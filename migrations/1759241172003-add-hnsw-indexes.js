import 'dotenv/config';
import { Client } from 'pg';

const schema = process.env.DB_SCHEMA || 'docs';

export const description = 'Add HNSW indexes to embedding columns';

export async function up() {
  const client = new Client();

  try {
    await client.connect();
    await client.query(/* sql */ `
      CREATE INDEX CONCURRENTLY IF NOT EXISTS postgres_chunks_embedding_idx
      ON ${schema}.postgres_chunks
      USING hnsw (embedding vector_cosine_ops);
    `);
    await client.query(/* sql */ `
      CREATE INDEX CONCURRENTLY IF NOT EXISTS timescale_chunks_embedding_idx
      ON ${schema}.timescale_chunks
      USING hnsw (embedding vector_cosine_ops);
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
      DROP INDEX CONCURRENTLY IF EXISTS ${schema}.postgres_chunks_embedding_idx;
    `);
    await client.query(/* sql */ `
      DROP INDEX CONCURRENTLY IF EXISTS ${schema}.timescale_chunks_embedding_idx;
    `);
  } catch (e) {
    throw e;
  } finally {
    await client.end();
  }
}
