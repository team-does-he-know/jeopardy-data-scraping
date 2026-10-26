# jeopardy-data-scraping

> Scrapes Wikipedia English article database and creates a Jeopardy factoids dataset via LLMs.

## Prerequisites

- pip
- Python 3.12+
- zstd CLI

## Getting Started

The following steps must be run in order.

### 1. Dependency Installation

Install the Python dependencies via the terminal:

```
> pip3 install -e .
```

### 2. Wikipedia Database Dump

> **WARNING:** The database dumps are **LARGE**! See below:
>
> - `enwiki-20220501-pages-articles-multistream.xml.bz2` — ~20 GB
> - `enwiki-20220501-pages-articles-multistream-index.txt.bz2` — ~241 MB

A [May 2022 dump of Wikipedia from the Internet Archive](https://archive.org/details/enwiki-20220501) is used by this project for its initial data scraping. Download it via the terminal:

```
> python3 ./scripts/download-wikipedia-database-dump.py
```

## Running the Data Scraper

The following steps must be run in order.

### 1. Ingest Data Pass

> **WARNING:** This step will probably max out all of your CPU cores / system RAM / swap / disk access and lock up your computer.
>
> Yeah... this needs some better optimization / backpressure handling.

Convert the downloaded Wikipedia dump assets to an SQLite3 dataset asset via the terminal:

```
> python3 ./1-ingest-data-pass.py
```

### 2. Build Categories Pass

> **WARNING:** This step will probably max out your disk access and lock up your computer.

Extract page categories and create one-to-many bindings between pages and categories.

```
> python3 ./2-build-categories-pass.py
```

### 3. Build Vital Articles Pass

...

### 4. Filter Pages Pass

Filter the extracted datasets down to a smaller cleaned dataset ready for factoid generation.

```
> python3 ./4-filter-pages-pass.py
```

### 5. Generate Factoids Pass

> **IMPORTANT:** This pass was specifically tuned for the Mixture-of-Experts Gemma 4 26B A4B QAT model.

> **TIP:** `./scripts/load-gemma-4.sh` is a quick shortcut script to tell an LM Studio server to load the above model.

> **IMPORTANT:** Enable thinking with a reasoning token cap of 1024 tokens. This enables the LLM to generate better quality factoid pairs within a reasonable timeframe.

Pass filtered Wikipedia pages dataset into an LLM via an OpenAI API-compatible chat completions endpoint.

```
> python3 ./5-generate-factoids-pass.py
```

### 6. Classification Pass

...

## Download Generated SQLite3 Datasets

Any of the above data scraper passes can be skipped by using the precompiled SQLite3 datasets.

### 1. Download Ingested Data Dataset

> **WARNING:** The ingested pages dataset is **LARGE**! See below:
>
> - `enwiki-20220501-pages-articles-multistream.pages.db` — ~61.5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_000` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_001` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_002` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_003` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_004` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_005` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_006` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_007` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_008` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_009` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_010` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_011` — ~5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_012` — ~1.5 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_000.zst` — ~1 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_001.zst` — ~1.1 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_002.zst` — ~1.1 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_003.zst` — ~1.1 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_004.zst` — ~1 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_005.zst` — ~1 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_006.zst` — ~1 GB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_007.zst` — ~994 MB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_008.zst` — ~974 MB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_009.zst` — ~968 MB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_010.zst` — ~938 MB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_011.zst` — ~931 MB
> - `enwiki-20220501-pages-articles-multistream.pages.db.part_012.zst` — ~321 MB

Download the ingested data artifacts, decompress them, assemble them into the final dataset, and cleanup the downloaded artifacts.

```
> python3 ./scripts/download-pages-db.py
> ./scripts/decompress-pages-db.sh
> ./scripts/assemble-pages-db.sh
> ./scripts/cleanup-pages-db-artifacts.sh
```

### 2. Download Categories Dataset

> **WARNING:** The categories dataset is **LARGE**! See below:
>
> - `enwiki-20220501-pages-articles-multistream.categories.db` — ~1.7 GB
> - `enwiki-20220501-pages-articles-multistream.categories.db.zst` — ~521 MB

Download the categories artifact, decompress it, and cleanup the downloaded artifact.

```
> python3 ./scripts/download-categories-db.py
> ./scripts/decompress-categories-db.sh
> ./scripts/cleanup-categories-db-artifacts.sh
```

### 3. Download Vital Articles Dataset

...

### 4. Download Filtered Dataset

...

### 5. Download Factoids Dataset

...
