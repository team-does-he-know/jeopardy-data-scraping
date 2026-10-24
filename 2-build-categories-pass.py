#!/usr/bin/env python3
from multiprocessing import Pool
from re import IGNORECASE, compile

from jeopardy_data_scraping import (
    CATEGORIES_DATABASE_FILEPATH,
    PAGES_DATABASE_FILEPATH,
    MediaWikiNamespace,
    flush_batch_to_database,
    initialize_bulk_write_database,
    load_page_id_ranges,
    open_readonly_database,
)

# Buffered article-category links committed to SQLite per transaction.
DATABASE_TRANSACTION_BATCH_SIZE = 100000

# Span of page IDs queried per worker task.
PAGE_ID_RANGE_SIZE = 100000

# Page ID ranges dispatched per worker at once.
WORKER_CHUNK_SIZE = 1

# Pattern matching standard MediaWiki category links (ex. [[Category:Title|Sortkey]]).
CATEGORY_LINK_PATTERN = compile(r"\[\[Category:([^|\]]+)(?:\|[^\]]*)?\]\]", IGNORECASE)

# SQLite table schema for categories and article-category relationships.
CATEGORIES_TABLE_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY,
        title TEXT
    );

    CREATE TABLE IF NOT EXISTS article_categories (
        article_id INTEGER,
        category_id INTEGER
    );
"""

# SQLite statement for inserting buffered article-category link records.
INSERT_ARTICLE_CATEGORY_SQL = "INSERT INTO article_categories VALUES (?, ?)"

# Persistent read-only database connection opened once per worker process.
WORKER_DATABASE_CONNECTION = None


def initialize_worker():
    """Opens a persistent read-only SQLite connection per worker process."""
    global WORKER_DATABASE_CONNECTION

    WORKER_DATABASE_CONNECTION = open_readonly_database(PAGES_DATABASE_FILEPATH)


def normalize_category_title(raw_title):
    """Normalizes category spacing and capitalizes the first character."""
    cleaned_title = raw_title.strip().replace("_", " ")

    return cleaned_title[0].upper() + cleaned_title[1:] if cleaned_title else ""


def extract_article_categories(raw_wikitext):
    """Extracts a deduplicated tuple of normalized category titles from Wikitext."""
    return tuple(
        {
            normalized_title
            for match in CATEGORY_LINK_PATTERN.findall(raw_wikitext)
            if (normalized_title := normalize_category_title(match))
        }
    )


def process_page_id_range(id_range):
    """Queries pages within an ID range and extracts (article_id, categories) tuples."""
    start_id, end_id = id_range

    cursor = WORKER_DATABASE_CONNECTION.execute(
        "SELECT id, content FROM pages WHERE id >= ? AND id < ? AND namespace = ?",
        (start_id, end_id, MediaWikiNamespace.MAIN),
    )

    return [
        (article_id, categories)
        for article_id, raw_wikitext in cursor
        if (categories := extract_article_categories(raw_wikitext))
    ]


def execute_categories_pipeline():
    """Coordinates parallel category extraction and sequential SQLite batch writes."""
    database_connection = initialize_bulk_write_database(
        CATEGORIES_DATABASE_FILEPATH, CATEGORIES_TABLE_SCHEMA_SQL
    )

    category_title_to_id = {}
    link_batch = []
    total_persisted_links = 0

    print("Calculating page ID ranges from source database...")
    id_ranges = load_page_id_ranges(PAGES_DATABASE_FILEPATH, PAGE_ID_RANGE_SIZE)
    print(f"Loaded {len(id_ranges):,} ID ranges. Starting category extraction...")

    with Pool(initializer=initialize_worker) as worker_pool:
        processed_ranges = worker_pool.imap_unordered(
            process_page_id_range, id_ranges, chunksize=WORKER_CHUNK_SIZE
        )

        for range_records in processed_ranges:
            for article_id, category_titles in range_records:
                for title in category_titles:
                    if (category_id := category_title_to_id.get(title)) is None:
                        category_id = len(category_title_to_id) + 1
                        category_title_to_id[title] = category_id

                    link_batch.append((article_id, category_id))

            if len(link_batch) >= DATABASE_TRANSACTION_BATCH_SIZE:
                total_persisted_links += len(link_batch)

                flush_batch_to_database(
                    database_connection, INSERT_ARTICLE_CATEGORY_SQL, link_batch
                )

                print(
                    f"Persisted {total_persisted_links:,} category links "
                    f"({len(category_title_to_id):,} unique categories)..."
                )

    if link_batch:
        total_persisted_links += len(link_batch)

        flush_batch_to_database(
            database_connection, INSERT_ARTICLE_CATEGORY_SQL, link_batch
        )

    print(f"Persisting {len(category_title_to_id):,} unique categories...")

    database_connection.executemany(
        "INSERT INTO categories VALUES (?, ?)",
        ((category_id, title) for title, category_id in category_title_to_id.items()),
    )

    database_connection.commit()

    print("Building indexes on categories database...")

    database_connection.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_title
        ON categories(title);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_article_categories_article_category
        ON article_categories(article_id, category_id);

        CREATE INDEX IF NOT EXISTS idx_article_categories_category_id
        ON article_categories(category_id);
    """)

    database_connection.close()
    print(
        f"Done. Total category links persisted: {total_persisted_links:,} "
        f"across {len(category_title_to_id):,} categories."
    )


if __name__ == "__main__":
    execute_categories_pipeline()
