from scrapy.spiders import SitemapSpider
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import os
import re
import sys
import argparse
import asyncio
import time
from urllib.parse import urlparse, urljoin
import hashlib
import requests
import json
import psycopg
from psycopg.sql import SQL, Identifier
import openai
import tomllib
from dotenv import load_dotenv, find_dotenv
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

script_dir = os.path.dirname(os.path.abspath(__file__))

if not os.path.exists(os.path.join(script_dir, 'build')):
    os.makedirs(os.path.join(script_dir, 'build'))

load_dotenv(dotenv_path=os.path.join(script_dir, '..', '.env'))
schema = 'docs'

with open(os.path.join(script_dir, 'tiger_docs_config.toml'), 'rb') as config_fp:
    config = tomllib.load(config_fp)
    DOMAIN_SELECTORS = config['domain_selectors']
    DEFAULT_SELECTORS = config['default_selectors']


def add_header_breadcrumbs_to_content(content, metadata):
    """Add header breadcrumbs to content - shared utility function"""
    breadcrumbs = []

    # Find the deepest header level present in metadata
    present_headers = []
    for level in ['Header 1', 'Header 2', 'Header 3']:
        if level in metadata:
            present_headers.append(level)

    # Add all headers except the last one (to avoid duplication with chunk content)
    for level in present_headers[:-1]:
        header_level = level.split()[-1]  # Get "1", "2", "3"
        header_prefix = '#' * int(header_level)
        breadcrumbs.append(f"{header_prefix} {metadata[level]}")

    # Combine breadcrumbs with chunk content
    if breadcrumbs:
        breadcrumb_text = '\n'.join(breadcrumbs) + '\n\n'
        return breadcrumb_text + content
    else:
        return content

