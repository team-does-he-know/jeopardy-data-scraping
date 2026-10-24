from bz2 import open as bz2open
from os import cpu_count
from pathlib import Path
from sqlite3 import connect

# SQLite cache limit, negative values set KiB (-2000000 ≈ 2 GiB).
SQLITE_CACHE_SIZE_KIBIBYTES = -2000000

# SQLite page size in bytes (65536 = 64 KiB, reduces overflow chaining for large text).
SQLITE_PAGE_SIZE_BYTES = 65536

# SQLite memory-mapped I/O limit in bytes (32212254720 = 30 GiB).
SQLITE_MMAP_SIZE_BYTES = 32212254720

# Helper threads allocated to SQLite for parallel index sorting.
SQLITE_WORKER_THREADS = cpu_count() or 1


def flush_batch_to_database(database_connection, insert_sql, record_batch):
    """Writes buffered records to SQLite in one transaction and clears the batch."""
    database_connection.executemany(insert_sql, record_batch)
    database_connection.commit()
    record_batch.clear()


def initialize_bulk_write_database(database_filepath, schema_sql, page_size=None):
    """Initializes a SQLite database with fast bulk-write pragmas and schema."""
    database_connection = connect(database_filepath)

    pragma_page_size_sql = (
        f"PRAGMA page_size = {page_size};" if page_size is not None else ""
    )

    database_connection.executescript(f"""
        {pragma_page_size_sql}

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

        -- Use available CPU cores to parallelize B-tree sorting during index creation.
        PRAGMA threads = {SQLITE_WORKER_THREADS};

        {schema_sql}
    """)

    return database_connection


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
        byte_ranges.append(
            (previous_offset, Path(dump_filepath).stat().st_size - previous_offset)
        )

    return byte_ranges
