# jeopardy-data-scraping

> Scrapes Wikipedia English article database and creates a Jeopardy factoids dataset via LLMs.

## Prerequisites

- pip
- Python 3.9+
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

...

### 5. Generate Factoids Pass

...

### 6. Classification Pass

...

## Download Generated SQLite3 Datasets

Any of the above data scraper passes can be skipped by using the precompiled SQLite3 datasets.

### 1. Download Ingested Data Dataset

...

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
