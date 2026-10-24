from os.path import join

ASSETS_DIRECTORY_PATH = "assets"


PAGES_DATABASE_FILEPATH = join(
    ASSETS_DIRECTORY_PATH, "enwiki-20220501-pages-articles-multistream.pages.db"
)

WIKIPEDIA_DUMP_FILEPATH = join(
    ASSETS_DIRECTORY_PATH, "enwiki-20220501-pages-articles-multistream.xml.bz2"
)

WIKIPEDIA_INDEX_FILEPATH = join(
    ASSETS_DIRECTORY_PATH, "enwiki-20220501-pages-articles-multistream-index.txt.bz2"
)
