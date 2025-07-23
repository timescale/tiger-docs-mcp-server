#!/usr/bin/env node
import { ServerContext } from './types.js';
import { Pool } from 'pg';

import { stdioServerFactory } from './shared/boilerplate/src/stdio.js';
import { apiFactories } from './apis/index.js';
import { serverInfo } from './serverInfo.js';

const pgPool = new Pool();
const context: ServerContext = { pgPool };

stdioServerFactory({
  ...serverInfo,
  context,
  apiFactories,
});
