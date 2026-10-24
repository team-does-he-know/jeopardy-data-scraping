#!/usr/bin/env bash
cd "$(dirname "$0")/.."

DATABASE_FILEPATH="assets/enwiki-20220501-pages-articles-multistream.categories.db.zst"

rm --force "$DATABASE_FILEPATH"