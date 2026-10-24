#!/usr/bin/env bash
cd "$(dirname "$0")/.."

DATABASE_FILEPATH="assets/enwiki-20220501-pages-articles-multistream.pages.db"

split --bytes=5GB --numeric-suffixes --suffix-length=3 "$DATABASE_FILEPATH" "${DATABASE_FILEPATH}.part_"