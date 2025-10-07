import 'dotenv/config';
import { Client } from 'pg';

const schema = process.env.DB_SCHEMA || 'docs';

export const description = 'Add HNSW indexes to embedding columns';

export async function up() {
  const client = new Client();

  try {
    await client.connect();
    await client.query(/* sql */ `
      CREATE INDEX CONCURRENTLY IF NOT EXISTS timescale_pages_domain_idx
      ON ${schema}.timescale_pages(domain);
    `);
    await client.query(/* sql */ `
      CREATE INDEX CONCURRENTLY IF NOT EXISTS timescale_pages_url_idx
      ON ${schema}.timescale_pages(url);
    `);
    await client.query(/* sql */ `
      CREATE INDEX CONCURRENTLY IF NOT EXISTS timescale_chunks_page_id_idx
      ON ${schema}.timescale_chunks(page_id);
    `);
    await client.query(/* sql */ `
      CREATE INDEX CONCURRENTLY IF NOT EXISTS timescale_chunks_metadata_idx
      ON ${schema}.timescale_chunks
      USING gin(metadata);
    `);
  } catch (e) {
    throw e;
  } finally {
    await client.end();
  }
}

export async function down() {
  const client = new Client();

  try {
    await client.connect();
    await client.query(/* sql */ `
      DROP INDEX CONCURRENTLY IF EXISTS ${schema}.timescale_pages_domain_idx;
    `);
    await client.query(/* sql */ `
      DROP INDEX CONCURRENTLY IF EXISTS ${schema}.timescale_pages_url_idx;
    `);
    await client.query(/* sql */ `
      DROP INDEX CONCURRENTLY IF EXISTS ${schema}.timescale_chunks_page_id_idx;
    `);
    await client.query(/* sql */ `
      DROP INDEX CONCURRENTLY IF EXISTS ${schema}.timescale_chunks_metadata_idx;
    `);
  } catch (e) {
    throw e;
  } finally {
    await client.end();
  }
}
