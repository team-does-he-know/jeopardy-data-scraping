#!/usr/bin/env bash
cd "$(dirname "$0")/.."

DATABASE_FILEGLOB="assets/enwiki-20220501-pages-articles-multistream.pages.db.part_*"

rm --force $DATABASE_FILEGLOB