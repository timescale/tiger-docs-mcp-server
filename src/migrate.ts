import migrate from 'migrate';
import path from 'path';
import { Client } from 'pg';
import { createHash } from 'crypto';
import { fileURLToPath } from 'url';
import { schema } from './config.js';

const schemaNamePattern = /^[a-zA-Z_][a-zA-Z0-9_]*$/;

if (!schemaNamePattern.test(schema)) {
  throw new Error(
    `Invalid schema name '${schema}'. Schema names must start with a letter or underscore and contain only letters, numbers, or underscores.`,
  );
}

// Use a hash of the project name
const hash = createHash('sha256')
  .update('tiger-docs-mcp-server')
  .digest('hex');
const MIGRATION_ADVISORY_LOCK_ID = BigInt(`0x${hash.substring(0, 15)}`);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const createStateStore = () => {
  let client: Client;

  return {
    async load(callback: (err: Error | null, set?: any) => void) {
      try {
        client = new Client();
        await client.connect();

        // Acquire advisory lock to prevent concurrent migrations
        await client.query(/* sql */ `SELECT pg_advisory_lock($1)`, [
          MIGRATION_ADVISORY_LOCK_ID,
        ]);

        // Ensure schema exists
        await client.query(/* sql */ `
          CREATE SCHEMA IF NOT EXISTS ${schema};
        `);
        
        // Ensure migrations table exists
        await client.query(/* sql */ `
          CREATE TABLE IF NOT EXISTS ${schema}.migrations (
            id SERIAL PRIMARY KEY,
            set JSONB NOT NULL,
            applied_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
          );
        `);

        // Load the most recent migration set
        const result = await client.query(
          /* sql */ `SELECT set FROM ${schema}.migrations ORDER BY applied_at DESC LIMIT 1`,
        );

        const set = result.rows.length > 0 ? result.rows[0].set : {};
        callback(null, set);
      } catch (error) {
        callback(error as Error);
      }
    },

    async save(set: any, callback: (err: Error | null) => void) {
      try {
        // Insert the entire set as JSONB
        await client.query(
          /* sql */ `INSERT INTO ${schema}.migrations (set) VALUES ($1)`,
          [JSON.stringify(set)],
        );

        callback(null);
      } catch (error) {
        callback(error as Error);
      }
    },

    async close() {
      if (client) {
        // Release advisory lock
        await client.query(/* sql */ `SELECT pg_advisory_unlock($1)`, [
          MIGRATION_ADVISORY_LOCK_ID,
        ]);
        await client.end();
      }
    },
  };
};

export const runMigrations = async (): Promise<void> => {
  return new Promise((resolve, reject) => {
    const stateStore = createStateStore();

    migrate.load(
      {
        stateStore,
        migrationsDirectory: path.join(__dirname, '..', 'migrations'),
      },
      (err, set) => {
        if (err) {
          stateStore.close().finally(() => reject(err));
          return;
        }

        set.up((err) => {
          stateStore.close().finally(() => {
            if (err) {
              reject(err);
            } else {
              resolve();
            }
          });
        });
      },
    );
  });
};
