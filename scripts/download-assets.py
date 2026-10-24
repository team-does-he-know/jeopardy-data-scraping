#!/usr/bin/env python3
from os.path import basename, exists, join
from urllib.parse import urlparse

from blake3 import blake3
from parfive import Downloader

ASSETS_DIRECTORY_PATH = "assets"

HASH_READ_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def is_valid_file(filepath, expected_hash):
    """Returns True if the file exists and its BLAKE3 hash matches expected_hash."""
    if not exists(filepath):
        return False

    file_hasher = blake3()

    with open(filepath, "rb") as file:
        while chunk := file.read(HASH_READ_CHUNK_SIZE):
            file_hasher.update(chunk)

    return file_hasher.hexdigest().lower() == expected_hash.lower()


def download(*file_targets):
    """Downloads (url, blake3_hash) tuples into the assets directory if missing or corrupt."""
    downloader = Downloader(overwrite=True)

    for url, expected_hash in file_targets:
        filename = basename(urlparse(url).path)
        filepath = join(ASSETS_DIRECTORY_PATH, filename)

        if not is_valid_file(filepath, expected_hash):
            downloader.enqueue_file(url, path=ASSETS_DIRECTORY_PATH)

    downloader.download()


download(
    (
        "https://archive.org/download/enwiki-20220501/enwiki-20220501-pages-articles-multistream-index.txt.bz2",
        "5a097d42d6b95c9b78bc1865710e92ca8e0671f8ee074bb1f7969a93d762005d",
    ),
    (
        "https://archive.org/download/enwiki-20220501/enwiki-20220501-pages-articles-multistream.xml.bz2",
        "33ac11e855b9b5cae2a7be4fe289d34284e4ea0a51f130ed328872191417f37d",
    ),
)