class DatabaseManager:
    """Handles PostgreSQL database interactions for storing scraped content"""

    def __init__(self, database_uri, embedding_model=None):
        self.database_uri = database_uri
        self.embedding_model = embedding_model
        try:
            self.connection = psycopg.connect(self.database_uri)
        except Exception as e:
            raise RuntimeError(f"Database connection failed: {e}")

    def create_tmp_tables(self):
        with self.connection.cursor() as cursor:
            cursor.execute(SQL("DROP TABLE IF EXISTS {schema}.timescale_chunks_tmp").format(schema=Identifier(schema)))
            cursor.execute(SQL("DROP TABLE IF EXISTS {schema}.timescale_pages_tmp").format(schema=Identifier(schema)))
            cursor.execute(SQL("CREATE TABLE {schema}.timescale_pages_tmp (LIKE {schema}.timescale_pages INCLUDING ALL EXCLUDING CONSTRAINTS)").format(schema=Identifier(schema)))
            cursor.execute(SQL("CREATE TABLE {schema}.timescale_chunks_tmp (LIKE {schema}.timescale_chunks INCLUDING ALL EXCLUDING CONSTRAINTS)").format(schema=Identifier(schema)))
            cursor.execute(SQL("ALTER TABLE {schema}.timescale_chunks_tmp ADD FOREIGN KEY (page_id) REFERENCES {schema}.timescale_pages_tmp(id) ON DELETE CASCADE").format(schema=Identifier(schema)))
        self.connection.commit()

    def rename_objects(self):
        """Rename the temporary tables and their indexes to the final names, dropping the old tables if they exist"""
        with self.connection.cursor() as cursor:
            cursor.execute(SQL("DROP TABLE IF EXISTS {schema}.timescale_chunks").format(schema=Identifier(schema)))
            cursor.execute(SQL("DROP TABLE IF EXISTS {schema}.timescale_pages").format(schema=Identifier(schema)))
            cursor.execute(SQL("ALTER TABLE {schema}.timescale_chunks_tmp RENAME TO timescale_chunks").format(schema=Identifier(schema)))
            cursor.execute(SQL("ALTER TABLE {schema}.timescale_pages_tmp RENAME TO timescale_pages").format(schema=Identifier(schema)))

            # the auto create foreign key and index names include the _tmp_ bit in their
            # names, so we remove them so that they match the generated names for the
            # renamed tables.
            for table in ["timescale_pages", "timescale_chunks"]:
                cursor.execute(
                    """
                    select indexname
                    from pg_indexes
                    where schemaname = %s
                    and tablename = %s
                    and indexname like %s
                """,
                    [schema, table, '%_tmp_%'],
                )
                for row in cursor.fetchall():
                    old_index_name = row[0]
                    new_index_name = old_index_name.replace("_tmp_", "_")
                    cursor.execute(
                        SQL(
                            "alter index {schema}.{old_index_name} rename to {new_index_name}"
                        ).format(
                            schema=Identifier(schema),
                            old_index_name=Identifier(old_index_name),
                            new_index_name=Identifier(new_index_name),
                        )
                    )

            cursor.execute(
                SQL("""
                    select conname
                    from pg_constraint
                    where conrelid = to_regclass(%s)
                    and contype = 'f'
                    and conname like '%_tmp_%'
                """).format(schema=Identifier(schema)),
                [f"{schema}.timescale_chunks"],
            )
            for row in cursor.fetchall():
                old_fk_name = row[0]
                new_fk_name = old_fk_name.replace("_tmp_", "_")
                cursor.execute(
                    SQL(
                        "alter table {schema}.timescale_chunks rename constraint {old_fk_name} to {new_fk_name}"
                    ).format(
                        schema=Identifier(schema),
                        old_fk_name=Identifier(old_fk_name),
                        new_fk_name=Identifier(new_fk_name),
                    )
                )

        self.connection.commit()

    def save_page(self, url, domain, filename, content_length, chunking_method='header'):
        """Save page information and return the page ID"""
        try:
            with (
                self.connection.cursor() as cursor,
                self.connection.transaction() as _,
            ):
                cursor.execute(SQL("""
                    INSERT INTO {schema}.timescale_pages_tmp (url, domain, filename, content_length, chunking_method)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO UPDATE SET
                        content_length = EXCLUDED.content_length,
                        chunking_method = EXCLUDED.chunking_method,
                        scraped_at = CURRENT_TIMESTAMP
                    RETURNING id
                """).format(schema=Identifier(schema)), (url, domain, filename, content_length, chunking_method))

                page_id = cursor.fetchone()[0]

                # Delete existing chunks for this page (in case of re-scraping)
                cursor.execute(SQL("DELETE FROM {schema}.timescale_chunks WHERE page_id = %s").format(schema=Identifier(schema)), (page_id,))

                return page_id

        except Exception as e:
            raise RuntimeError(f"Failed to save page {url}: {e}")

    def generate_embeddings_batch(self, texts):
        """Generate embeddings for a batch of texts using the configured embedding model"""
        if self.embedding_model is None:
            return [None] * len(texts)

        try:
            # Clean texts for embedding
            clean_texts = []
            for text in texts:
                clean_text = text.strip() if text else ""
                clean_texts.append(clean_text)

            # Generate embeddings in batch using the model
            embeddings = self.embedding_model.get_text_embeddings(clean_texts)
            return embeddings

        except Exception as e:
            print(f"Warning: Failed to generate batch embeddings: {e}")
            return [None] * len(texts)

    def save_chunks(self, page_id, chunks):
        """Save chunks for a page with batch embedding generation"""
        try:
            # Prepare content with breadcrumbs for all chunks
            processed_chunks = []
            chunk_texts = []

            for chunk in chunks:
                content_with_breadcrumbs = add_header_breadcrumbs_to_content(
                    chunk['content'],
                    chunk['metadata']
                )
                processed_chunks.append({
                    'content': content_with_breadcrumbs,
                    'metadata': chunk['metadata']
                })
                chunk_texts.append(content_with_breadcrumbs)

            # Generate embeddings for all chunks in batch
            embeddings = self.generate_embeddings_batch(chunk_texts)

            with (
                self.connection.cursor() as cursor,
                self.connection.transaction() as _,
            ):
                for chunk, embedding in zip(processed_chunks, embeddings):
                    cursor.execute(SQL("""
                        INSERT INTO {schema}.timescale_chunks_tmp (page_id, chunk_index, sub_chunk_index, content, metadata, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """).format(schema=Identifier(schema)), (
                        page_id,
                        chunk['metadata'].get('chunk_index', 0),
                        chunk['metadata'].get('sub_chunk_index', 0),
                        chunk['content'],
                        json.dumps(chunk['metadata']),
                        embedding
                    ))

                # Update chunks count in pages table
                cursor.execute(SQL("""
                    UPDATE {schema}.timescale_pages_tmp
                    SET chunks_count = %s
                    WHERE id = %s
                """).format(schema=Identifier(schema)), (len(chunks), page_id))

        except Exception as e:
            raise RuntimeError(f"Failed to save chunks for page {page_id}: {e}")

    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()

