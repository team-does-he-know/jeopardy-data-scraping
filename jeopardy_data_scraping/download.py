from mmap import ACCESS_READ, mmap
from urllib.request import Request, urlopen

from blake3 import blake3
from parfive import Downloader

from jeopardy_data_scraping.path import ASSETS_DIRECTORY_PATH


def download_asset(*file_targets):
    """Downloads (url, blake3_hash) tuples into the assets directory if missing or corrupt."""
    downloader = Downloader(overwrite=True)

    pending_verification = []

    for url, expected_hash in file_targets:
        filename = url.rsplit("/", 1)[-1]
        filepath = ASSETS_DIRECTORY_PATH / filename

        print(f"Checking existing {filepath.name}...")

        if file_matches_hash(filepath, expected_hash):
            print(f"Passed check: {filepath.name}")

        else:
            print(f"Failed check: {filepath.name}")
            resolved_url = resolve_url(url)

            downloader.enqueue_file(
                resolved_url, path=ASSETS_DIRECTORY_PATH, filename=filename
            )

            pending_verification.append((filepath, expected_hash))

    if pending_verification:
        downloader.download()

        for filepath, expected_hash in pending_verification:
            print(f"Checking downloaded {filepath.name}...")

            if file_matches_hash(filepath, expected_hash):
                print(f"Passed check: {filepath.name}")

            else:
                print(f"Failed check: {filepath.name}")
                filepath.unlink(missing_ok=True)

                raise RuntimeError(
                    f"Hash verification failed for {filepath.name} after download."
                )


def file_matches_hash(filepath, expected_hash):
    """Returns True if the file exists and its BLAKE3 hash matches expected_hash."""
    if not filepath.is_file():
        return False

    file_hasher = blake3(max_threads=blake3.AUTO)

    with filepath.open("rb") as file:
        with mmap(file.fileno(), 0, access=ACCESS_READ) as mm:
            file_hasher.update(mm)

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
