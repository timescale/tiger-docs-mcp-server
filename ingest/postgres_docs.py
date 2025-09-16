from dataclasses import dataclass
from dotenv import load_dotenv
from bs4 import BeautifulSoup, element as BeautifulSoupElement
from markdownify import markdownify
import openai
import os
from pathlib import Path
import psycopg
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

ENC = tiktoken.get_encoding("o200k_base")

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


def build_html(version: int, tag: str) -> None:
    html_stamp = SMGL_DIR / "html-stamp"

    # make uses the presence of html-stamp to determine if it needs to
    # rebuild the html docs.
    if html_stamp.exists():
        html_stamp.unlink()

    if HTML_DIR.exists():
        shutil.rmtree(HTML_DIR)

    print(f"checking out version {version} at {tag}...")
    subprocess.run(
        f"git checkout {tag}",
        shell=True,
        check=True,
        env=os.environ,
        text=True,
        cwd=POSTGRES_DIR,
    )

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

        # Convert first h3 to h4 in notice/warning/tip divs
        if not is_refentry:
            for class_name in ["caution", "important", "notice", "warning", "tip", "note"]:
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
class Chunk:
    header: str
    header_path: list[str]
    content: str
    slug: str
    version: int
    token_count: int = 0

def insert_chunk(
    conn: psycopg.Connection,
    chunk: Chunk,
) -> None:
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    content = ''
    for i in range(len(chunk.header_path)):
        content += ''.join(['#' for _ in range(i + 1)]) + ' ' + chunk.header_path[i] + '\n\n'
    content += chunk.content
    embedding = client.embeddings.create(
        model="text-embedding-3-small",
        input=chunk.content,
    ).data[0].embedding
    content = chunk.content
    # token_count, embedding = embed(header_path, content)
    print(f"header: {chunk.header}")
    conn.execute(
        "insert into docs.postgres_2 (version, header, header_path, source_url, content, token_count, embedding) values (%s,%s,%s,%s,%s,%s,%s)",
        [
            chunk.version,
            chunk.header,
            chunk.header_path,
            f"{POSTGRES_BASE_URL}/{chunk.version}/{chunk.slug}",
            content,
            0,
            embedding,
        ],
    )
    conn.commit()


def process_chunk(conn: psycopg.Connection, chunk: Chunk) -> None:
    if chunk.content == "":  # discard empty chunks
        return

    chunk.token_count = len(ENC.encode(chunk.content))
    if chunk.token_count < 10:  # discard chunks that are too tiny to be useful
        return

    chunks = [chunk]

    if chunk.token_count > 7000:
        print(f"chunk {chunk.header} too large ({chunk.token_count} tokens), skipping...")
        return
        # chunks = chunk_by_term(chunk)

    for chunk in chunks:
        insert_chunk(conn, chunk)


def chunk_files(conn: psycopg.Connection, version: int) -> None:
    conn.execute("delete from docs.postgres_2 where version = %s", [version])

    header_pattern = re.compile(
        "^(#{1,3}) .+$"
    )  # find lines that are markdown headers with 1-3 #
    codeblock_pattern = re.compile("^```")
    for md in MD_DIR.glob("*.md"):
        print(f"chunking {md}...")
        with md.open() as f:
            # process the frontmatter
            f.readline()
            title_line = f.readline()
            slug = f.readline().split(":", 1)[1].strip()
            refentry = f.readline().split(":", 1)[1].strip().lower() == "true"
            f.readline()
            header_path = []
            chunk: Chunk | None = None
            in_codeblock = False
            while True:
                line = f.readline()
                if line == "":
                    if chunk is not None:
                        process_chunk(conn, chunk)
                    break
                match = header_pattern.match(line)
                if match is None or in_codeblock or (refentry and chunk is not None):
                    assert chunk is not None
                    if codeblock_pattern.match(line):
                        in_codeblock = not in_codeblock
                    chunk.content += line
                    continue
                header = match.group(1)
                depth = len(header)
                header_path = header_path[: (depth - 1)]
                header_path.append(line.lstrip("#").strip())
                if chunk is not None:
                    process_chunk(conn, chunk)
                chunk = Chunk(
                    header=line.lstrip("#").strip(),
                    header_path=header_path.copy(),
                    content="",
                    slug=slug,
                    version=version,
                )


if __name__ == "__main__":
    update_repo()
    postgres_versions = [
        (17, "REL_17_6"),
        # (16, "REL_16_9"),
        # (15, "REL_15_13"),
        # (14, "REL_14_18")
    ]
    db_uri = f"postgresql://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    with psycopg.connect(db_uri) as conn:
        for version, tag in postgres_versions:
            print(f"Building Postgres {version} documentation...")
            # build_html(version, tag)
            build_markdown()
            chunk_files(conn, version)
