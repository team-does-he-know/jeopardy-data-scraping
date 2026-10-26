#!/usr/bin/env python3
from multiprocessing import Pool
from urllib.error import URLError

from jeopardy_data_scraping import (
    FACTOIDS_DATABASE_FILEPATH,
    FILTERED_DATABASE_FILEPATH,
    SQLITE_PAGE_SIZE_BYTES,
    flush_batch_to_database,
    initialize_bulk_write_database,
    open_readonly_database,
    request_chat_completion,
)

# Concurrent LLM generation requests dispatched to LM Studio at once.
MAX_CONCURRENT_REQUESTS = 4

# Buffered factoid records committed to SQLite per transaction.
DATABASE_TRANSACTION_BATCH_SIZE = 500

# Candidate articles dispatched per worker at once.
WORKER_CHUNK_SIZE = 1

# Sampling and penalty parameters for deterministic factoid extraction.
GENERATION_TEMPERATURE = 0.2  # Keeps drift due to randomness low.
GENERATION_SEED = 2713179051  # Random seed picked via RNG.
GENERATION_PRESENCE_PENALTY = (
    0.2  # Pushes the LLM to avoid too many repetitive tokens, flatly.
)
GENERATION_FREQUENCY_PENALTY = (
    0.01  # Nudges the LLM to avoid too many repetitive tokens, scaled.
)

# System prompt governing atomic trivia factoid extraction.
SYSTEM_PROMPT = """Extract a comprehensive list of trivia clue-and-response pairs from the source text.

### Scope & Coverage
- Process the text systematically from top to bottom, extracting distinct, granular factoids from every section rather than skimming high-level summaries or clustering in the lead.
- Actively vary target entities: target both the primary subject and notable secondary entities (people, places, organizations, works, concepts, inventions, or discoveries).
- Once all distinct facts are extracted, close the array immediately without creating partial or filler items.

### Field Requirements
- "question": Format strictly as "<Interrogative> <is/are> <Bare Canonical Entity Name>?" (ex. "What is...?", "Who is...?", "Who are...?", "Where is...?").
  - Include only the interrogative, linking verb, and bare canonical name. Omit actions, extra context, and parenthetical disambiguations (ex. "(band)").
  - Omit leading articles ("the", "a", "an") unless part of an official title, and omit trailing category labels (ex. write "penicillin" instead of "the penicillin discovery").
  - Use sentence-interior capitalization: capitalize only formal proper nouns and official titles, keep common nouns and concepts lowercase (ex. "photosynthesis", "continental drift") regardless of source formatting.
- "answer": A standalone, atomic clue containing one single fact that uniquely identifies the target entity.
  - Refer to the target entity with a specific descriptor (ex. "This author", "This 1996 album") and vary your sentence structure.
  - Target ~15 words or fewer using direct, active phrasing without sacrificing uniqueness or identifying detail.
  - Make every clue self-contained: replace pronouns (ex. "he", "she", "it", "they") with explicit names, and explicitly name the primary article topic when targeting a secondary entity (ex. state "Apollo 11" instead of "the mission").
  - Preserve the source text's original wording and spirit.
  - Strictly omit the target entity's name, abbreviations, and any shared root words or proper nouns from the "question" field.

### Grounding Constraints
- Use only facts explicitly stated in the text, omit external knowledge, inferences, and opinions."""

# JSON Schema enforcing structured trivia factoid output.
FACTOID_SCHEMA = {
    "name": "trivia_factoid_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "factoids": {
                "type": "array",
                "description": "A comprehensive list of distinct, atomic trivia pairs extracted across all sections of the source text.",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The canonical target entity formatted strictly as '<Interrogative> <is/are> <Entity Name>?' with proper capitalization.",
                        },
                        "answer": {
                            "type": "string",
                            "description": "A standalone, concise clue uniquely identifying the target entity without naming it or sharing its root words.",
                        },
                    },
                    "required": ["question", "answer"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["factoids"],
        "additionalProperties": False,
    },
}

# SQLite table schema for generated factoids, categories, and relationships.
FACTOIDS_TABLE_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS factoids (
        id INTEGER PRIMARY KEY,
        article_id INTEGER,
        question TEXT,
        answer TEXT
    );

    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY,
        title TEXT
    );

    CREATE TABLE IF NOT EXISTS factoid_categories (
        factoid_id INTEGER,
        category_id INTEGER
    );
