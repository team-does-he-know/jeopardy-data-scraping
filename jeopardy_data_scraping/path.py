from pathlib import Path

ASSETS_DIRECTORY_PATH = Path("assets")


PAGES_DATABASE_FILEPATH = (
    ASSETS_DIRECTORY_PATH / "enwiki-20220501-pages-articles-multistream.pages.db"
)

WIKIPEDIA_DUMP_FILEPATH = (
    ASSETS_DIRECTORY_PATH / "enwiki-20220501-pages-articles-multistream.xml.bz2"
)

WIKIPEDIA_INDEX_FILEPATH = (
    ASSETS_DIRECTORY_PATH / "enwiki-20220501-pages-articles-multistream-index.txt.bz2"
)
