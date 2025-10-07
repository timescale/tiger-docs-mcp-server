import 'dotenv/config';
import { Client } from 'pg';

const schema = process.env.DB_SCHEMA || 'docs';

// We only want to run this if keyword search is enabled, where this expects
// that the user is using a Tiger Cloud backed database that has pg_textsearch
// available.
const keywordSearchEnabled = process.env.ENABLE_KEYWORD_SEARCH === 'true';

export const description = 'Add textsearch indexes to tiger docs content column';

export async function up() {
  if (!keywordSearchEnabled) {
    return;
  }

  const client = new Client();

  try {
    await client.connect();
    await client.query(/* sql */ `
      CREATE EXTENSION pg_textsearch;
    `);
    await client.query(/* sql */ `
      CREATE INDEX IF NOT EXISTS ON ${schema}.timescaledb_chunks USING bm25(content) WITH (text_config='english');
    `);
  } catch (e) {
    throw e;
  } finally {
    await client.end();
  }
}

export async function down() {
  if (!keywordSearchEnabled) {
    return;
  }

  const client = new Client();

  try {
    await client.connect();
    await client.query(/* sql */ `
      DROP INDEX IF EXISTS ${schema}.timescale_chunks_content_idx;
    `);
  } catch (e) {
    throw e;
  } finally {
    await client.end();
  }
}
