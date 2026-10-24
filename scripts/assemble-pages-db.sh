#!/usr/bin/env bash
cd "$(dirname "$0")/.."

DATABASE_FILEPATH="assets/enwiki-20220501-pages-articles-multistream.pages.db"

cat "${DATABASE_FILEPATH}.part_"* > "$DATABASE_FILEPATH"