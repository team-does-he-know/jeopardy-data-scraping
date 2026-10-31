#!/usr/bin/env python3
from itertools import batched
from json import dumps
from multiprocessing import Pool
from urllib.error import URLError

from jeopardy_data_scraping import (
    CLASSIFIED_DATABASE_FILEPATH,
    FACTOIDS_DATABASE_FILEPATH,
    SQLITE_PAGE_SIZE_BYTES,
    flush_batch_to_database,
    initialize_bulk_write_database,
    open_readonly_database,
    request_chat_completion,
)

# Concurrent LLM classification requests dispatched to LM Studio at once.
MAX_CONCURRENT_REQUESTS = 4

# Factoid records bundled into a single LLM classification prompt.
CLASSIFICATION_PROMPT_BATCH_SIZE = 50

# Buffered factoid records committed to SQLite per transaction.
DATABASE_TRANSACTION_BATCH_SIZE = 500

# Factoid ID batches dispatched per worker at once.
WORKER_CHUNK_SIZE = 1

# Maximum seconds to wait before aborting an LLM request.
REQUEST_TIMEOUT_SECONDS = 60 * 10

# Sampling parameters for deterministic factoid classification.
GENERATION_TEMPERATURE = 0.2  # Keeps drift due to randomness low.
GENERATION_SEED = 2713179051  # Random seed picked via RNG.

# System prompt governing factoid classification.
SYSTEM_PROMPT = """Classify and enrich each trivia clue-and-response pair in the input array.

### Scope & Coverage
- Return one classification object per input item in exact order, matched by "id".
- Grade difficulty against a global standard of general cultural familiarity, not relative to the current batch.

### Field Requirements
- "id": The exact integer identifier from the input item.
- "difficulty": An integer (1-5) rating how hard it is to identify the target entity from the clue, weighing both entity fame and clue specificity:
  - 1 (Household): Universally known entity paired with its most famous, defining fact.
  - 2 (Casual): Known to anyone with a passing interest in the broad subject area.
  - 3 (Intermediate): Standard trivia requiring active recall or solid familiarity with the topic.
  - 4 (Specialist): Niche entities, specific creators, sub-concepts, or granular details.
  - 5 (Obscure): Deep-cut facts, minor figures, exact dates, or arcane technical trivia.
- "question_entity": The bare canonical entity name from "question" with exact original spelling, stripping the leading interrogative, linking verb (ex. "What is", "Who are"), and trailing question mark.
- "answer_tags": An array of 2 to 4 concise, lowercase strings representing concrete entities, domains, or key concepts explicitly mentioned in "answer".
  - Use lowercase and singular common nouns (ex. ["apollo 11", "microbiology", "1969"]).
  - Omit generic filler words, the "question_entity", and any variations of the "question_entity".

### Grounding Constraints
- Derive "question_entity" and "answer_tags" strictly from the input text, using external knowledge only to calibrate "difficulty"."""

# JSON Schema enforcing structured trivia classification and enrichment output.
CLASSIFICATION_SCHEMA = {
    "name": "trivia_factoid_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "description": "A list of difficulty ratings and metadata enrichments corresponding in exact order to the input trivia factoids.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "integer",
                            "description": "The exact integer identifier from the input item.",
                        },
                        "difficulty": {
                            "type": "integer",
                            "enum": [1, 2, 3, 4, 5],
                            "description": "Global difficulty rating from 1 (Household) to 5 (Obscure) based on entity fame and clue specificity.",
                        },
                        "question_entity": {
                            "type": "string",
                            "description": "The bare canonical entity name extracted from the 'question' field.",
                        },
                        "answer_tags": {
                            "type": "array",
                            "description": "2 to 4 concise, lowercase, singular strings representing concrete entities, domains, or key concepts in the 'answer' field, excluding the question_entity.",
                            "items": {
                                "type": "string",
                            },
                        },
                    },
                    "required": ["id", "difficulty", "question_entity", "answer_tags"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["classifications"],
        "additionalProperties": False,
    },
}

# SQLite table schema for classified factoids, categories, tags, and relationships.
CLASSIFIED_TABLE_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS factoids (
        id INTEGER PRIMARY KEY,
        article_id INTEGER,
        question TEXT,
        answer TEXT,
        difficulty INTEGER,
        question_entity TEXT
    );

    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY,
        title TEXT
    );

    CREATE TABLE IF NOT EXISTS factoid_categories (
        factoid_id INTEGER,
        category_id INTEGER
    );

    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY,
        name TEXT
    );

    CREATE TABLE IF NOT EXISTS factoid_tags (
        factoid_id INTEGER,
        tag_id INTEGER
    );
