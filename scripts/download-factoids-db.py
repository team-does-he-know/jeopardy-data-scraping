#!/usr/bin/env python3
from jeopardy_data_scraping import download_asset

download_asset(
    (
        "https://github.com/team-does-he-know/jeopardy-data-scraping/releases/download/factoids-db-2026-10-28/enwiki-20220501-pages-articles-multistream.factoids.db",
        "1aa91fbeb917cbd7aecea3897fbeb1ad08cab417241fb178f77e7d3315176533",
    ),
)
