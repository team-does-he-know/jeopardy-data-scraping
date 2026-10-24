#!/usr/bin/env python3
from bz2 import decompress
from multiprocessing import Pool
from xml.etree import ElementTree

from jeopardy_data_scraping import (
    PAGES_DATABASE_FILEPATH,
    SQLITE_PAGE_SIZE_BYTES,
    VITAL_ARTICLES_TITLE_PREFIX,
    WIKIPEDIA_DUMP_FILEPATH,
    WIKIPEDIA_INDEX_FILEPATH,
    MediaWikiContentModel,
    MediaWikiNamespace,
    flush_batch_to_database,
    initialize_bulk_write_database,
    load_multistream_byte_ranges,
)

# Buffered rows committed to SQLite per transaction.
DATABASE_TRANSACTION_BATCH_SIZE = 10000

# 100-page compressed blocks dispatched per worker at once.
WORKER_CHUNK_SIZE = 8

# String namespace representations for XML tag comparison.
MAIN_NAMESPACE_TEXT = str(MediaWikiNamespace.MAIN)
PROJECT_NAMESPACE_TEXT = str(MediaWikiNamespace.PROJECT)

# Namespaces checked before inspecting full XML page elements.
ALLOWED_NAMESPACES = {MAIN_NAMESPACE_TEXT, PROJECT_NAMESPACE_TEXT}

# SQLite table schema for ingested Wikipedia pages.
PAGES_TABLE_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY,
        namespace INTEGER,
        title TEXT,
        content TEXT
    );
"""

# SQLite statement for inserting buffered page records.
INSERT_PAGE_SQL = "INSERT OR IGNORE INTO pages VALUES (?, ?, ?, ?)"

# Persistent dump file handle opened once per worker process.
WORKER_DUMP_FILE = None


def initialize_worker():
    """Opens a persistent read-only dump file handle per worker process."""
    global WORKER_DUMP_FILE

    WORKER_DUMP_FILE = open(WIKIPEDIA_DUMP_FILEPATH, "rb")


def is_valid_main_article(namespace, title, has_redirect, model):
    """Returns True if a page is a non-redirect Wikitext article in the main namespace."""
    return (
        namespace == MAIN_NAMESPACE_TEXT
        and not has_redirect
        and model == MediaWikiContentModel.WIKITEXT
        and bool(title)
    )


def is_valid_vital_article(namespace, title, has_redirect, model):
    """Returns True if a page is a non-redirect Vital Articles list in the project namespace."""
    return (
        namespace == PROJECT_NAMESPACE_TEXT
        and not has_redirect
        and model == MediaWikiContentModel.WIKITEXT
        and title.startswith(VITAL_ARTICLES_TITLE_PREFIX)
    )


def extract_page_record(page_element):
    """Extracts an (id, namespace, title, content) tuple from a valid XML page."""
    namespace_text = page_element.findtext("ns")

    if namespace_text not in ALLOWED_NAMESPACES:
        return None

    has_redirect = page_element.find("redirect") is not None
    title_text = page_element.findtext("title") or ""
    model_text = page_element.findtext("revision/model")

    if not (
        is_valid_main_article(namespace_text, title_text, has_redirect, model_text)
        or is_valid_vital_article(namespace_text, title_text, has_redirect, model_text)
    ):
        return None

    page_id_text = page_element.findtext("id")
    raw_wikitext = page_element.findtext("revision/text")

    if not (page_id_text and raw_wikitext):
        return None

    return (int(page_id_text), int(namespace_text), title_text, raw_wikitext)


def process_compressed_xml_block(byte_range):
    """Seeks, decompresses, parses XML, and extracts page records for one block."""
    start_offset, block_size = byte_range

    WORKER_DUMP_FILE.seek(start_offset)
    compressed_block = WORKER_DUMP_FILE.read(block_size)

    if len(compressed_block) < block_size:
        print(f"Warning: Reached unexpected end of file at offset {start_offset}.")
        return []

    try:
        xml_fragment = decompress(compressed_block).decode("utf-8", errors="replace")
    except (OSError, ValueError) as error:
        print(f"Warning: Failed to decompress block at offset {start_offset}: {error}")
        return []

    first_page_index = xml_fragment.find("<page>")
    last_page_index = xml_fragment.rfind("</page>")

    if first_page_index == -1 or last_page_index == -1:
        return []

    clean_pages_xml = xml_fragment[first_page_index : last_page_index + 7]
    root_element = ElementTree.fromstring(f"<root>{clean_pages_xml}</root>")

    return [
        record
        for page_element in root_element
        if (record := extract_page_record(page_element)) is not None
    ]


def execute_ingestion_pipeline():
    """Coordinates parallel block processing and sequential SQLite batch writes."""
    database_connection = initialize_bulk_write_database(
        PAGES_DATABASE_FILEPATH,
        PAGES_TABLE_SCHEMA_SQL,
        page_size=SQLITE_PAGE_SIZE_BYTES,
    )

    page_batch = []
    total_persisted_pages = 0

    print("Loading multistream index into memory...")
    byte_ranges = load_multistream_byte_ranges(
        WIKIPEDIA_INDEX_FILEPATH, WIKIPEDIA_DUMP_FILEPATH
    )
    print(f"Loaded {len(byte_ranges):,} block offsets. Starting extraction...")

    with Pool(initializer=initialize_worker) as worker_pool:
        processed_blocks = worker_pool.imap_unordered(
            process_compressed_xml_block, byte_ranges, chunksize=WORKER_CHUNK_SIZE
        )

        for block_pages in processed_blocks:
            page_batch.extend(block_pages)

            if len(page_batch) >= DATABASE_TRANSACTION_BATCH_SIZE:
                total_persisted_pages += len(page_batch)

                flush_batch_to_database(
                    database_connection, INSERT_PAGE_SQL, page_batch
                )

                print(f"Persisted {total_persisted_pages:,} pages...")

    if page_batch:
        total_persisted_pages += len(page_batch)

        flush_batch_to_database(database_connection, INSERT_PAGE_SQL, page_batch)

    print("Building index on pages...")

    database_connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_pages_namespace_title ON pages(namespace, title);"
    )

    database_connection.close()
    print(f"Done. Total pages persisted: {total_persisted_pages:,}.")


if __name__ == "__main__":
    execute_ingestion_pipeline()