"""

# SQLite statements for inserting buffered records.
INSERT_FACTOID_SQL = "INSERT INTO factoids VALUES (?, ?, ?, ?)"
INSERT_CATEGORY_SQL = "INSERT INTO categories VALUES (?, ?)"
INSERT_FACTOID_CATEGORY_SQL = "INSERT INTO factoid_categories VALUES (?, ?)"

# Persistent read-only database connection opened once per worker process.
WORKER_DATABASE_CONNECTION = None


def initialize_worker():
    """Opens a persistent read-only SQLite connection per worker process."""
    global WORKER_DATABASE_CONNECTION

    WORKER_DATABASE_CONNECTION = open_readonly_database(FILTERED_DATABASE_FILEPATH)


def load_filtered_metadata():
    """Loads categories, article-to-category mappings, and article IDs."""
    with open_readonly_database(FILTERED_DATABASE_FILEPATH) as database_connection:
        categories = dict(
            database_connection.execute("SELECT id, title FROM categories")
        )

        article_to_categories = {}
        cursor = database_connection.execute(
            "SELECT article_id, category_id FROM article_categories"
        )

        for article_id, category_id in cursor:
            article_to_categories.setdefault(article_id, []).append(category_id)

        article_ids = [
            row[0]
            for row in database_connection.execute(
                "SELECT id FROM articles ORDER BY id"
            )
        ]

    return categories, article_to_categories, article_ids


def request_article_factoids(title, plain_text):
    """Sends an article to the local LLM server and returns extracted factoid dicts."""
    parsed_content = request_chat_completion(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Title: {title}\n\n{plain_text}",
        response_schema=FACTOID_SCHEMA,
        temperature=GENERATION_TEMPERATURE,
        seed=GENERATION_SEED,
        presence_penalty=GENERATION_PRESENCE_PENALTY,
        frequency_penalty=GENERATION_FREQUENCY_PENALTY,
    )

    return parsed_content.get("factoids", [])


def process_article(article_id):
    """Queries an article and extracts validated (question, answer) tuples via LLM."""
    row = WORKER_DATABASE_CONNECTION.execute(
        "SELECT title, plain_text FROM articles WHERE id = ?",
        (article_id,),
    ).fetchone()

    if row is None:
        return (article_id, [])

    title, plain_text = row

    try:
        raw_factoids = request_article_factoids(title, plain_text)
    except (URLError, KeyError, ValueError) as error:
        print(
            f"Warning: Failed to extract factoids for article {article_id} ({title}): {error}"
        )

        return (article_id, [])

    valid_factoids = [
        (question, answer)
        for item in raw_factoids
        if (question := item.get("question", "").strip())
        and (answer := item.get("answer", "").strip())
    ]

    return (article_id, valid_factoids)


def execute_factoids_pipeline():
    """Coordinates concurrent LLM factoid generation and sequential SQLite writes."""
    database_connection = initialize_bulk_write_database(
        FACTOIDS_DATABASE_FILEPATH,
        FACTOIDS_TABLE_SCHEMA_SQL,
        page_size=SQLITE_PAGE_SIZE_BYTES,
    )

    print("Loading metadata from filtered database...")
    categories, article_to_categories, article_ids = load_filtered_metadata()
    print(
        f"Loaded {len(article_ids):,} articles across {len(categories):,} categories. "
        f"Starting generation with {MAX_CONCURRENT_REQUESTS} concurrent workers..."
    )

    factoid_batch = []
    link_batch = []
    used_category_ids = set()
    total_persisted_factoids = 0
    processed_article_count = 0
    next_factoid_id = 1

    with Pool(
        processes=MAX_CONCURRENT_REQUESTS, initializer=initialize_worker
    ) as worker_pool:
        processed_articles = worker_pool.imap_unordered(
            process_article,
            article_ids,
            chunksize=WORKER_CHUNK_SIZE,
        )

        for article_id, extracted_factoids in processed_articles:
            processed_article_count += 1

            if not extracted_factoids:
                continue

            article_categories = article_to_categories.get(article_id, ())

            for question, answer in extracted_factoids:
                factoid_id = next_factoid_id
                next_factoid_id += 1

                factoid_batch.append((factoid_id, article_id, question, answer))

                for category_id in article_categories:
                    link_batch.append((factoid_id, category_id))
                    used_category_ids.add(category_id)

            if len(factoid_batch) >= DATABASE_TRANSACTION_BATCH_SIZE:
                total_persisted_factoids += len(factoid_batch)

                flush_batch_to_database(
                    database_connection, INSERT_FACTOID_SQL, factoid_batch
                )

                flush_batch_to_database(
                    database_connection, INSERT_FACTOID_CATEGORY_SQL, link_batch
                )

                print(
                    f"Persisted {total_persisted_factoids:,} factoids "
                    f"({processed_article_count:,}/{len(article_ids):,} articles)..."
                )

    if factoid_batch:
        total_persisted_factoids += len(factoid_batch)

        flush_batch_to_database(database_connection, INSERT_FACTOID_SQL, factoid_batch)
        flush_batch_to_database(
            database_connection, INSERT_FACTOID_CATEGORY_SQL, link_batch
        )

    surviving_categories = [
        (category_id, title)
        for category_id, title in categories.items()
        if category_id in used_category_ids
    ]

    print(f"Persisting {len(surviving_categories):,} active categories...")
    database_connection.executemany(INSERT_CATEGORY_SQL, surviving_categories)
    database_connection.commit()

    print("Building indexes on factoids database...")
    database_connection.executescript("""
        CREATE INDEX IF NOT EXISTS idx_factoids_article_id
        ON factoids(article_id);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_title
        ON categories(title);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_factoid_categories_factoid_category
        ON factoid_categories(factoid_id, category_id);

        CREATE INDEX IF NOT EXISTS idx_factoid_categories_category_id
        ON factoid_categories(category_id);
    """)

    database_connection.close()
    print(
        f"Done. Total factoids persisted: {total_persisted_factoids:,} "
        f"across {len(surviving_categories):,} categories."
    )


if __name__ == "__main__":
    execute_factoids_pipeline()
