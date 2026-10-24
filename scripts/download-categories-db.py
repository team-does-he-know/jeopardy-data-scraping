#!/usr/bin/env python3
from jeopardy_data_scraping import download_asset

download_asset(
    (
        "https://github.com/team-does-he-know/jeopardy-data-scraping/releases/download/categories-db-20220501-zst/enwiki-20220501-pages-articles-multistream.categories.db.zst",
        "02c1fc1d11c3b4aa820d0696028e0f66f48a57c9ab394427acc0a5284fdc94d6",
    ),
)