class FileManager:
    """Handles file-based storage for scraped content"""

    def __init__(self, output_dir='scraped_docs'):
        self.output_dir = output_dir
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)

    def save_chunked_content(self, url, filename, chunks):
        """Save chunked content to a markdown file with delimiters"""
        filepath = os.path.join(self.output_dir, filename)

        # Create markdown with chunk delimiters
        chunked_markdown = f"# Source: {url}\n\n"
        chunked_markdown += f"<!-- Total Chunks: {len(chunks)} -->\n\n"

        for i, chunk in enumerate(chunks):
            # Add chunk delimiter
            chunked_markdown += f"---\n<!-- CHUNK {i+1}/{len(chunks)} -->\n"

            # Add metadata as comments
            if chunk['metadata']:
                chunked_markdown += f"<!-- Metadata: {chunk['metadata']} -->\n"

            chunked_markdown += "---\n\n"

            # Add header breadcrumbs and content
            content_with_breadcrumbs = add_header_breadcrumbs_to_content(
                chunk['content'],
                chunk['metadata']
            )
            chunked_markdown += content_with_breadcrumbs
            chunked_markdown += "\n\n"

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(chunked_markdown)

        return filepath

    def save_regular_content(self, url, filename, content):
        """Save regular markdown content to a file"""
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Source: {url}\n\n")
            f.write(content)

        return filepath

