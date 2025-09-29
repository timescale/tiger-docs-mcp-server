#!/usr/bin/env python3
"""
Tiger Blog Content Ingest Script

Fetches blog posts from the Tiger Ghost API, processes content for RAG,
and stores in PostgreSQL with embeddings.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import openai
import psycopg
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from psycopg.sql import SQL, Identifier

script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(script_dir, '..', '.env'))

schema = 'docs'

class BlogScraper:
    def __init__(self, api_url="https://www.tigerdata.com/api/ghost/getPosts"):
        self.api_url = api_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Tiger Blog Scraper 1.0'
        })

    def fetch_posts_batch(self, page: int, limit_per_page: int = 20) -> Tuple[List[Dict], bool]:
        """Fetch a single batch of posts from Ghost API. Returns (posts, has_more)."""
        params = {
            "include": "authors,tags",
            "limit": limit_per_page,
            "page": page
        }

        print(f"📡 Fetching page {page} (up to {limit_per_page} posts)...")
        response = self.session.get(self.api_url, params=params)
        response.raise_for_status()

        data = response.json()
        posts = data.get('posts', [])
        pagination = data.get('pagination', {})

        has_more = bool(pagination.get('next') and page < pagination.get('pages', 1))

        print(f"  ✅ Got {len(posts)} posts")
        return posts, has_more

    def fetch_all_posts(self, limit_per_page=100) -> List[Dict]:
        """Fetch all posts from Ghost API with pagination (for compatibility)."""
        all_posts = []
        page = 1

        while True:
            posts, has_more = self.fetch_posts_batch(page, limit_per_page)
            all_posts.extend(posts)

            if not has_more:
                break

            page += 1

        print(f"📊 Total posts available: {len(all_posts)}")
        return all_posts

    def html_to_clean_text(self, html_content: str) -> str:
        """Convert HTML content to clean text."""
        soup = BeautifulSoup(html_content, 'html.parser')

        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()

        # Get text and clean up whitespace
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)

        return text

    def filter_posts_by_tags(self, posts: List[Dict], include_tags: Optional[List[str]] = None, exclude_tags: Optional[List[str]] = None) -> List[Dict]:
        """Filter posts based on tag configuration."""
        if not include_tags and not exclude_tags:
            return posts

        filtered_posts = []

        for post in posts:
            post_tags = [tag['name'] for tag in post.get('tags', [])]

            # Check exclusions first
            if exclude_tags:
                if any(tag in exclude_tags for tag in post_tags):
                    print(f"Excluding '{post['title']}' due to tags: {post_tags}")
                    continue

            # Check inclusions (empty means include all)
            if include_tags:
                if not any(tag in include_tags for tag in post_tags):
                    print(f"Skipping '{post['title']}' - no matching tags: {post_tags}")
                    continue

            filtered_posts.append(post)

        return filtered_posts


class SemanticChunker:
    def __init__(self,
                 target_size: int = 1500,
                 min_size: int = 300,
                 max_size: int = 3000,
                 overlap: int = 200):
        self.target_size = target_size
        self.min_size = min_size
        self.max_size = max_size
        self.overlap = overlap

    def chunk_content(self, html_content: str, title: str) -> List[str]:
        """
        Chunk HTML content semantically while respecting size constraints.

        Strategy:
        1. Parse HTML structure
        2. Extract semantic elements (headings, paragraphs, code, lists)
        3. Combine elements until target size, respecting boundaries
        4. Only split within sections if absolutely necessary
        """

        # Convert HTML to structured elements
        elements = self._parse_html_structure(html_content)

        # Group elements into semantic chunks
        chunks = self._create_semantic_chunks(elements)

        return chunks

    def _parse_html_structure(self, html_content: str) -> List[Dict]:
        """Parse HTML into semantic elements."""
        soup = BeautifulSoup(html_content, 'html.parser')
        elements = []

        # Process each element in the HTML
        for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre', 'code', 'ul', 'ol', 'blockquote', 'div']):
            element_type = self._classify_element(element)
            if element_type:
                text = self._extract_clean_text(element)
                if text.strip():
                    elements.append({
                        'type': element_type,
                        'text': text.strip(),
                        'size': len(text.strip()),
                        'tag': element.name
                    })

        # If no structured elements found, fall back to paragraph splitting
        if not elements:
            elements = self._fallback_paragraph_split(soup.get_text())

        return elements

    def _classify_element(self, element) -> str:
        """Classify HTML element by semantic meaning."""
        tag = element.name.lower()

        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            return 'heading'
        elif tag == 'pre' or (tag == 'code' and len(element.get_text()) > 50):
            return 'code_block'
        elif tag in ['ul', 'ol']:
            return 'list'
        elif tag == 'blockquote':
            return 'quote'
        elif tag == 'p':
            text = element.get_text().strip()
            # Check if paragraph contains code-like content
            if any(keyword in text for keyword in ['SELECT', 'CREATE', 'INSERT', 'UPDATE', 'DELETE', 'FROM', 'WHERE']) and len(text) > 100:
                return 'code_paragraph'
            return 'paragraph'
        elif tag == 'div':
            # Only include divs with substantial text content
            text = element.get_text().strip()
            if len(text) > 50:
                return 'paragraph'

        return None

    def _extract_clean_text(self, element) -> str:
        """Extract clean text from HTML element."""
        # Remove nested script/style elements
        for nested in element.find_all(['script', 'style']):
            nested.decompose()

        text = element.get_text()

        # Clean up whitespace but preserve code formatting
        if element.name in ['pre', 'code']:
            # Preserve code formatting
            lines = text.split('\n')
            cleaned_lines = [line.rstrip() for line in lines]
            return '\n'.join(cleaned_lines)
        else:
            # Normal text cleanup
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            return ' '.join(chunk for chunk in chunks if chunk)

    def _fallback_paragraph_split(self, text: str) -> List[Dict]:
        """Fallback method when no HTML structure is found."""
        paragraphs = text.split('\n\n')
        elements = []

        for para in paragraphs:
            para = para.strip()
            if para:
                # Check if paragraph contains code
                if any(keyword in para for keyword in ['SELECT', 'CREATE', 'INSERT', '```', 'FROM']):
                    element_type = 'code_paragraph'
                else:
                    element_type = 'paragraph'

                elements.append({
                    'type': element_type,
                    'text': para,
                    'size': len(para),
                    'tag': 'p'
                })

        return elements

    def _create_semantic_chunks(self, elements: List[Dict]) -> List[str]:
        """Create chunks from semantic elements."""
        chunks = []
        current_chunk = []
        current_size = 0

        i = 0
        while i < len(elements):
            element = elements[i]

            # Handle different element types
            if element['type'] == 'heading':
                # Headings start new chunks (unless current chunk is very small)
                if current_chunk and current_size >= self.min_size:
                    chunks.append(self._finalize_chunk(current_chunk))
                    current_chunk = []
                    current_size = 0

                current_chunk.append(element)
                current_size += element['size']

            elif element['type'] in ['code_block', 'code_paragraph']:
                # Keep code blocks intact - never split
                if current_size + element['size'] > self.max_size and current_chunk:
                    # Current chunk is full, start new one
                    chunks.append(self._finalize_chunk(current_chunk))
                    current_chunk = [element]
                    current_size = element['size']
                else:
                    current_chunk.append(element)
                    current_size += element['size']

            elif element['type'] == 'list':
                # Keep lists intact
                if current_size + element['size'] > self.max_size and current_chunk:
                    chunks.append(self._finalize_chunk(current_chunk))
                    current_chunk = [element]
                    current_size = element['size']
                else:
                    current_chunk.append(element)
                    current_size += element['size']

            else:
                # Regular paragraphs - combine until target size
                if current_size + element['size'] > self.target_size and current_chunk:
                    # Check if we should finalize current chunk
                    if current_size >= self.min_size:
                        chunks.append(self._finalize_chunk(current_chunk))

                        # Start new chunk with overlap
                        overlap_elements = self._get_overlap_elements(current_chunk)
                        current_chunk = overlap_elements + [element]
                        current_size = sum(e['size'] for e in current_chunk)
                    else:
                        # Current chunk too small, keep adding
                        current_chunk.append(element)
                        current_size += element['size']
                else:
                    current_chunk.append(element)
                    current_size += element['size']

            # Safety check for oversized chunks
            if current_size > self.max_size:
                if len(current_chunk) > 1:
                    # Split the chunk
                    chunks.append(self._finalize_chunk(current_chunk[:-1]))
                    current_chunk = [current_chunk[-1]]  # Keep last element
                    current_size = current_chunk[0]['size']
                else:
                    # Single huge element - split if it's a paragraph
                    if current_chunk[0]['type'] == 'paragraph':
                        split_chunks = self._split_large_paragraph(current_chunk[0])
                        chunks.extend(split_chunks[:-1])
                        current_chunk = [split_chunks[-1]] if split_chunks else []
                        current_size = split_chunks[-1]['size'] if split_chunks else 0
                    else:
                        # Can't split (code block, etc.) - keep as is
                        chunks.append(self._finalize_chunk(current_chunk))
                        current_chunk = []
                        current_size = 0

            i += 1

        # Add final chunk
        if current_chunk:
            chunks.append(self._finalize_chunk(current_chunk))

        return chunks

    def _finalize_chunk(self, elements: List[Dict]) -> str:
        """Convert elements into final chunk text."""
        chunk_parts = []

        for element in elements:
            if element['type'] == 'heading':
                # Add some formatting to headings
                chunk_parts.append(f"\n{element['text']}\n")
            elif element['type'] in ['code_block', 'code_paragraph']:
                # Preserve code formatting
                chunk_parts.append(f"\n{element['text']}\n")
            elif element['type'] == 'list':
                chunk_parts.append(f"{element['text']}")
            else:
                chunk_parts.append(element['text'])

        return ' '.join(chunk_parts).strip()

    def _get_overlap_elements(self, current_chunk: List[Dict]) -> List[Dict]:
        """Get elements for overlap with next chunk."""
        if not current_chunk:
            return []

        # Take last few elements up to overlap size
        overlap_elements = []
        overlap_size = 0

        for element in reversed(current_chunk):
            if overlap_size + element['size'] <= self.overlap:
                overlap_elements.insert(0, element)
                overlap_size += element['size']
            else:
                break

        return overlap_elements

    def _split_large_paragraph(self, element: Dict) -> List[Dict]:
        """Split a large paragraph by sentences."""
        text = element['text']
        sentences = re.split(r'(?<=[.!?])\s+', text)

        split_elements = []
        current_text = ""

        for sentence in sentences:
            if len(current_text + sentence) > self.target_size and current_text:
                split_elements.append({
                    'type': 'paragraph',
                    'text': current_text.strip(),
                    'size': len(current_text.strip()),
                    'tag': 'p'
                })
                current_text = sentence
            else:
                current_text += " " + sentence if current_text else sentence

        if current_text:
            split_elements.append({
                'type': 'paragraph',
                'text': current_text.strip(),
                'size': len(current_text.strip()),
                'tag': 'p'
            })

        return split_elements


class BlogChunker:
    def __init__(self, chunking_method='semantic', chunk_size=1000, chunk_overlap=200):
        self.chunking_method = chunking_method
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        if chunking_method == 'semantic':
            self.semantic_chunker = SemanticChunker(
                target_size=chunk_size,
                min_size=max(100, chunk_size // 3),
                max_size=chunk_size * 3,
                overlap=chunk_overlap
            )
        else:
            self.text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                length_function=len,
                separators=["\n\n", "\n", " ", ""]
            )

    def chunk_content(self, html_content: str, title: str) -> List[str]:
        """Create chunks from HTML content."""
        if not html_content or len(html_content) < 100:
            return []

        if self.chunking_method == 'semantic':
            # Use sophisticated HTML-aware semantic chunking
            chunks = self.semantic_chunker.chunk_content(html_content, title)
        else:
            # Fallback to simple text-based chunking
            scraper = BlogScraper()
            text_content = scraper.html_to_clean_text(html_content)
            chunks = self.text_splitter.split_text(text_content)

        # Filter out very short chunks
        chunks = [chunk for chunk in chunks if len(chunk.strip()) >= 100]
        return chunks


class BlogDatabaseManager:
    def __init__(self, database_uri: str, embedding_model: str = "text-embedding-3-small"):
        self.database_uri = database_uri
        self.embedding_model = embedding_model
        self.openai_client = openai.OpenAI() if os.getenv('OPENAI_API_KEY') else None

        try:
            self.connection = psycopg.connect(database_uri)
        except Exception as e:
            raise RuntimeError(f"Database connection failed: {e}")

    def create_tmp_tables(self):
        """Create temporary tables for atomic updates."""
        with self.connection.cursor() as cursor:
            cursor.execute(SQL("DROP TABLE IF EXISTS {schema}.tiger_blog_chunks_tmp").format(schema=Identifier(schema)))
            cursor.execute(SQL("DROP TABLE IF EXISTS {schema}.tiger_blog_pages_tmp").format(schema=Identifier(schema)))

            cursor.execute(SQL("CREATE TABLE {schema}.tiger_blog_pages_tmp (LIKE {schema}.tiger_blog_pages INCLUDING ALL)").format(schema=Identifier(schema)))
            cursor.execute(SQL("CREATE TABLE {schema}.tiger_blog_chunks_tmp (LIKE {schema}.tiger_blog_chunks INCLUDING ALL)").format(schema=Identifier(schema)))
            cursor.execute(SQL("ALTER TABLE {schema}.tiger_blog_chunks_tmp ADD FOREIGN KEY (page_id) REFERENCES {schema}.tiger_blog_pages_tmp(id) ON DELETE CASCADE").format(schema=Identifier(schema)))

        self.connection.commit()

    def rename_objects(self):
        """Rename temporary tables to final names."""
        with self.connection.cursor() as cursor:
            cursor.execute(SQL("DROP TABLE IF EXISTS {schema}.tiger_blog_chunks").format(schema=Identifier(schema)))
            cursor.execute(SQL("DROP TABLE IF EXISTS {schema}.tiger_blog_pages").format(schema=Identifier(schema)))

            cursor.execute(SQL("ALTER TABLE {schema}.tiger_blog_chunks_tmp RENAME TO tiger_blog_chunks").format(schema=Identifier(schema)))
            cursor.execute(SQL("ALTER TABLE {schema}.tiger_blog_pages_tmp RENAME TO tiger_blog_pages").format(schema=Identifier(schema)))

            # Rename indexes if they exist
            try:
                cursor.execute(SQL("ALTER INDEX {schema}.tiger_blog_chunks_tmp_embedding_idx RENAME TO tiger_blog_chunks_embedding_idx").format(schema=Identifier(schema)))
                cursor.execute(SQL("ALTER INDEX {schema}.tiger_blog_pages_tmp_published_at_idx RENAME TO tiger_blog_pages_published_at_idx").format(schema=Identifier(schema)))
                cursor.execute(SQL("ALTER INDEX {schema}.tiger_blog_pages_tmp_tags_idx RENAME TO tiger_blog_pages_tags_idx").format(schema=Identifier(schema)))
                cursor.execute(SQL("ALTER INDEX {schema}.tiger_blog_chunks_tmp_page_id_idx RENAME TO tiger_blog_chunks_page_id_idx").format(schema=Identifier(schema)))
            except psycopg.errors.UndefinedObject:
                pass  # Indexes might not exist yet

        self.connection.commit()

    def save_page(self, post: Dict) -> int:
        """Save blog page information and return page ID."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                SQL("""
                INSERT INTO {schema}.tiger_blog_pages_tmp
                (url, title, slug, published_at, updated_at, excerpt, tags, authors,
                 content_length, chunking_method, post_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """).format(schema=Identifier(schema)),
                (
                    f"https://www.tigerdata.com/blog/{post['slug']}",
                    post['title'],
                    post['slug'],
                    post.get('published_at'),
                    post.get('updated_at'),
                    post.get('excerpt', ''),
                    [tag['name'] for tag in post.get('tags', [])],
                    [author['name'] for author in post.get('authors', [])],
                    len(post.get('html', '')),
                    'semantic',
                    post['id']
                )
            )
            page_id = cursor.fetchone()[0]

        self.connection.commit()
        return page_id

    def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text using OpenAI."""
        if not self.openai_client:
            raise RuntimeError("OpenAI client not available. Set OPENAI_API_KEY environment variable.")

        try:
            response = self.openai_client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"Error generating embedding: {e}")
            raise

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts in a single API call."""
        if not self.openai_client:
            raise RuntimeError("OpenAI client not available. Set OPENAI_API_KEY environment variable.")

        if not texts:
            return []

        try:
            print(f"  🔄 Generating embeddings for {len(texts)} chunks...")
            response = self.openai_client.embeddings.create(
                model=self.embedding_model,
                input=texts
            )
            embeddings = [data.embedding for data in response.data]
            print(f"  ✅ Generated {len(embeddings)} embeddings")
            return embeddings
        except Exception as e:
            print(f"  ❌ Error generating batch embeddings: {e}")
            raise

    def save_chunks_batch(self, chunks_data: List[Tuple], embedding_batch_size: int = 100):
        """Save multiple chunks with batch embedding generation."""
        if not chunks_data:
            return 0

        total_saved = 0

        # Process chunks in batches for embedding generation
        for batch_start in range(0, len(chunks_data), embedding_batch_size):
            batch_end = min(batch_start + embedding_batch_size, len(chunks_data))
            batch = chunks_data[batch_start:batch_end]

            # Extract texts for embedding
            texts = [chunk_data[4] for chunk_data in batch]  # content is at index 4

            # Generate embeddings in batch
            embeddings = self.generate_embeddings_batch(texts)

            # Insert chunks with embeddings
            with self.connection.cursor() as cursor:
                for i, (page_id, chunk_id, chunk_index, metadata, content, post) in enumerate(batch):
                    cursor.execute(
                        SQL("""
                        INSERT INTO {schema}.tiger_blog_chunks_tmp
                        (id, page_id, chunk_index, content, metadata, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """).format(schema=Identifier(schema)),
                        (
                            chunk_id,
                            page_id,
                            chunk_index,
                            content,
                            json.dumps(metadata),
                            embeddings[i]
                        )
                    )

                total_saved += len(batch)

        self.connection.commit()
        return total_saved

    def save_chunks(self, page_id: int, chunks: List[str], post: Dict):
        """Save chunks with embeddings for a page (legacy single-post method)."""
        if not chunks:
            return 0

        # Update chunks count
        with self.connection.cursor() as cursor:
            cursor.execute(
                SQL("UPDATE {schema}.tiger_blog_pages_tmp SET chunks_count = %s WHERE id = %s").format(schema=Identifier(schema)),
                (len(chunks), page_id)
            )

        # Prepare chunks data for batch processing
        chunks_data = []
        for i, chunk_content in enumerate(chunks):
            # Create chunk metadata
            metadata = {
                'title': post['title'],
                'slug': post['slug'],
                'url': f"https://www.tigerdata.com/blog/{post['slug']}",
                'published_at': post.get('published_at', ''),
                'updated_at': post.get('updated_at', ''),
                'excerpt': post.get('excerpt', ''),
                'tags': [tag['name'] for tag in post.get('tags', [])],
                'authors': [author['name'] for author in post.get('authors', [])],
                'chunk_index': i,
                'total_chunks': len(chunks),
                'source': 'tigerdata_blog',
                'post_id': post['id']
            }

            chunk_id = f"{post['slug']}-chunk-{i}"
            chunks_data.append((page_id, chunk_id, i, metadata, chunk_content, post))

        # Use batch processing for embeddings
        return self.save_chunks_batch(chunks_data, embedding_batch_size=50)

    def create_indexes(self):
        """Create indexes for efficient search."""
        with self.connection.cursor() as cursor:
            # Vector similarity index
            cursor.execute(SQL("""
                CREATE INDEX IF NOT EXISTS tiger_blog_chunks_embedding_idx
                ON {schema}.tiger_blog_chunks USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """).format(schema=Identifier(schema)))

            # Other useful indexes
            cursor.execute(SQL("""
                CREATE INDEX IF NOT EXISTS tiger_blog_pages_published_at_idx
                ON {schema}.tiger_blog_pages (published_at)
            """).format(schema=Identifier(schema)))

            cursor.execute(SQL("""
                CREATE INDEX IF NOT EXISTS tiger_blog_pages_tags_idx
                ON {schema}.tiger_blog_pages USING gin (tags)
            """).format(schema=Identifier(schema)))

            cursor.execute(SQL("""
                CREATE INDEX IF NOT EXISTS tiger_blog_chunks_page_id_idx
                ON {schema}.tiger_blog_chunks (page_id)
            """).format(schema=Identifier(schema)))

        self.connection.commit()

    def close(self):
        if hasattr(self, 'connection'):
            self.connection.close()


def main():
    parser = argparse.ArgumentParser(description='Ingest Tiger blog posts into database')
    parser.add_argument('--chunking', choices=['semantic', 'simple'], default='semantic',
                        help='Chunking method (default: semantic)')
    parser.add_argument('--chunk-size', type=int, default=1000,
                        help='Target chunk size in characters (default: 1000)')
    parser.add_argument('--chunk-overlap', type=int, default=200,
                        help='Chunk overlap in characters (default: 200)')
    parser.add_argument('--max-posts', type=int,
                        help='Maximum number of posts to process (for testing)')
    parser.add_argument('--include-tags', nargs='+', metavar='TAG',
                        help='Only include posts that have at least one of these tags')
    parser.add_argument('--exclude-tags', nargs='+', metavar='TAG',
                        help='Exclude posts that have any of these tags')
    parser.add_argument('--skip-embeddings', action='store_true',
                        help='Skip embedding generation (for testing)')
    parser.add_argument('--database-uri',
                        default=f"postgresql://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}",
                        help='PostgreSQL connection URI')
    parser.add_argument('--skip-indexes', action='store_true',
                        help='Skip creating indexes (for development/testing)')
    parser.add_argument('--delay', type=float, default=0.5,
                        help='Delay between API calls in seconds (default: 0.5)')
    parser.add_argument('--debug-chunks', action='store_true',
                        help='Show detailed chunking information for debugging')
    parser.add_argument('--batch-size', type=int, default=20,
                        help='Number of posts to fetch and process per batch (default: 20)')
    parser.add_argument('--embedding-batch-size', type=int, default=100,
                        help='Number of embeddings to generate per batch (default: 100)')
    parser.add_argument('--concurrent-posts', type=int, default=3,
                        help='Number of posts to process concurrently (default: 3)')

    args = parser.parse_args()

    if not args.database_uri:
        print("Error: DATABASE_URL environment variable or --database-uri required")
        sys.exit(1)

    if not args.skip_embeddings and not os.getenv('OPENAI_API_KEY'):
        print("Error: OPENAI_API_KEY environment variable required for embeddings")
        sys.exit(1)

    try:
        print("🚀 Starting Tiger blog ingestion...")

        # Initialize components
        scraper = BlogScraper()
        chunker = BlogChunker(
            chunking_method=args.chunking,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap
        )
        db_manager = BlogDatabaseManager(args.database_uri)

        # Create temporary tables
        print("🗄️ Setting up temporary database tables...")
        db_manager.create_tmp_tables()

        # Process posts in batches
        total_chunks = 0
        processed_posts = 0
        page = 1
        posts_processed_in_batch = 0
        max_posts_remaining = args.max_posts

        while True:
            # Fetch next batch
            batch_posts, has_more = scraper.fetch_posts_batch(page, args.batch_size)

            if not batch_posts:
                break

            # Apply tag filtering to batch
            if args.include_tags or args.exclude_tags:
                if page == 1:  # Show filtering info only once
                    print(f"🏷️ Applying tag filters...")
                    if args.include_tags:
                        print(f"  ✅ Include tags: {args.include_tags}")
                    if args.exclude_tags:
                        print(f"  ❌ Exclude tags: {args.exclude_tags}")

                original_count = len(batch_posts)
                batch_posts = scraper.filter_posts_by_tags(batch_posts, args.include_tags, args.exclude_tags)
                filtered_count = len(batch_posts)

                if original_count != filtered_count:
                    print(f"  📊 Batch {page}: {filtered_count}/{original_count} posts passed filters")

            # Apply max_posts limit
            if max_posts_remaining is not None:
                if len(batch_posts) > max_posts_remaining:
                    batch_posts = batch_posts[:max_posts_remaining]
                    has_more = False  # Stop after this batch
                max_posts_remaining -= len(batch_posts) if max_posts_remaining else 0

            if not batch_posts:
                print(f"  📭 No posts to process in batch {page}")
                if not has_more:
                    break
                page += 1
                continue

            print(f"\n🔄 Processing batch {page}: {len(batch_posts)} posts")

            # Collect all chunks from the batch for optimized embedding generation
            all_chunks_data = []
            posts_with_pages = []

            # First pass: generate chunks and save page info
            for i, post in enumerate(batch_posts):
                post_num = processed_posts + i + 1
                print(f"\n📰 Processing post {post_num}: {post['title'][:60]}{'...' if len(post['title']) > 60 else ''}")

                try:
                    # Save page info
                    page_id = db_manager.save_page(post)

                    # Create chunks
                    html_content = post.get('html', '')
                    if not html_content:
                        print("  ⚠️ No content found, skipping...")
                        continue

                    chunks = chunker.chunk_content(html_content, post['title'])
                    print(f"  📄 Generated {len(chunks)} chunks")

                    # Debug chunking information
                    if args.debug_chunks:
                        print(f"    📊 Chunk Analysis:")
                        for idx, chunk in enumerate(chunks):
                            preview = chunk.replace('\n', ' ')[:80]
                            print(f"      Chunk {idx+1:2d}: {len(chunk):4d} chars | {preview}...")

                    if chunks:
                        # Prepare chunks data for batch embedding processing
                        for chunk_idx, chunk_content in enumerate(chunks):
                            metadata = {
                                'title': post['title'],
                                'slug': post['slug'],
                                'url': f"https://www.tigerdata.com/blog/{post['slug']}",
                                'published_at': post.get('published_at', ''),
                                'updated_at': post.get('updated_at', ''),
                                'excerpt': post.get('excerpt', ''),
                                'tags': [tag['name'] for tag in post.get('tags', [])],
                                'authors': [author['name'] for author in post.get('authors', [])],
                                'chunk_index': chunk_idx,
                                'total_chunks': len(chunks),
                                'source': 'tigerdata_blog',
                                'post_id': post['id']
                            }

                            chunk_id = f"{post['slug']}-chunk-{chunk_idx}"
                            all_chunks_data.append((page_id, chunk_id, chunk_idx, metadata, chunk_content, post))

                        posts_with_pages.append((post, page_id, len(chunks)))

                    # Rate limiting for API calls (not for embeddings)
                    if args.delay > 0:
                        time.sleep(args.delay)

                except Exception as e:
                    print(f"  ❌ Error processing post: {e}")
                    continue

            # Second pass: generate embeddings for all chunks in batch
            if all_chunks_data and not args.skip_embeddings:
                print(f"\n🚀 Batch embedding generation for {len(all_chunks_data)} chunks across {len(batch_posts)} posts")
                saved_chunks = db_manager.save_chunks_batch(all_chunks_data, args.embedding_batch_size)
                total_chunks += saved_chunks

                # Update chunk counts for pages
                with db_manager.connection.cursor() as cursor:
                    for post, page_id, chunk_count in posts_with_pages:
                        cursor.execute(
                            SQL("UPDATE {schema}.tiger_blog_pages_tmp SET chunks_count = %s WHERE id = %s").format(schema=Identifier(schema)),
                            (chunk_count, page_id)
                        )
                db_manager.connection.commit()

                print(f"  ✅ Saved {saved_chunks} chunks with embeddings across batch")
            elif all_chunks_data:
                print(f"  ⏭️ Skipped embeddings for {len(all_chunks_data)} chunks")

            processed_posts += len(batch_posts)
            print(f"📊 Batch {page} complete. Total progress: {processed_posts} posts, {total_chunks} chunks")

            # Check if we should continue
            if not has_more or (max_posts_remaining is not None and max_posts_remaining <= 0):
                break

            page += 1

        # Create indexes if requested
        if not args.skip_indexes and not args.skip_embeddings:
            print("🔍 Creating database indexes...")
            db_manager.create_indexes()

        # Rename temporary tables to final names
        print("🔄 Finalizing database changes...")
        db_manager.rename_objects()

        print(f"\n🎉 Ingestion completed!")
        print(f"📊 Summary:")
        print(f"  - Processed posts: {processed_posts}")
        print(f"  - Total chunks: {total_chunks}")
        print(f"  - Chunking method: {args.chunking}")

        if args.skip_embeddings:
            print("  ⚠️ Embeddings were skipped")

    except KeyboardInterrupt:
        print("\n⚠️ Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error during ingestion: {e}")
        sys.exit(1)
    finally:
        if 'db_manager' in locals():
            db_manager.close()


if __name__ == "__main__":
    main()