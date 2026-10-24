from urllib.request import Request, urlopen

from blake3 import blake3
from parfive import Downloader

from .path import ASSETS_DIRECTORY_PATH

HASH_READ_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def download_asset(*file_targets):
    """Downloads (url, blake3_hash) tuples into the assets directory if missing or corrupt."""
    downloader = Downloader(overwrite=True)

    pending_verification = []

    for url, expected_hash in file_targets:
        filename = url.rsplit("/", 1)[-1]
        filepath = ASSETS_DIRECTORY_PATH / filename

        if not file_matches_hash(filepath, expected_hash):
            resolved_url = resolve_url(url)

            downloader.enqueue_file(
                resolved_url, path=ASSETS_DIRECTORY_PATH, filename=filename
            )

            pending_verification.append((filepath, expected_hash))

    if pending_verification:
        downloader.download()

        for filepath, expected_hash in pending_verification:
            if not file_matches_hash(filepath, expected_hash):
                filepath.unlink(missing_ok=True)

                raise RuntimeError(
                    f"Hash verification failed for {filepath.name} after download."
                )


def file_matches_hash(filepath, expected_hash):
    """Returns True if the file exists and its BLAKE3 hash matches expected_hash."""
    if not filepath.is_file():
        return False

    file_hasher = blake3()

    with filepath.open("rb") as file:
        while chunk := file.read(HASH_READ_CHUNK_SIZE):
            file_hasher.update(chunk)

    return file_hasher.hexdigest().lower() == expected_hash.lower()


def resolve_url(url):
    """Returns the resolved URL based on the server's response."""
    request = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        method="HEAD",
    )

    try:
        with urlopen(request) as response:
            return response.url

    except Exception:
        return url
