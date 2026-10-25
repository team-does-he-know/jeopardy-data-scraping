#!/usr/bin/env python3
from multiprocessing import Pool
from re import IGNORECASE, compile

from jeopardy_data_scraping import (
    CATEGORIES_DATABASE_FILEPATH,
    FILTERED_DATABASE_FILEPATH,
    PAGES_DATABASE_FILEPATH,
    SQLITE_PAGE_SIZE_BYTES,
    MediaWikiNamespace,
    flush_batch_to_database,
    initialize_bulk_write_database,
    open_readonly_database,
    render_wikitext_to_plaintext,
)

# Curated category titles to include in the filtered dataset.
CATEGORY_WHITELIST = (
    # Pokémon
    "Pokémon",
    "Pokémon buildings and structures",
    "Pokémon films",
    "Pokémon video games",
    "Pokémon introduced in generation I",
    "Pokémon introduced in generation II",
    "Pokémon introduced in generation III",
    "Pokémon introduced in generation IV",
    # Vidya Game Score Composers
    "Video games scored by C418",
    "Video games scored by Darren Korb",
    "Video games scored by Kelly Bailey",
    "Video games scored by Martin O'Donnell",
    "Video games scored by Michael Salvatori",
    "Video games scored by Mike Morasky",
    # Vidya Game Franchises
    "Bayonetta",
    "Castlevania games",
    "Devil May Cry games",
    "Fallout (franchise) video games",
    "Fire Emblem video games",
    "Half-Life (series) games",
    "Hades (series)",
    "Halo (franchise) games",
    "Metal Gear video games",
    "Minecraft",
    "Persona (series)",
    "Star Wars video games",
    "The Elder Scrolls",
    "The Legend of Zelda video games",
    # Vidya Game Developers
    "Atlus games",
    "Bethesda Game Studios games",
    "Bungie games",
    "Konami games",
    "Intelligent Systems games",
    "PlatinumGames games",
    "Re-Logic games",
    "Rockstar Games games",
    "Nintendo Classics games",
    "Nintendo Entertainment Analysis & Development games",
    "Sega video games",
    "Supergiant Games games",
    "Valve Corporation games",
    # Vidya Game Genres
    "3D platformers",
    "Action-adventure games",
    "Action role-playing video games",
    "Dungeon crawler video games",
    "First-person adventure games",
    "First-person shooters",
    "Hack and slash games",
    "Indie games",
    "Metroidvania games",
    "Open-world video games",
    "Psychological horror games",
    "Puzzle-platformers",
    "Roguelike video games",
    "Role-playing video games",
    "Sandbox games",
    "Shooter games",
    "Stealth video games",
    "Survival video games",
    "Survival horror video games",
    "Third-person shooters",
    "Turn-based role-playing video games",
    "Twin-stick shooters",
    # Vidya Game Mechanics
    "Video games using procedural generation",
    "Video games with time manipulation",
    # Vidya Game Visual Presentation
    "Video games with isometric graphics",
    # Vidya Game Narrative Devices
    "Metafictional video games",
    "Video games with unreliable narrators",
    # Vidya Game Continuity and Releases
    "Prequel video games",
    "Sequel video games",
    "Video game interquels",
    # Vidya Game Topics
    "Alternate history video games",
    "Apocalyptic video games",
    "Cyberpunk video games",
    "Dark fantasy video games",
    "Dystopian video games",
    "Existentialist video games",
    "Fantasy video games",
    "Military science fiction video games",
    "Post-apocalyptic video games",
    "Retro-style video games",
    "Retrofuturistic video games",
    "Science fantasy video games",
    "Science fiction video games",
    "Space opera video games",
    "Video games about alien invasions",
    "Video games about artificial intelligence",
    "Video games about bomb disposal",
    "Video games about curses",
    "Video games about demons",
    "Video games about dragons",
    "Video games about filicide",
    "Video games about fratricide",
    "Video games about hypnosis",
    "Video games about nuclear war and weapons",
    "Video games about parallel universes",
    "Video games about royalty",
    "Video games about science",
    "Video games about shapeshifting",
    "Video games about space warfare",
    "Video games about time loops",
    "Video games about time travel",
    "Video games about the afterlife",
    "Video games about witchcraft",
    "Video games about zombies",
    "Video games based on Greek mythology",
    # Media Francises
    "Avatar: The Last Airbender",
    # Tabletop Franchises
    "Magic: The Gathering",
    # Generic
    "Actresses from Pennsylvania",
    "Guinness World Records holders",
    "Male actors from Pennsylvania",
    "Musicians from Pennsylvania",
    "Musical groups from Pennsylvania",
)

# SQL LIKE patterns matching non-article or navigation titles to exclude.
EXCLUDED_TITLE_PATTERNS = ("%(disambiguation)",)

# Patterns matching placeholder or navigation content in Wikitext.
EXCLUDED_WIKITEXT_PATTERNS = (
    compile(
        r"\{\{\s*(?:[^}|]*-stub|disambiguation|disambig|dab|set index|sia)\s*(?:\||\}\})",
        IGNORECASE,
    ),
)

# Buffered rows committed to SQLite per transaction.
DATABASE_TRANSACTION_BATCH_SIZE = 1000

# Candidate article IDs dispatched per worker at once.
WORKER_CHUNK_SIZE = 500

# Minimum word count required for rendered plain text articles.
MINIMUM_PLAINTEXT_WORD_COUNT = 150

# Dynamic SQL clause for title exclusion.
TITLE_EXCLUSIONS_SQL = (
    " AND " + " AND ".join("title NOT LIKE ?" for _ in EXCLUDED_TITLE_PATTERNS)
    if EXCLUDED_TITLE_PATTERNS
    else ""
)

