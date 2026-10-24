#!/usr/bin/env bash
cd "$(dirname "$0")/.."

DATABASE_FILEGLOB="assets/enwiki-20220501-pages-articles-multistream.pages.db.part_*.zst"

zstd --decompress --threads=0 --keep $DATABASE_FILEGLOB