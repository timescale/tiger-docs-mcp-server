import argparse
from dataclasses import dataclass
from dotenv import load_dotenv
from bs4 import BeautifulSoup, element as BeautifulSoupElement
import json
from markdownify import markdownify
import openai
import os
from pathlib import Path
import psycopg
from psycopg.sql import SQL, Identifier
import re
import shutil
import subprocess
import tiktoken


THIS_DIR = Path(__file__).parent.resolve()

load_dotenv(dotenv_path=os.path.join(THIS_DIR, "..", ".env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

POSTGRES_DIR = THIS_DIR / "postgres"
SMGL_DIR = POSTGRES_DIR / "doc" / "src" / "sgml"
HTML_DIR = SMGL_DIR / "html"
BUILD_DIR = THIS_DIR / "build"
BUILD_DIR.mkdir(exist_ok=True)
MD_DIR = BUILD_DIR / "md"

POSTGRES_BASE_URL = "https://www.postgresql.org/docs"

ENC = tiktoken.get_encoding("cl100k_base")
MAX_CHUNK_TOKENS = 7000


def update_repo():
    if not POSTGRES_DIR.exists():
        subprocess.run(
            "git clone https://github.com/postgres/postgres.git postgres",
            shell=True,
            check=True,
            env=os.environ,
            text=True,
        )
    else:
        subprocess.run(
            "git fetch",
            shell=True,
            check=True,
            env=os.environ,
            text=True,
            cwd=POSTGRES_DIR,
        )


def get_version_tag(version: int) -> str:
    result = subprocess.run(
        ["git", "tag", "-l"], capture_output=True, text=True, cwd=POSTGRES_DIR
    )
    if result.returncode != 0:
        raise RuntimeError("Failed to get git tags")

    tags = result.stdout.splitlines()

    candidate_tags = []

    for version_type in ["", "RC", "BETA"]:
        pattern = re.compile(rf"REL_{version}_{version_type}(\d+)$")
        for tag in tags:
            match = pattern.match(tag)
            if match:
                minor_version = int(match.group(1))
                candidate_tags.append((minor_version, tag))
        if len(candidate_tags) > 0:
            break

    if not candidate_tags:
        raise ValueError(f"No tags found for Postgres version {version}")

    candidate_tags.sort(key=lambda x: x[0], reverse=True)
    return candidate_tags[0][1]


def checkout_tag(tag: str) -> None:
    print(f"checking out {tag}...")
    subprocess.run(
        f"git checkout {tag}",
        shell=True,
        check=True,
        env=os.environ,
        text=True,
        cwd=POSTGRES_DIR,
    )


def build_html() -> None:
    html_stamp = SMGL_DIR / "html-stamp"

    # make uses the presence of html-stamp to determine if it needs to
    # rebuild the html docs.
    if html_stamp.exists():
        html_stamp.unlink()

    if HTML_DIR.exists():
        shutil.rmtree(HTML_DIR)

    print("configuring postgres build...")
    environ = os.environ.copy()
    # Shim for macOS and icu4c installed via homebrew, where it's not linked into
    # /usr/local by default.
    if Path("/opt/homebrew/opt/icu4c/lib/pkgconfig").exists():
        environ["PKG_CONFIG_PATH"] = "/opt/homebrew/opt/icu4c/lib/pkgconfig"
    subprocess.run(
        "./configure --without-readline --without-zlib",
        shell=True,
        check=True,
        env=environ,
        text=True,
        cwd=POSTGRES_DIR,
    )

    print("building postgres docs...")
    subprocess.run(
        "make html",
        shell=True,
        check=True,
        env=os.environ,
        text=True,
        cwd=SMGL_DIR,
    )


def build_markdown() -> None:
    print("converting to markdown...")
    if MD_DIR.exists():
        shutil.rmtree(MD_DIR)
    MD_DIR.mkdir()

    for html_file in HTML_DIR.glob("*.html"):
        # Skip files which are more metadata about the docs than actual docs
        # that people would ask questions about.
        if html_file.name in [
            "legalnotice.html",
            "appendix-obsolete.md",
            "appendixes.md",
            "biblio.html",
            "bookindex.html",
            "bug-reporting.html",
            "source-format.html",
            "error-message-reporting.html",
            "error-style-guide.html",
            "source-conventions.html",
            "sourcerepo.html",
        ] or html_file.name.startswith("docguide"):
            continue
        md_file = MD_DIR / (html_file.stem + ".md")

        html_content = html_file.read_text(encoding="utf-8")
        html_content = html_content.replace(
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>', ""
        )

        soup = BeautifulSoup(html_content, "html.parser")

        is_refentry = bool(soup.find("div", class_="refentry"))

        elem = soup.find("div", attrs={"id": True})
        if elem and isinstance(elem, BeautifulSoupElement.Tag):
            slug = str(elem["id"]).lower() + ".html"
        else:
            raise SystemError(f"No div with id found in {html_file}")

        title = soup.find("title")
        title_text = (
            str(title.string).strip()
            if title and isinstance(title, BeautifulSoupElement.Tag)
            else "PostgreSQL Documentation"
        )
        if title:
            title.decompose()
        for class_name in ["navheader", "navfooter"]:
            for div in soup.find_all("div", class_=class_name):
                div.decompose()

        # Don't bother including refentry in the transform as we don't chunk
        # them by headers anyway.
        if not is_refentry:
            # Convert h3 headings in admonitions to h4 so that we avoid
            # chunking them.
            for class_name in [
                "caution",
                "important",
                "notice",
                "warning",
                "tip",
                "note",
            ]:
                for div in soup.find_all("div", class_=class_name):
                    if div is None or not isinstance(div, BeautifulSoupElement.Tag):
                        continue
                    h3 = div.find("h3")
                    if h3 and isinstance(h3, BeautifulSoupElement.Tag):
                        h3.name = "h4"

        md_content = markdownify(str(soup), heading_style="ATX")
        md_content = f"""---
title: {title_text}
slug: {slug}
refentry: {is_refentry}
---
{md_content}"""
        md_file.write_text(md_content, encoding="utf-8")


@dataclass
class Page:
    id: int
    version: int
    url: str
    domain: str
    filename: str


@dataclass
class Chunk:
    idx: int
    header: str
    header_path: list[str]
    content: str
    token_count: int = 0
    subindex: int = 0


def insert_page(
    conn: psycopg.Connection,
    page: Page,
) -> None:
    print("inserting page", page.filename, page.url)
    result = conn.execute(
        "insert into docs.postgres_pages_tmp (version, url, domain, filename, content_length, chunks_count) values (%s,%s,%s,%s,%s,%s) RETURNING id",
        [
            page.version,
            page.url,
            page.domain,
            page.filename,
            0,
            0,
        ],
    )
    row = result.fetchone()
    assert row is not None
    page.id = row[0]


def update_page_stats(
    conn: psycopg.Connection,
    page: Page,
) -> None:
    conn.execute(
        """
        update docs.postgres_pages_tmp p
        set
            content_length = coalesce(chunks_stats.total_length, 0),
            chunks_count = coalesce(chunks_stats.chunks_count, 0)
        from (
            select
                page_id,
                sum(char_length(content)) as total_length,
                count(*) as chunks_count
            from docs.postgres_chunks_tmp
            where page_id = %s
            group by page_id
        ) as chunks_stats
        where p.id = chunks_stats.page_id and p.id = %s
    """,
        [page.id, page.id],
    )


def insert_chunk(
    conn: psycopg.Connection,
    page: Page,
    chunk: Chunk,
) -> None:
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    content = ""
    for i in range(len(chunk.header_path)):
        content += (
            "".join(["#" for _ in range(i + 1)]) + " " + chunk.header_path[i] + "\n\n"
        )
    content += chunk.content
    embedding = (
        client.embeddings.create(
            model="text-embedding-3-small",
            input=chunk.content,
        )
        .data[0]
        .embedding
    )
    content = chunk.content
    # token_count, embedding = embed(header_path, content)
    print(f"header: {chunk.header}")
    url = page.url
    if len(chunk.header_path) > 1:
        pattern = r"\((#\S+)\)"
        match = re.search(pattern, chunk.header_path[-1])
        if match:
            url += match.group(1).lower()
    conn.execute(
        "insert into docs.postgres_chunks_tmp (page_id, chunk_index, sub_chunk_index, content, metadata, embedding) values (%s,%s,%s,%s,%s,%s)",
        [
            page.id,
            chunk.idx,
            chunk.subindex,
            chunk.content,
            json.dumps(
                {
                    "header": chunk.header,
                    "header_path": chunk.header_path,
                    "source_url": url,
                    "token_count": chunk.token_count,
                }
            ),
            embedding,
        ],
    )


def split_chunk(chunk: Chunk) -> list[Chunk]:
    num_subchunks = (chunk.token_count // MAX_CHUNK_TOKENS) + 1
    input_ids = ENC.encode(chunk.content)

    tokens_per_chunk = len(input_ids) // num_subchunks

    subchunks = []
    subindex = 0
    idx = 0
    while idx < len(input_ids):
        cur_idx = min(idx + tokens_per_chunk, len(input_ids))
        chunk_ids = input_ids[idx:cur_idx]
        if not chunk_ids:
            break
        decoded = ENC.decode(chunk_ids)
        if decoded:
            subchunks.append(
                Chunk(
                    idx=chunk.idx,
                    header=chunk.header,
                    header_path=chunk.header_path,
                    content=decoded,
                    token_count=len(chunk_ids),
                    subindex=subindex,
                )
            )
            subindex += 1
        if cur_idx == len(input_ids):
            break
        idx += tokens_per_chunk
    return subchunks


def process_chunk(conn: psycopg.Connection, page: Page, chunk: Chunk) -> None:
    if chunk.content == "":  # discard empty chunks
        return

    chunk.token_count = len(ENC.encode(chunk.content))
    if chunk.token_count < 10:  # discard chunks that are too tiny to be useful
        return

    chunks = [chunk]

    if chunk.token_count > MAX_CHUNK_TOKENS:
        print(
            f"Chunk {chunk.header} too large ({chunk.token_count} tokens), splitting..."
        )
        chunks = split_chunk(chunk)

    for chunk in chunks:
        insert_chunk(conn, page, chunk)
    conn.commit()


def chunk_files(conn: psycopg.Connection, version: int) -> None:
    conn.execute("drop table if exists docs.postgres_chunks_tmp")
    conn.execute("drop table if exists docs.postgres_pages_tmp")
    conn.execute(
        "create table docs.postgres_pages_tmp (like docs.postgres_pages including all excluding constraints)"
    )
    conn.execute(
        "insert into docs.postgres_pages_tmp select * from docs.postgres_pages where version != %s",
        [version],
    )
    conn.execute(
        "create table docs.postgres_chunks_tmp (like docs.postgres_chunks including all excluding constraints)"
    )
    conn.execute(
        "insert into docs.postgres_chunks_tmp select c.* from docs.postgres_chunks c inner join docs.postgres_pages p on c.page_id = p.id where p.version != %s",
        [version],
    )
    conn.execute(
        "alter table docs.postgres_chunks_tmp add foreign key (page_id) references docs.postgres_pages_tmp(id) on delete cascade"
    )
    conn.commit()

    # Reset the sequences for the temp tables
    conn.execute(
        "select setval(pg_get_serial_sequence('docs.postgres_chunks_tmp', 'id'), (select max(id) from docs.postgres_chunks_tmp))"
    )
    conn.execute(
        "select setval(pg_get_serial_sequence('docs.postgres_pages_tmp', 'id'), (select max(id) from docs.postgres_pages_tmp))"
    )
    conn.commit()

    header_pattern = re.compile("^(#{1,3}) .+$")
    codeblock_pattern = re.compile("^```")

    section_prefix = r"^[A-Za-z0-9.]+\.\s*"
    chapter_prefix = r"^Chapter\s+[0-9]+\.\s*"

    page_count = 0

    for md in MD_DIR.glob("*.md"):
        print(f"chunking {md}...")
        with md.open() as f:
            # process the frontmatter
            f.readline()
            f.readline()  # title line
            slug = f.readline().split(":", 1)[1].strip()
            refentry = f.readline().split(":", 1)[1].strip().lower() == "true"
            f.readline()

            page = Page(
                id=0,
                version=version,
                url=f"{POSTGRES_BASE_URL}/{version}/{slug}",
                domain="postgresql.org",
                filename=md.name,
            )
            page_count += 1

            insert_page(conn, page)

            header_path = []
            idx = 0
            chunk: Chunk | None = None
            in_codeblock = False
            while True:
                line = f.readline()
                if line == "":
                    if chunk is not None:
                        process_chunk(conn, page, chunk)
                    break
                match = header_pattern.match(line)
                if match is None or in_codeblock or (refentry and chunk is not None):
                    assert chunk is not None
                    if codeblock_pattern.match(line):
                        in_codeblock = not in_codeblock
                    chunk.content += line
                    continue
                header_hases = match.group(1)
                depth = len(header_hases)
                header_path = header_path[: (depth - 1)]
                header = line.lstrip("#").strip()
                header = re.sub(section_prefix, "", header).strip()
                header = re.sub(chapter_prefix, "", header).strip()
                header_path.append(header)
                if chunk is not None:
                    process_chunk(conn, page, chunk)
                chunk = Chunk(
                    idx=idx,
                    header=header,
                    header_path=header_path.copy(),
                    content="",
                )
                idx += 1
            update_page_stats(conn, page)
            conn.commit()

    with conn.cursor() as cur:
        cur.execute("drop table docs.postgres_chunks")
        cur.execute("drop table docs.postgres_pages")
        cur.execute("alter table docs.postgres_chunks_tmp rename to postgres_chunks")
        cur.execute("alter table docs.postgres_pages_tmp rename to postgres_pages")

        # the auto create foreign key and index names include the _tmp_ bit in their
        # names, so we remove them so that they match the generated names for the
        # renamed tables.
        for table in ["postgres_pages", "postgres_chunks"]:
            cur.execute(
                """
                select indexname
                from pg_indexes
                where schemaname = 'docs'
                and tablename = %s
                and indexname like %s
            """,
                [table, '%_tmp_%'],
            )
            for row in cur.fetchall():
                old_index_name = row[0]
                new_index_name = old_index_name.replace("_tmp_", "_")
                cur.execute(
                    SQL(
                        "alter index docs.{old_index_name} rename to {new_index_name}"
                    ).format(
                        old_index_name=Identifier(old_index_name),
                        new_index_name=Identifier(new_index_name),
                    )
                )

        cur.execute("""
            select conname
            from pg_constraint
            where conrelid = to_regclass(%s)
            and contype = 'f'
            and conname like %s
        """, ['docs.postgres_chunks', '%_tmp_%'])
        for row in cur.fetchall():
            old_fk_name = row[0]
            new_fk_name = old_fk_name.replace("_tmp_", "_")
            cur.execute(
                SQL(
                    "alter table docs.postgres_chunks rename constraint {old_fk_name} to {new_fk_name}"
                ).format(
                    old_fk_name=Identifier(old_fk_name),
                    new_fk_name=Identifier(new_fk_name),
                )
            )

    conn.commit()

    print(f"Processed {page_count} pages.")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Postgres documentation into the database."
    )
    parser.add_argument("version", type=int, help="Postgres version to ingest")
    args = parser.parse_args()
    version = args.version
    update_repo()
    tag = get_version_tag(version)
    db_uri = f"postgresql://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    with psycopg.connect(db_uri) as conn:
        print(f"Building Postgres {version} ({tag}) documentation...")
        checkout_tag(tag)
        build_html()
        build_markdown()
        chunk_files(conn, version)


if __name__ == "__main__":
    main()
