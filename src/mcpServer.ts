import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { apiFactories } from './apis/index.js';
import { ServerContext } from './types.js';

export const createServer = (context: ServerContext) => {
  const server = new McpServer(
    {
      name: 'tiger-docs',
      version: '1.0.0',
    },
    {
      capabilities: {
        tools: {},
      },
    },
  );

  for (const factory of apiFactories) {
    const tool = factory(context);
    server.registerTool(tool.name, tool.config as any, async (args) => {
      try {
        const result = await tool.fn(args as any);
        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify(result),
            },
          ],
          structuredContent: result,
        };
      } catch (error) {
        console.error('Error invoking tool:', error);
        return {
          content: [
            {
              type: 'text',
              text: `Error: ${(error as Error).message || 'Unknown error'}`,
            },
          ],
          isError: true,
        };
      }
    });
  }

  return { server };
};
