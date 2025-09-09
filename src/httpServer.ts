#!/usr/bin/env node
import { httpServerFactory } from './shared/boilerplate/src/httpServer.js';
import { apiFactories } from './apis/index.js';
import { log } from './shared/boilerplate/src/logger.js';
import { runMigrations } from './migrate.js';
import { context, serverInfo } from './serverInfo.js';

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
});
