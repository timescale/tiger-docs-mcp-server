# Ingest

## Setup

### Prerequisites

- [`uv`](https://docs.astral.sh/uv/)
- Docbook Toolsets for building PostgreSQL docs
  (see [this page](https://www.postgresql.org/docs/current/docguide-toolsets.html)
  for installing for specific platforms)

### Install Dependencies

```bash
uv sync
```

## Running the ingest

### PostgreSQL Documentation

```text
$ uv run python postgres_docs.py --help
usage: postgres_docs.py [-h] version

Ingest Postgres documentation into the database.

positional arguments:
  version     Postgres version to ingest

options:
  -h, --help  show this help message and exit
```

### Tiger Documentation

```text
uv run python tiger_docs.py --help
usage: tiger_docs.py [-h] [--domain DOMAIN] [-o OUTPUT_DIR] [-m MAX_PAGES] [--strip-images] [--no-strip-images] [--chunk] [--no-chunk] [--chunking {header,semantic}] [--storage-type {file,database}] [--database-uri DATABASE_URI]
                         [--skip-indexes] [--delay DELAY] [--concurrent CONCURRENT] [--log-level {DEBUG,INFO,WARNING,ERROR}] [--user-agent USER_AGENT]

Scrape websites using sitemaps and convert to chunked markdown for RAG applications

options:
  -h, --help            show this help message and exit
  --domain, -d DOMAIN   Domain to scrape (e.g., docs.tigerdata.com)
  -o, --output-dir OUTPUT_DIR
                        Output directory for scraped files (default: scraped_docs)
  -m, --max-pages MAX_PAGES
                        Maximum number of pages to scrape (default: unlimited)
  --strip-images        Strip data: images from content (default: True)
  --no-strip-images     Keep data: images in content
  --chunk               Enable content chunking (default: True)
  --no-chunk            Disable content chunking
  --chunking {header,semantic}
                        Chunking method: header (default) or semantic (requires OPENAI_API_KEY)
  --storage-type {file,database}
                        Storage type: database (default) or file
  --database-uri DATABASE_URI
                        PostgreSQL connection URI (default: uses DB_URL from environment)
  --skip-indexes        Skip creating database indexes after import (for development/testing)
  --delay DELAY         Download delay in seconds (default: 1.0)
  --concurrent CONCURRENT
                        Maximum concurrent requests (default: 4)
  --log-level {DEBUG,INFO,WARNING,ERROR}
                        Logging level (default: INFO)
  --user-agent USER_AGENT
                        User agent string

Examples:
  tiger_docs.py docs.tigerdata.com
  tiger_docs.py docs.tigerdata.com -o tiger_docs -m 50
  tiger_docs.py docs.tigerdata.com -o semantic_docs -m 5 --chunking semantic
  tiger_docs.py docs.tigerdata.com --no-chunk --no-strip-images -m 100
  tiger_docs.py docs.tigerdata.com --storage-type database --database-uri postgresql://user:pass@host:5432/dbname
  tiger_docs.py docs.tigerdata.com --storage-type database --chunking semantic -m 10
```