# SQLite statement for querying a single candidate article by ID.
SELECT_CANDIDATE_ARTICLE_SQL = f"""
    SELECT title, content
    FROM pages
    WHERE id = ? AND namespace = ?{TITLE_EXCLUSIONS_SQL}
"""

# SQLite table schema for filtered articles, categories, and relationships.
FILTERED_TABLE_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY,
        title TEXT,
        plain_text TEXT
    );

    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY,
        title TEXT
    );

    CREATE TABLE IF NOT EXISTS article_categories (
        article_id INTEGER,
        category_id INTEGER
    );
"""

# SQLite statements for inserting buffered records.
INSERT_ARTICLE_SQL = "INSERT INTO articles VALUES (?, ?, ?)"
INSERT_CATEGORY_SQL = "INSERT INTO categories VALUES (?, ?)"
INSERT_ARTICLE_CATEGORY_SQL = "INSERT INTO article_categories VALUES (?, ?)"

# Persistent read-only database connection opened once per worker process.
WORKER_DATABASE_CONNECTION = None


def initialize_worker():
    """Opens a persistent read-only SQLite connection per worker process."""
    global WORKER_DATABASE_CONNECTION

    WORKER_DATABASE_CONNECTION = open_readonly_database(PAGES_DATABASE_FILEPATH)


def load_whitelisted_candidates():
    """Returns matched categories and an article-to-categories mapping."""
    if not CATEGORY_WHITELIST:
        return {}, {}

    placeholders = ", ".join("?" for _ in CATEGORY_WHITELIST)

    with open_readonly_database(CATEGORIES_DATABASE_FILEPATH) as database_connection:
        cursor = database_connection.execute(
            f"""
            SELECT categories.id, categories.title, article_categories.article_id
            FROM categories
            JOIN article_categories ON article_categories.category_id = categories.id
            WHERE categories.title IN ({placeholders})
            """,
            CATEGORY_WHITELIST,
        )

        matched_categories = {}
        article_to_categories = {}

        for category_id, category_title, article_id in cursor:
            matched_categories[category_id] = category_title

            article_to_categories.setdefault(article_id, []).append(category_id)

    return matched_categories, article_to_categories


def process_article(article_id):
    """Queries and validates a single candidate article, returning (id, title, plain_text)."""
    row = WORKER_DATABASE_CONNECTION.execute(
        SELECT_CANDIDATE_ARTICLE_SQL,
        (article_id, MediaWikiNamespace.MAIN, *EXCLUDED_TITLE_PATTERNS),
    ).fetchone()

    if row is None:
        return None

    title, raw_wikitext = row

    if any(pattern.search(raw_wikitext) for pattern in EXCLUDED_WIKITEXT_PATTERNS):
        return None

    plain_text = render_wikitext_to_plaintext(raw_wikitext)

    if len(plain_text.split()) < MINIMUM_PLAINTEXT_WORD_COUNT:
        return None

    return (article_id, title, plain_text)


def execute_filter_pipeline():
    """Coordinates candidate lookup, parallel article filtering, and SQLite batch writes."""
    database_connection = initialize_bulk_write_database(
        FILTERED_DATABASE_FILEPATH,
        FILTERED_TABLE_SCHEMA_SQL,
        page_size=SQLITE_PAGE_SIZE_BYTES,
    )

    print("Loading candidate articles from categories database...")
    matched_categories, article_to_categories = load_whitelisted_candidates()

    print(
        f"Matched {len(matched_categories):,} whitelisted categories "
        f"covering {len(article_to_categories):,} unique candidate articles."
    )

    article_batch = []
    link_batch = []
    used_category_ids = set()
    total_persisted_articles = 0

    with Pool(initializer=initialize_worker) as worker_pool:
        processed_articles = worker_pool.imap_unordered(
            process_article,
            sorted(article_to_categories),
            chunksize=WORKER_CHUNK_SIZE,
        )

        for record in processed_articles:
            if record is None:
                continue

            article_id = record[0]
            article_batch.append(record)

            for category_id in article_to_categories[article_id]:
                link_batch.append((article_id, category_id))
                used_category_ids.add(category_id)

            if len(article_batch) >= DATABASE_TRANSACTION_BATCH_SIZE:
                total_persisted_articles += len(article_batch)

                flush_batch_to_database(
                    database_connection, INSERT_ARTICLE_SQL, article_batch
                )

                flush_batch_to_database(
                    database_connection, INSERT_ARTICLE_CATEGORY_SQL, link_batch
                )

                print(f"Persisted {total_persisted_articles:,} filtered articles...")

    if article_batch:
        total_persisted_articles += len(article_batch)

        flush_batch_to_database(database_connection, INSERT_ARTICLE_SQL, article_batch)
        flush_batch_to_database(
            database_connection, INSERT_ARTICLE_CATEGORY_SQL, link_batch
        )

    surviving_categories = [
        (category_id, title)
        for category_id, title in matched_categories.items()
        if category_id in used_category_ids
    ]

    print(f"Persisting {len(surviving_categories):,} active categories...")
    database_connection.executemany(INSERT_CATEGORY_SQL, surviving_categories)
    database_connection.commit()

    print("Building indexes on filtered database...")
    database_connection.executescript("""
        CREATE INDEX IF NOT EXISTS idx_articles_title
        ON articles(title);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_title
        ON categories(title);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_article_categories_article_category
        ON article_categories(article_id, category_id);

        CREATE INDEX IF NOT EXISTS idx_article_categories_category_id
        ON article_categories(category_id);
    """)

    database_connection.close()
    print(
        f"Done. Total filtered articles persisted: {total_persisted_articles:,} "
        f"across {len(surviving_categories):,} categories."
    )


if __name__ == "__main__":
    execute_filter_pipeline()
