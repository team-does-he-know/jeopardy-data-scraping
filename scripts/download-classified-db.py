#!/usr/bin/env python3
from jeopardy_data_scraping import download_asset

download_asset(
    (
        "https://github.com/team-does-he-know/jeopardy-data-scraping/releases/download/classified-factoids-db-2022-05-01/enwiki-20220501-pages-articles-multistream.classified.db",
        "e7fdd35cfe5c6e59d1849bcfebc7083b5a9ace2873fe50c9527bcc619d6735ac",
    ),
)
