#!/usr/bin/env node
import { httpServerFactory, log } from '@tigerdata/mcp-boilerplate';
import { apiFactories } from './apis/index.js';
import { promptFactories } from './skillutils/index.js';
import { runMigrations } from './migrate.js';
import { context, serverInfo } from './serverInfo.js';

log.info('starting server...');
try {
  log.info('Running database migrations...');
  await runMigrations();
  log.info('Database migrations completed successfully');
} catch (error) {
  log.error('Database migration failed:', error as Error);
  throw error;
}

export const { registerCleanupFn } = httpServerFactory({
  ...serverInfo,
  context,
  apiFactories,
  promptFactories,
  stateful: false,
});
