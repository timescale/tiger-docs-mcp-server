#!/usr/bin/env node
import { httpServerFactory } from './shared/boilerplate/src/httpServer.js';
import { apiFactories } from './apis/index.js';
import { context, serverInfo } from './serverInfo.js';

export const { registerCleanupFn } = httpServerFactory({
  ...serverInfo,
  context,
  apiFactories,
});