"""

# SQLite statements for inserting buffered records.
INSERT_FACTOID_SQL = "INSERT INTO factoids VALUES (?, ?, ?, ?, ?, ?)"
INSERT_FACTOID_CATEGORY_SQL = "INSERT INTO factoid_categories VALUES (?, ?)"
INSERT_FACTOID_TAG_SQL = "INSERT INTO factoid_tags VALUES (?, ?)"

# Persistent read-only database connection opened once per worker process.
WORKER_DATABASE_CONNECTION = None


def initialize_worker():
    """Opens a persistent read-only SQLite connection per worker process."""
    global WORKER_DATABASE_CONNECTION

    WORKER_DATABASE_CONNECTION = open_readonly_database(FACTOIDS_DATABASE_FILEPATH)


def load_factoids_metadata():
    """Loads categories, factoid-to-category mappings, and factoid IDs."""
    with open_readonly_database(FACTOIDS_DATABASE_FILEPATH) as database_connection:
        categories = dict(
            database_connection.execute("SELECT id, title FROM categories")
        )

        factoid_to_categories = {}
        cursor = database_connection.execute(
            "SELECT factoid_id, category_id FROM factoid_categories"
        )

        for factoid_id, category_id in cursor:
            factoid_to_categories.setdefault(factoid_id, []).append(category_id)

        factoid_ids = [
            row[0]
            for row in database_connection.execute(
                "SELECT id FROM factoids ORDER BY id"
            )
        ]

    return categories, factoid_to_categories, factoid_ids


def request_factoid_classifications(factoid_items):
    """Sends a batch of factoids to the local LLM server and returns classification dicts."""
    parsed_content = request_chat_completion(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=dumps(factoid_items, ensure_ascii=False),
        response_schema=CLASSIFICATION_SCHEMA,
        temperature=GENERATION_TEMPERATURE,
        seed=GENERATION_SEED,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    return parsed_content.get("classifications", [])


def process_factoid_batch(factoid_id_batch):
    """Queries a batch of factoids and extracts validated classification tuples via LLM."""
    placeholders = ", ".join("?" for _ in factoid_id_batch)
    rows = WORKER_DATABASE_CONNECTION.execute(
        f"SELECT id, article_id, question, answer FROM factoids WHERE id IN ({placeholders})",
        factoid_id_batch,
    ).fetchall()

    if not rows:
        return []

    factoids_by_id = {
        factoid_id: (article_id, question, answer)
        for factoid_id, article_id, question, answer in rows
    }

    prompt_items = [
        {"id": factoid_id, "question": question, "answer": answer}
        for factoid_id, _, question, answer in rows
    ]

    try:
        raw_classifications = request_factoid_classifications(prompt_items)
    except (URLError, TimeoutError, KeyError, ValueError) as error:
        print(
            f"Warning: Failed to classify factoid batch "
            f"{factoid_id_batch[0]}..{factoid_id_batch[-1]}: {error}"
        )

        return []

    valid_records = []

    for item in raw_classifications:
        factoid_id = item.get("id")
        question_entity = item.get("question_entity", "").strip().lower()
        factoid_data = factoids_by_id.pop(factoid_id, None)

        if factoid_data is None or not question_entity:
            continue

        cleaned_tags = tuple(
            {
                cleaned_tag
                for tag in item.get("answer_tags", ())
                if (cleaned_tag := tag.strip().lower())
            }
        )

        article_id, question, answer = factoid_data

        valid_records.append(
            (
                factoid_id,
                article_id,
                question,
                answer,
                item["difficulty"],
                question_entity,
                cleaned_tags,
            )
        )

    return valid_records


def execute_classification_pipeline():
    """Coordinates concurrent LLM factoid classification and sequential SQLite writes."""
    database_connection = initialize_bulk_write_database(
        CLASSIFIED_DATABASE_FILEPATH,
        CLASSIFIED_TABLE_SCHEMA_SQL,
        page_size=SQLITE_PAGE_SIZE_BYTES,
    )

    print("Loading metadata from factoids database...")
    categories, factoid_to_categories, factoid_ids = load_factoids_metadata()
    factoid_id_batches = list(batched(factoid_ids, CLASSIFICATION_PROMPT_BATCH_SIZE))

    print(
        f"Loaded {len(factoid_ids):,} factoids across {len(categories):,} categories "
        f"({len(factoid_id_batches):,} batches). "
        f"Starting classification with {MAX_CONCURRENT_REQUESTS} concurrent workers..."
    )

    factoid_batch = []
    category_link_batch = []
    tag_link_batch = []
    tag_name_to_id = {}
    used_category_ids = set()
    total_persisted_factoids = 0
    processed_batch_count = 0

    with Pool(
        processes=MAX_CONCURRENT_REQUESTS, initializer=initialize_worker
    ) as worker_pool:
        processed_batches = worker_pool.imap_unordered(
            process_factoid_batch,
            factoid_id_batches,
            chunksize=WORKER_CHUNK_SIZE,
        )

        for classified_records in processed_batches:
            processed_batch_count += 1

            for (
                factoid_id,
                article_id,
                question,
                answer,
                difficulty,
                question_entity,
                answer_tags,
            ) in classified_records:
                factoid_batch.append(
                    (
                        factoid_id,
                        article_id,
                        question,
                        answer,
                        difficulty,
                        question_entity,
                    )
                )

                for category_id in factoid_to_categories.get(factoid_id, ()):
                    category_link_batch.append((factoid_id, category_id))
                    used_category_ids.add(category_id)

                for tag_name in answer_tags:
                    if (tag_id := tag_name_to_id.get(tag_name)) is None:
                        tag_id = len(tag_name_to_id) + 1
                        tag_name_to_id[tag_name] = tag_id

                    tag_link_batch.append((factoid_id, tag_id))

            if len(factoid_batch) >= DATABASE_TRANSACTION_BATCH_SIZE:
                total_persisted_factoids += len(factoid_batch)

                flush_batch_to_database(
                    database_connection, INSERT_FACTOID_SQL, factoid_batch
                )

                flush_batch_to_database(
                    database_connection,
                    INSERT_FACTOID_CATEGORY_SQL,
                    category_link_batch,
                )

                flush_batch_to_database(
                    database_connection, INSERT_FACTOID_TAG_SQL, tag_link_batch
                )

                print(
                    f"Persisted {total_persisted_factoids:,} classified factoids "
                    f"({processed_batch_count:,}/{len(factoid_id_batches):,} batches, "
                    f"{len(tag_name_to_id):,} unique tags)..."
                )

    if factoid_batch:
        total_persisted_factoids += len(factoid_batch)

        flush_batch_to_database(database_connection, INSERT_FACTOID_SQL, factoid_batch)

        flush_batch_to_database(
            database_connection, INSERT_FACTOID_CATEGORY_SQL, category_link_batch
        )

        flush_batch_to_database(
            database_connection, INSERT_FACTOID_TAG_SQL, tag_link_batch
        )

    print(f"Persisting {len(used_category_ids):,} active categories...")
    database_connection.executemany(
        "INSERT INTO categories VALUES (?, ?)",
        (
            (category_id, categories[category_id])
            for category_id in used_category_ids
            if category_id in categories
        ),
    )

    print(f"Persisting {len(tag_name_to_id):,} unique tags...")
    database_connection.executemany(
        "INSERT INTO tags VALUES (?, ?)",
        ((tag_id, tag_name) for tag_name, tag_id in tag_name_to_id.items()),
    )

    database_connection.commit()

    print("Building indexes on classified database...")
    database_connection.executescript("""
        CREATE INDEX IF NOT EXISTS idx_factoids_article_id
        ON factoids(article_id);

        CREATE INDEX IF NOT EXISTS idx_factoids_difficulty
        ON factoids(difficulty);

        CREATE INDEX IF NOT EXISTS idx_factoids_question_entity
        ON factoids(question_entity);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_title
        ON categories(title);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_factoid_categories_factoid_category
        ON factoid_categories(factoid_id, category_id);

        CREATE INDEX IF NOT EXISTS idx_factoid_categories_category_id
        ON factoid_categories(category_id);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_name
        ON tags(name);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_factoid_tags_factoid_tag
        ON factoid_tags(factoid_id, tag_id);

        CREATE INDEX IF NOT EXISTS idx_factoid_tags_tag_id
        ON factoid_tags(tag_id);
    """)

    database_connection.close()
    print(
        f"Done. Total classified factoids persisted: {total_persisted_factoids:,} "
        f"across {len(used_category_ids):,} categories and {len(tag_name_to_id):,} tags."
    )


if __name__ == "__main__":
    execute_classification_pipeline()