class SitemapMarkdownSpider(SitemapSpider):
    name = 'sitemap_markdown'

    def __init__(self, domain=None, output_dir='scraped_docs', max_pages=None, strip_data_images=True, chunk_content=True, chunking_method='header', db_manager=None, file_manager=None, *args, **kwargs):
        super(SitemapMarkdownSpider, self).__init__(*args, **kwargs)

        if not domain:
            raise ValueError("domain parameter is required")

        self.domain = domain
        self.output_dir = output_dir
        self.max_pages = int(max_pages) if max_pages else None
        self.should_strip_data_images = strip_data_images if isinstance(strip_data_images, bool) else strip_data_images.lower() == 'true'
        self.should_chunk_content = chunk_content if isinstance(chunk_content, bool) else chunk_content.lower() == 'true'
        self.chunking_method = chunking_method  # 'header' or 'semantic'
        self.allowed_domains = [domain]

        # Use passed-in storage managers
        self.db_manager = db_manager
        self.file_manager = file_manager

        # Get sitemap URLs from robots.txt or fallback to default
        self.sitemap_urls = self.get_sitemap_urls(domain)

        # Track processed URLs to avoid duplicates
        self.processed_urls = set()
        # Track number of pages processed
        self.pages_processed = 0

        # Configure domain-specific element removal
        self.ignore_selectors = self.get_ignore_selectors(domain)

    def _init_default_embedding_model(self):
        """Initialize OpenAI embedding model for database storage"""
        try:
            if not os.getenv('OPENAI_API_KEY'):
                raise ValueError("OPENAI_API_KEY environment variable is required for database storage with embeddings")

            self.logger.info("Initializing OpenAI embedding client")
            client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

            # Create a simple wrapper class for the OpenAI client
            class OpenAIEmbeddingWrapper:
                def __init__(self, client):
                    self.client = client
                    self.model = "text-embedding-3-small"

                def get_text_embeddings(self, texts):
                    """Generate embeddings for a batch of texts"""
                    response = self.client.embeddings.create(
                        input=texts,
                        model=self.model
                    )
                    return [embedding.embedding for embedding in response.data]

            return OpenAIEmbeddingWrapper(client)

        except Exception as e:
            raise RuntimeError(f"Failed to initialize OpenAI embeddings: {e}")

    def get_sitemap_urls(self, domain):
        """Get sitemap URLs from robots.txt, fallback to common locations"""
        sitemap_urls = []

        # Try to get sitemaps from robots.txt
        robots_url = f'https://{domain}/robots.txt'
        try:
            self.logger.info(f'Checking robots.txt at: {robots_url}')
            response = requests.get(robots_url, timeout=10)
            response.raise_for_status()

            # Parse robots.txt for sitemap entries
            for line in response.text.split('\n'):
                line = line.strip()
                if line.lower().startswith('sitemap:'):
                    sitemap_url = line.split(':', 1)[1].strip()
                    # Handle relative URLs
                    if not sitemap_url.startswith('http'):
                        sitemap_url = urljoin(f'https://{domain}/', sitemap_url)
                    sitemap_urls.append(sitemap_url)
                    self.logger.info(f'Found sitemap in robots.txt: {sitemap_url}')

        except Exception as e:
            self.logger.warning(f'Could not fetch robots.txt from {robots_url}: {e}')

        # If no sitemaps found in robots.txt, try common locations
        if not sitemap_urls:
            common_sitemap_locations = [
                f'https://{domain}/sitemap.xml',
                f'https://{domain}/sitemap_index.xml',
                f'https://{domain}/sitemap.txt'
            ]

            for sitemap_url in common_sitemap_locations:
                try:
                    self.logger.info(f'Trying common sitemap location: {sitemap_url}')
                    response = requests.head(sitemap_url, timeout=10)
                    if response.status_code == 200:
                        sitemap_urls.append(sitemap_url)
                        self.logger.info(f'Found sitemap at: {sitemap_url}')
                        break
                except Exception as e:
                    self.logger.debug(f'Sitemap not found at {sitemap_url}: {e}')

        # If still no sitemap found, return empty list and let Scrapy handle the error
        if not sitemap_urls:
            self.logger.error(f'No sitemap found for domain: {domain}')

        return sitemap_urls

    def get_ignore_selectors(self, domain):
        """Get CSS selectors to ignore for specific domains"""
        # Get domain-specific selectors, fallback to default
        selectors = DOMAIN_SELECTORS.get(domain, DEFAULT_SELECTORS.copy())

        # Also check for subdomain matches (e.g., subdomain.readthedocs.io)
        if selectors == DEFAULT_SELECTORS:
            for known_domain, known_selectors in DOMAIN_SELECTORS.items():
                if known_domain in domain:
                    selectors = known_selectors.copy()
                    break

        self.logger.info(f'Using ignore selectors for {domain}: {selectors}')
        return selectors

    def strip_data_images(self, soup):
        """Remove <img> elements with data: src attributes"""
        data_images_removed = 0

        # Only remove img tags with data: src
        for img in soup.find_all('img', src=True):
            if img['src'].startswith('data:'):
                img.decompose()
                data_images_removed += 1

        if data_images_removed > 0:
            self.logger.debug(f'Removed {data_images_removed} data: images')

        return soup

    def convert_callouts_to_admonitions(self, soup):
        """Convert div.callout elements with h6 to admonition-style markdown callouts"""
        callouts_converted = 0

        # Map of h6 text to admonition types
        admonition_map = {
            'warning': ':warning:',
            'note': ':information_source:',
            'tip': ':bulb:',
            'important': ':exclamation:',
            'caution': ':warning:',
            'danger': ':no_entry:',
            'info': ':information_source:',
            'example': ':memo:',
            'see also': ':point_right:',
        }

        for callout_div in soup.find_all('div', class_='callout'):
            h6 = callout_div.find('h6')
            if not h6:
                continue

            h6_text = h6.get_text().strip().lower()

            # Find matching admonition type
            admonition_icon = None
            for keyword, icon in admonition_map.items():
                if keyword in h6_text:
                    admonition_icon = icon
                    break

            # Default to info if no match
            if not admonition_icon:
                admonition_icon = ':information_source:'

            # Create blockquote with icon and h6 text
            blockquote = soup.new_tag('blockquote')

            # Add the h6 text with icon as first paragraph
            header_p = soup.new_tag('p')
            header_p.string = f"{admonition_icon} {h6.get_text().strip()}"
            blockquote.append(header_p)

            # Remove the h6 from callout div
            h6.decompose()

            # Move all remaining content from callout div to blockquote
            for child in list(callout_div.children):
                if child.name:  # Skip text nodes
                    blockquote.append(child.extract())

            # Replace callout div with blockquote
            callout_div.replace_with(blockquote)
            callouts_converted += 1

        if callouts_converted > 0:
            self.logger.debug(f'Converted {callouts_converted} callout divs to admonitions')

        return soup

    def clean_code_blocks(self, soup):
        """Clean up code block HTML structure before markdown conversion"""
        code_blocks_cleaned = 0

        # Find code blocks with token-line structure
        for code_container in soup.find_all(['pre', 'code']):
            token_lines = code_container.find_all('div', class_='token-line')

            if token_lines:
                # Extract text from each token line and join with newlines
                lines = []
                for line_div in token_lines:
                    # Get text content from line-content span or the div itself
                    line_content = line_div.find(attrs={'data-line_content': 'true'})
                    if line_content:
                        lines.append(line_content.get_text())
                    else:
                        lines.append(line_div.get_text())

                # Replace the complex structure with simple text
                code_container.clear()
                code_container.string = '\n'.join(lines)
                code_blocks_cleaned += 1

        if code_blocks_cleaned > 0:
            self.logger.debug(f'Cleaned {code_blocks_cleaned} code blocks')

        return soup

    def extract_anchor_links(self, text):
        """Extract markdown anchor links from text (only internal #anchors)"""
        import re

        # Pattern to match markdown links that are internal anchors: [text](#anchor)
        anchor_pattern = r'\[([^\]]+)\]\(#([^)]+)\)'

        anchors = []
        for match in re.finditer(anchor_pattern, text):
            link_text = match.group(1)
            anchor_id = match.group(2)

            anchors.append({
                'text': link_text,
                'anchor': anchor_id
            })

        return anchors


    def semantic_chunk_with_openai(self, markdown_text, url):
        """Use OpenAI to identify semantic boundaries for chunking using split identifiers"""
        try:
            # Initialize OpenAI client
            client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

            # Split text into lines for LLM processing
            lines = markdown_text.split('\n')
            small_chunks = [line for line in lines if line.strip()]  # Filter out empty lines

            # Add chunk identifiers
            chunked_input = ''
            for i, chunk in enumerate(small_chunks):
                chunked_input += f"<|start_chunk_{i+1}|>{chunk}<|end_chunk_{i+1}|>"

            # Create prompt for semantic boundary identification
            system_prompt = """You are an assistant specialized in splitting text into thematically consistent sections.
The text has been divided into chunks, each marked with <|start_chunk_X|> and <|end_chunk_X|> tags, where X is the chunk number.
Your task is to identify the points where splits should occur, such that consecutive chunks of similar themes stay together.

Focus on:
- Topic changes or conceptual shifts
- Natural reading breaks that maintain context
- Keeping related examples, tables, code blocks, and explanations together
- Ensuring each chunk contains complete thoughts/concepts
- Prefer to split at markdown headers

Respond with a list of chunk IDs where you believe a split should be made. For example, if chunks 1 and 2 belong together but chunk 3 starts a new topic, you would suggest a split after chunk 2. THE CHUNKS MUST BE IN ASCENDING ORDER.
Your response should be in the form: 'split_after: 2, 5, 8'."""

            user_prompt = f"""CHUNKED_TEXT: {chunked_input}

Respond only with the IDs of the chunks where you believe a split should occur. YOU MUST RESPOND WITH AT LEAST ONE SPLIT. THESE SPLITS MUST BE IN ASCENDING ORDER."""

            # Call OpenAI API
            response = client.chat.completions.create(
                model="gpt-4o",  # Use cost-effective model
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,  # Low temperature for consistent results
                max_tokens=300
            )

            # Parse response to get split positions
            result_string = response.choices[0].message.content.strip()

            # Extract numbers from response
            try:
                # Find the line containing split_after
                split_after_lines = [line for line in result_string.split('\n') if 'split_after:' in line]
                if not split_after_lines:
                    # Fallback: extract all numbers from response
                    numbers = re.findall(r'\d+', result_string)
                else:
                    numbers = re.findall(r'\d+', split_after_lines[0])

                split_indices = list(map(int, numbers))

                # Validate that numbers are in ascending order
                if split_indices != sorted(split_indices):
                    raise ValueError(f"Split indices not in ascending order for {url}: {split_indices}")

            except Exception as e:
                raise ValueError(f"Could not parse OpenAI response for {url}: {e}")

            # Convert chunk IDs to split indices (0-based)
            chunks_to_split_after = [i - 1 for i in split_indices if i > 0 and i <= len(small_chunks)]

            # Create final chunks by combining lines based on split points
            final_chunks = []
            current_chunk_lines = []

            for i, line in enumerate(small_chunks):
                current_chunk_lines.append(line)
                if i in chunks_to_split_after or i == len(small_chunks) - 1:
                    if current_chunk_lines:
                        # Join lines back with newlines
                        chunk_content = '\n'.join(current_chunk_lines)

                        # Extract anchor links from chunk content
                        content_anchors = self.extract_anchor_links(chunk_content)

                        # Create metadata
                        chunk_metadata = {
                            'source_url': url,
                            'chunk_index': len(final_chunks),
                            'sub_chunk_index': 0,
                            'chunking_method': 'semantic_openai',
                            'line_range': f"{i - len(current_chunk_lines) + 1}-{i}"
                        }

                        # Add anchor information to metadata
                        if content_anchors:
                            chunk_metadata['anchor_links'] = content_anchors
                            chunk_metadata['anchor_count'] = len(content_anchors)
                            chunk_metadata['anchor_ids'] = [a['anchor'] for a in content_anchors]

                        final_chunks.append({
                            'content': chunk_content,
                            'metadata': chunk_metadata
                        })
                    current_chunk_lines = []

            self.logger.debug(f'Created {len(final_chunks)} semantic chunks using OpenAI from {len(small_chunks)} lines')
            return final_chunks

        except Exception as e:
            raise RuntimeError(f"OpenAI semantic chunking failed for {url}: {e}")

    def chunk_markdown_content_header_based(self, markdown_text, url):
        """Original header-based chunking method"""
        chunks = []

        # Define headers to split on (up to h3)
        headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
        ]

        # First pass: split by markdown headers
        markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=False  # Keep headers in the chunks
        )

        header_splits = markdown_splitter.split_text(markdown_text)

        # Second pass: recursive character splitting for large chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=2000,
            chunk_overlap=200,
            length_function=len,
            separators=["```", "\n\n", "\n", " ", ""]
        )

        for i, doc in enumerate(header_splits):
            # Get the header metadata
            metadata = doc.metadata.copy() if hasattr(doc, 'metadata') else {}
            metadata['source_url'] = url
            metadata['chunk_index'] = i
            metadata['chunking_method'] = 'header_based'

            # Extract anchor links from headers (breadcrumb context)
            header_anchors = []
            for level in ['Header 1', 'Header 2', 'Header 3']:
                if level in metadata:
                    header_anchors.extend(self.extract_anchor_links(metadata[level]))

            # Split large chunks further
            sub_chunks = text_splitter.split_text(doc.page_content)

            for j, chunk_text in enumerate(sub_chunks):
                chunk_metadata = metadata.copy()
                chunk_metadata['sub_chunk_index'] = j

                # Extract anchor links from chunk content
                content_anchors = self.extract_anchor_links(chunk_text)

                # Combine header and content anchors, removing duplicates
                all_anchors = header_anchors + content_anchors
                unique_anchors = []
                seen_anchors = set()
                for anchor in all_anchors:
                    anchor_key = (anchor['text'], anchor['anchor'])
                    if anchor_key not in seen_anchors:
                        unique_anchors.append(anchor)
                        seen_anchors.add(anchor_key)

                # Add anchor information to metadata
                if unique_anchors:
                    chunk_metadata['anchor_links'] = unique_anchors
                    chunk_metadata['anchor_count'] = len(unique_anchors)
                    # Also create a simple list of anchor IDs for easier searching
                    chunk_metadata['anchor_ids'] = [a['anchor'] for a in unique_anchors]

                chunks.append({
                    'content': chunk_text,
                    'metadata': chunk_metadata
                })

        self.logger.debug(f'Created {len(chunks)} chunks using header-based method')
        return chunks

    def chunk_markdown_content(self, markdown_text, url):
        """Route to appropriate chunking method based on configuration"""
        if self.chunking_method == 'semantic':
            return self.semantic_chunk_with_openai(markdown_text, url)
        else:  # Default to header-based
            return self.chunk_markdown_content_header_based(markdown_text, url)

    def sitemap_filter(self, entries):
        """Filter sitemap entries to only include HTML pages"""
        for entry in entries:
            # Only process HTML pages, skip images, PDFs, etc.
            if not any(ext in entry['loc'] for ext in ['.pdf', '.jpg', '.png', '.gif', '.css', '.js', '.xml']):
                yield entry

    def parse(self, response):
        """Parse each page from the sitemap"""
        url = response.url

        # Skip if already processed
        if url in self.processed_urls:
            return

        # Check if we've reached the maximum number of pages
        if self.max_pages and self.pages_processed >= self.max_pages:
            self.logger.info(f'Reached maximum pages limit ({self.max_pages}), stopping crawler')
            self.crawler.engine.close_spider(self, 'max_pages_reached')
            return

        self.processed_urls.add(url)
        self.pages_processed += 1

        # Log the URL being processed
        self.logger.info(f'Processing: {url}')

        try:
            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(response.body, 'html.parser')

            # Remove elements based on configured selectors
            for selector in self.ignore_selectors:
                elements = soup.select(selector)
                for element in elements:
                    element.decompose()
                if elements:
                    self.logger.debug(f'Removed {len(elements)} elements matching: {selector}')

            # Strip data: images if requested
            if self.should_strip_data_images:
                soup = self.strip_data_images(soup)

            # Convert callout divs to admonitions
            soup = self.convert_callouts_to_admonitions(soup)

            # Clean up code block structure
            soup = self.clean_code_blocks(soup)

            # Find main content
            main_content = soup.find("main") or soup
            html_content = str(main_content)

            # Convert to markdown
            markdown_output = md(html_content, heading_style="ATX")

            # Generate filename from URL
            filename = self.generate_filename(url)
            filepath = os.path.join(self.output_dir, filename)

            if self.should_chunk_content:
                # Chunk the content
                chunks = self.chunk_markdown_content(markdown_output, url)

                if self.db_manager is not None:
                    # Save to database
                    page_id = self.db_manager.save_page(
                        url=url,
                        domain=self.domain,
                        filename=filename,
                        content_length=len(markdown_output),
                        chunking_method=self.chunking_method
                    )

                    self.logger.info(f'Generating embeddings for {len(chunks)} chunks from: {url}')
                    self.db_manager.save_chunks(page_id, chunks)

                    self.logger.info(f'Saved {len(chunks)} chunks with embeddings to database: {url}')

                if self.file_manager is not None:
                    # Save to file
                    filepath = self.file_manager.save_chunked_content(url, filename, chunks)
                    self.logger.info(f'Saved {len(chunks)} chunks: {filepath}')

                return {
                    'url': url,
                    'filename': filename,
                    'content_length': len(markdown_output),
                    'chunks_count': len(chunks)
                }
            else:
                if self.db_manager is not None:
                    # Save to database without chunking
                    page_id = self.db_manager.save_page(
                        url=url,
                        domain=self.domain,
                        filename=filename,
                        content_length=len(markdown_output),
                        chunking_method='none'
                    )
                    # Save entire content as single chunk
                    single_chunk = [{
                        'content': markdown_output,
                        'metadata': {
                            'source_url': url,
                            'chunk_index': 0,
                            'sub_chunk_index': 0,
                            'chunking_method': 'none'
                        }
                    }]
                    self.db_manager.save_chunks(page_id, single_chunk)

                    self.logger.info(f'Saved to database: {url}')

                if self.file_manager is not None:
                    # Save to file
                    filepath = self.file_manager.save_regular_content(url, filename, markdown_output)
                    self.logger.info(f'Saved: {filepath}')

                return {
                    'url': url,
                    'filename': filename,
                    'content_length': len(markdown_output)
                }

        except Exception as e:
            self.logger.error(f'Error processing {url}: {str(e)}')
            return None

    def generate_filename(self, url):
        """Generate a safe filename from URL"""
        parsed = urlparse(url)
        path = parsed.path

        # Remove leading/trailing slashes and replace path separators
        path = path.strip('/')
        if not path:
            path = 'index'

        # Replace problematic characters
        safe_path = re.sub(r'[^\w\-_/]', '_', path)
        safe_path = re.sub(r'_+', '_', safe_path)  # Replace multiple underscores
        safe_path = safe_path.replace('/', '_')

        # Ensure filename isn't too long
        if len(safe_path) > 100:
            # Create hash of original path and truncate
            hash_suffix = hashlib.md5(path.encode()).hexdigest()[:8]
            safe_path = safe_path[:80] + '_' + hash_suffix

        return f"{safe_path}.md"


