#!/usr/bin/env python3
from jeopardy_data_scraping import download_asset

download_asset(
    (
        "https://github.com/team-does-he-know/jeopardy-data-scraping/releases/download/filtered-pages-db-2022-05-01/enwiki-20220501-pages-articles-multistream.filtered.db",
        "5868f0a5affdcddb98112683c9103c6ec1aa9ec5a266cb7a32570cabf48da78c",
    ),
)
