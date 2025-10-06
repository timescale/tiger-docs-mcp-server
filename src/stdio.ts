#!/usr/bin/env node
import { stdioServerFactory } from '@tigerdata/mcp-boilerplate';
import { apiFactories } from './apis/index.js';
import { promptFactories } from './prompts/index.js';
import { context, serverInfo } from './serverInfo.js';


stdioServerFactory({
  ...serverInfo,
  context,
  apiFactories,
  promptFactories,
});
