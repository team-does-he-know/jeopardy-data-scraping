#!/usr/bin/env python3
from bz2 import decompress, open as bz2open
from multiprocessing import Pool
from os.path import getsize, join
from sqlite3 import connect
from xml.etree import ElementTree

ASSETS_DIRECTORY_PATH = "assets"

SQLITE_DATABASE_FILEPATH = join(
    ASSETS_DIRECTORY_PATH, "enwiki-20220501-pages-articles-multistream.db"
)

WIKIPEDIA_DUMP_FILEPATH = join(
    ASSETS_DIRECTORY_PATH, "enwiki-20220501-pages-articles-multistream.xml.bz2"
)

WIKIPEDIA_INDEX_FILEPATH = join(
    ASSETS_DIRECTORY_PATH, "enwiki-20220501-pages-articles-multistream-index.txt.bz2"
)

# Buffered rows committed to SQLite per transaction.
DATABASE_TRANSACTION_BATCH_SIZE = 10000

# SQLite cache limit, negative values set KiB (-2000000 ≈ 2 GiB).
SQLITE_CACHE_SIZE_KIBIBYTES = -2000000

# SQLite page size in bytes (65536 = 64 KiB, reduces overflow chaining for large text).
SQLITE_PAGE_SIZE_BYTES = 65536

# 100-page compressed blocks dispatched per worker at once.
WORKER_CHUNK_SIZE = 8

# MediaWiki namespace ID for encyclopedia articles (ex. Main / Article).
WIKIPEDIA_MAIN_NAMESPACE = "0"

# MediaWiki namespace ID for project pages and meta lists (ex. Wikipedia:).
WIKIPEDIA_PROJECT_NAMESPACE = "4"

# Namespaces checked before inspecting full XML page elements.
ALLOWED_NAMESPACES = {WIKIPEDIA_MAIN_NAMESPACE, WIKIPEDIA_PROJECT_NAMESPACE}

# Required revision content model for Wikitext pages.
WIKITEXT_CONTENT_MODEL = "wikitext"

# Title prefix identifying Vital Articles index and sub-list pages.
VITAL_ARTICLES_TITLE_PREFIX = "Wikipedia:Vital articles/"

# Persistent dump file handle opened once per worker process.
WORKER_DUMP_FILE = None


def initialize_worker():
    """Opens a persistent read-only dump file handle per worker process."""
    global WORKER_DUMP_FILE

    WORKER_DUMP_FILE = open(WIKIPEDIA_DUMP_FILEPATH, "rb")


def initialize_page_database():
    """Initializes the pages table and sets pragmas for fast bulk writes."""
    database_connection = connect(SQLITE_DATABASE_FILEPATH)

    database_connection.executescript(f"""
        -- Use 64 KiB pages to prevent large text rows from spanning overflow pages.
        PRAGMA page_size = {SQLITE_PAGE_SIZE_BYTES};

        -- Disable disk sync on commit to maximize write speed.
        PRAGMA synchronous = OFF;

        -- Disable rollback journaling for one-way bulk loading.
        PRAGMA journal_mode = OFF;

        -- Hold an exclusive lock to avoid acquiring/releasing OS file locks per commit.
        PRAGMA locking_mode = EXCLUSIVE;

        -- Store temp tables, indexes, and sort structures in RAM instead of disk.
        PRAGMA temp_store = MEMORY;

        -- Allocate RAM cache to hold database pages during processing.
        PRAGMA cache_size = {SQLITE_CACHE_SIZE_KIBIBYTES};

        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY,
            namespace INTEGER,
            title TEXT,
            content TEXT
        );
    """)

    return database_connection


def flush_batch_to_database(database_connection, page_batch):
    """Writes buffered page records to SQLite in one transaction."""
    database_connection.executemany(
        "INSERT OR IGNORE INTO pages VALUES (?, ?, ?, ?)", page_batch
    )

    database_connection.commit()
    page_batch.clear()


def load_multistream_byte_ranges(index_filepath, dump_filepath):
    """Reads index into memory and yields (start_offset, block_size) tuples."""
    byte_ranges = []
    previous_offset = None

    with bz2open(
        index_filepath, mode="rt", encoding="utf-8", errors="replace"
    ) as index_stream:
        for line in index_stream:
            current_offset = int(line.partition(":")[0])
            if previous_offset is not None and current_offset != previous_offset:
                byte_ranges.append((previous_offset, current_offset - previous_offset))
            previous_offset = current_offset

    if previous_offset is not None:
        byte_ranges.append((previous_offset, getsize(dump_filepath) - previous_offset))

    return byte_ranges


def is_valid_main_article(namespace, title, has_redirect, model):
    """Returns True if a page is a non-redirect Wikitext article in the main namespace."""
    return (
        namespace == WIKIPEDIA_MAIN_NAMESPACE
        and not has_redirect
        and model == WIKITEXT_CONTENT_MODEL
        and bool(title)
    )


def is_valid_vital_article(namespace, title, has_redirect, model):
    """Returns True if a page is a non-redirect Vital Articles list in the project namespace."""
    return (
        namespace == WIKIPEDIA_PROJECT_NAMESPACE
        and not has_redirect
        and model == WIKITEXT_CONTENT_MODEL
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
    database_connection = initialize_page_database()

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

                flush_batch_to_database(database_connection, page_batch)
                print(f"Persisted {total_persisted_pages:,} pages...")

    if page_batch:
        total_persisted_pages += len(page_batch)

        flush_batch_to_database(database_connection, page_batch)

    print("Building index on pages...")

    database_connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_pages_namespace_title ON pages(namespace, title);"
    )

    database_connection.close()
    print(f"Done. Total pages persisted: {total_persisted_pages:,}.")


if __name__ == "__main__":
    execute_ingestion_pipeline()
