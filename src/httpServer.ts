#!/usr/bin/env node
import { Pool } from 'pg';

import { ServerContext } from './types.js';
import { httpServerFactory } from './shared/boilerplate/src/httpServer.js';
import { apiFactories } from './apis/index.js';
import { serverInfo } from './serverInfo.js';

const pgPool = new Pool();
const context: ServerContext = { pgPool };

httpServerFactory({
  ...serverInfo,
  context,
  apiFactories,
});
