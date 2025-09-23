import { Pool } from 'pg';

import { schema } from './config.js';
import { ServerContext } from './types.js';

export const serverInfo = {
  name: 'tiger-docs',
  version: '1.0.0',
} as const;

const pgPool = new Pool();

export const context: ServerContext = { pgPool, schema };
