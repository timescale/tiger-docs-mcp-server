#!/usr/bin/env node
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { createServer } from './mcpServer.js';
import { ServerContext } from './types.js';
import { Pool } from 'pg';

const pgPool = new Pool();
const context: ServerContext = { pgPool };

console.error('Starting default (STDIO) server...');

async function main() {
  const transport = new StdioServerTransport();
  const { server } = createServer(context);

  await server.connect(transport);

  // Cleanup on exit
  process.on('SIGINT', async () => {
    await server.close();
    process.exit(0);
  });
}

main().catch((error) => {
  console.error('Server error:', error);
  process.exit(1);
});
