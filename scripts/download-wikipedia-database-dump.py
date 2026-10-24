#!/usr/bin/env python3
from jeopardy_data_scraping import download_asset

download_asset(
    (
        "https://archive.org/download/enwiki-20220501/enwiki-20220501-pages-articles-multistream-index.txt.bz2",
        "5a097d42d6b95c9b78bc1865710e92ca8e0671f8ee074bb1f7969a93d762005d",
    ),
    (
        "https://archive.org/download/enwiki-20220501/enwiki-20220501-pages-articles-multistream.xml.bz2",
        "33ac11e855b9b5cae2a7be4fe289d34284e4ea0a51f130ed328872191417f37d",
    ),
)
