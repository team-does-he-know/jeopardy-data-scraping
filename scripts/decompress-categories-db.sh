#!/usr/bin/env bash
cd "$(dirname "$0")/.."

DATABASE_FILEPATH="assets/enwiki-20220501-pages-articles-multistream.categories.db.zst"

zstd --decompress --threads=0 --keep "$DATABASE_FILEPATH"