#!/usr/bin/env node
import express, { NextFunction, Request, Response } from 'express';
import { Pool } from 'pg';

import { mcpRouterFactory } from './http/mcp.js';
import { ServerContext } from './types.js';
import { apiRouterFactory } from './http/api.js';

const pgPool = new Pool();
const context: ServerContext = { pgPool };

let handlingExit = false;
const exitHandler = (code = 0) => {
  if (handlingExit) return;
  handlingExit = true;

  console.error('Shutting down server...');
  server.close();

  Promise.allSettled([
    mcpCleanup()?.catch(console.error),
    apiCleanup()?.catch(console.error),
  ]).finally(() => {
    console.error('Server shutdown complete');
    process.exit(code);
  });
};

// Handle server shutdown
process.on('SIGINT', () => {
  exitHandler();
});
process.on('SIGTERM', () => {
  exitHandler();
});
process.on('uncaughtException', (err) => {
  console.error('Uncaught Exception:', err);
  exitHandler(1);
});

console.error('Starting HTTP server...');

const app = express();

const [mcpRouter, mcpCleanup] = mcpRouterFactory(context);
app.use('/mcp', mcpRouter);

const [apiRouter, apiCleanup] = apiRouterFactory(context);
app.use('/api', apiRouter);

// Error handler
app.use(function (err: Error, req: Request, res: Response, next: NextFunction) {
  console.log('Received error:', err.message);
  res.status(500).send(err.message);
});

// Start the server
const PORT = process.env.PORT || 3001;
const server = app.listen(PORT, (error?: Error) => {
  if (error) {
    console.error('Error starting HTTP server:', error);
    exitHandler(1);
  } else {
    console.error(`HTTP Server listening on port ${PORT}`);
  }
});