# Standalone script to run the spider
if __name__ == "__main__":
    import argparse
    import sys
    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    parser = argparse.ArgumentParser(
        description='Scrape websites using sitemaps and convert to chunked markdown for RAG applications',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Examples:
  %(prog)s docs.tigerdata.com
  %(prog)s docs.tigerdata.com -o tiger_docs -m 50
  %(prog)s docs.tigerdata.com -o semantic_docs -m 5 --chunking semantic
  %(prog)s docs.tigerdata.com --no-chunk --no-strip-images -m 100
  %(prog)s docs.tigerdata.com --storage-type database --database-uri postgresql://user:pass@host:5432/dbname
  %(prog)s docs.tigerdata.com --storage-type database --chunking semantic -m 10
        '''
    )

    # Optional arguments
    parser.add_argument('--domain', '-d',
                       help='Domain to scrape (e.g., docs.tigerdata.com)')

    parser.add_argument('-o', '--output-dir',
                       default='scraped_docs',
                       help='Output directory for scraped files (default: scraped_docs)')

    parser.add_argument('-m', '--max-pages',
                       type=int,
                       help='Maximum number of pages to scrape (default: unlimited)')

    parser.add_argument('--strip-images',
                       action='store_true',
                       default=True,
                       help='Strip data: images from content (default: True)')

    parser.add_argument('--no-strip-images',
                       dest='strip_images',
                       action='store_false',
                       help='Keep data: images in content')

    parser.add_argument('--chunk',
                       action='store_true',
                       default=True,
                       help='Enable content chunking (default: True)')

    parser.add_argument('--no-chunk',
                       dest='chunk',
                       action='store_false',
                       help='Disable content chunking')

    parser.add_argument('--chunking',
                       choices=['header', 'semantic'],
                       default='header',
                       help='Chunking method: header (default) or semantic (requires OPENAI_API_KEY)')

    # Storage options
    parser.add_argument('--storage-type',
                       choices=['file', 'database'],
                       default='database',
                       help='Storage type: database (default) or file')

    parser.add_argument('--database-uri',
                       help='PostgreSQL connection URI (default: uses DB_URL from environment)')

    parser.add_argument('--skip-indexes',
                       action='store_true',
                       help='Skip creating database indexes after import (for development/testing)')

    parser.add_argument('--delay',
                       type=float,
                       default=1.0,
                       help='Download delay in seconds (default: 1.0)')

    parser.add_argument('--concurrent',
                       type=int,
                       default=4,
                       help='Maximum concurrent requests (default: 4)')

    parser.add_argument('--log-level',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       default='INFO',
                       help='Logging level (default: INFO)')

    parser.add_argument('--user-agent',
                       default='Mozilla/5.0 (compatible; DocumentationScraper)',
                       help='User agent string')

    # Set defaults from environment variables
    parser.set_defaults(
        database_uri=os.environ.get('DB_URL', f'postgresql://{os.environ["PGUSER"]}:{os.environ['PGPASSWORD']}@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}'),
        domain=os.environ.get('SCRAPER_DOMAIN', 'docs.tigerdata.com'),
        max_pages=int(os.environ.get('SCRAPER_MAX_PAGES', 0)) or None,
        output_dir=os.environ.get('SCRAPER_OUTPUT_DIR', os.path.join(script_dir, 'build', 'scraped_docs')),
        chunking=os.environ.get('SCRAPER_CHUNKING_METHOD', 'header'),
        storage_type=os.environ.get('SCRAPER_STORAGE_TYPE', 'database')
    )

    args = parser.parse_args()

    # Validate semantic chunking requirements
    if args.chunking == 'semantic':
        if not os.getenv('OPENAI_API_KEY'):
            print("Error: Semantic chunking requires OPENAI_API_KEY environment variable")
            print("Set it with: export OPENAI_API_KEY=your_api_key")
            print("Or create a .env file with: OPENAI_API_KEY=your_api_key")
            sys.exit(1)

    # Configure Scrapy settings
    settings = get_project_settings()
    settings.update({
        'USER_AGENT': args.user_agent,
        'ROBOTSTXT_OBEY': True,
        'DOWNLOAD_DELAY': args.delay,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'CONCURRENT_REQUESTS': args.concurrent,
        'CONCURRENT_REQUESTS_PER_DOMAIN': min(args.concurrent, 2),
        'LOG_LEVEL': args.log_level,
    })

    print(f"Starting scraper for {args.domain}")
    print(f"Output directory: {args.output_dir}")
    print(f"Max pages: {args.max_pages or 'unlimited'}")
    print(f"Chunking: {'enabled' if args.chunk else 'disabled'} ({args.chunking})")
    print(f"Strip images: {args.strip_images}")
    print(f"Storage type: {args.storage_type}")
    if args.storage_type == 'database':
        print(f"Database URI: {args.database_uri}")
    print()

    # Initialize storage managers
    db_manager = None
    file_manager = None

    if args.storage_type == 'database':
        # Initialize embedding model for database storage (needed for both header and semantic)
        client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

        # Create embedding wrapper
        class OpenAIEmbeddingWrapper:
            def __init__(self, client):
                self.client = client
                self.model = "text-embedding-3-small"

            def get_text_embeddings(self, texts):
                response = self.client.embeddings.create(
                    input=texts,
                    model=self.model
                )
                return [embedding.embedding for embedding in response.data]

        embedding_model = OpenAIEmbeddingWrapper(client)
        db_manager = DatabaseManager(database_uri=args.database_uri, embedding_model=embedding_model)
        db_manager.create_tmp_tables()
    else:
        file_manager = FileManager(args.output_dir)

    process = CrawlerProcess(settings)
    process.crawl(
        SitemapMarkdownSpider,
        domain=args.domain,
        output_dir=args.output_dir,
        max_pages=args.max_pages,
        strip_data_images=args.strip_images,
        chunk_content=args.chunk,
        chunking_method=args.chunking,
        db_manager=db_manager,
        file_manager=file_manager
    )
    process.start()

    # Create database indexes after scraping completes
    if args.storage_type == 'database' and not args.skip_indexes and db_manager:
        try:
            print("Renaming temporary tables to final names...")
            db_manager.rename_objects()
            print("Database indexes created successfully!")
        except Exception as e:
            print(f"Failed to finish database: {e}")
            raise SystemExit(1)
        finally:
            db_manager.close()
