import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { InMemoryEventStore } from '@modelcontextprotocol/sdk/examples/shared/inMemoryEventStore.js';
import { Request, Response, Router } from 'express';
import { createServer } from '../mcpServer.js';
import { randomUUID } from 'node:crypto';
import { RouterFactory } from '../types.js';

export const mcpRouterFactory: RouterFactory = (context) => {
  const router = Router();

  const transports: Map<string, StreamableHTTPServerTransport> = new Map<
    string,
    StreamableHTTPServerTransport
  >();

  router.post('/', async (req: Request, res: Response) => {
    console.error('Received MCP POST request');
    try {
      // Check for existing session ID
      const sessionId = req.headers['mcp-session-id'] as string | undefined;
      let transport: StreamableHTTPServerTransport;

      if (sessionId && transports.has(sessionId)) {
        // Reuse existing transport
        transport = transports.get(sessionId)!;
      } else if (!sessionId) {
        const { server } = createServer(context);

        // New initialization request
        const eventStore = new InMemoryEventStore();
        transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          eventStore, // Enable resumability
          onsessioninitialized: (sessionId: string) => {
            // Store the transport by session ID when session is initialized
            // This avoids race conditions where requests might come in before the session is stored
            console.error(`Session initialized with ID: ${sessionId}`);
            transports.set(sessionId, transport);
          },
          onsessionclosed: (sessionId: string) => {
            if (sessionId && transports.has(sessionId)) {
              console.error(
                `Transport closed for session ${sessionId}, removing from transports map`,
              );
              transports.delete(sessionId);
            }
          },
        });

        // Connect the transport to the MCP server BEFORE handling the request
        // so responses can flow back through the same transport
        await server.connect(transport);

        await transport.handleRequest(req, res);
        return; // Already handled
      } else {
        // Invalid request - no session ID or not initialization request
        res.status(400).json({
          jsonrpc: '2.0',
          error: {
            code: -32000,
            message: 'Bad Request: No valid session ID provided',
          },
          id: req?.body?.id,
        });
        return;
      }

      // Handle the request with existing transport - no need to reconnect
      // The existing transport is already connected to the server
      await transport.handleRequest(req, res);
    } catch (error) {
      console.error('Error handling MCP request:', error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: '2.0',
          error: {
            code: -32603,
            message: 'Internal server error',
          },
          id: req?.body?.id,
        });
        return;
      }
    }
  });

  // Handle GET requests for SSE streams (using built-in support from StreamableHTTP)
  router.get('/', async (req: Request, res: Response) => {
    console.error('Received MCP GET request');
    const sessionId = req.headers['mcp-session-id'] as string | undefined;
    if (!sessionId || !transports.has(sessionId)) {
      res.status(400).json({
        jsonrpc: '2.0',
        error: {
          code: -32000,
          message: 'Bad Request: No valid session ID provided',
        },
        id: req?.body?.id,
      });
      return;
    }

    // Check for Last-Event-ID header for resumability
    const lastEventId = req.headers['last-event-id'] as string | undefined;
    if (lastEventId) {
      console.error(`Client reconnecting with Last-Event-ID: ${lastEventId}`);
    } else {
      console.error(`Establishing new SSE stream for session ${sessionId}`);
    }

    const transport = transports.get(sessionId);
    await transport!.handleRequest(req, res);
  });

  // Handle DELETE requests for session termination (according to MCP spec)
  router.delete('/', async (req: Request, res: Response) => {
    const sessionId = req.headers['mcp-session-id'] as string | undefined;
    if (!sessionId || !transports.has(sessionId)) {
      res.status(400).json({
        jsonrpc: '2.0',
        error: {
          code: -32000,
          message: 'Bad Request: No valid session ID provided',
        },
        id: req?.body?.id,
      });
      return;
    }

    console.error(
      `Received session termination request for session ${sessionId}`,
    );

    try {
      const transport = transports.get(sessionId);
      await transport!.handleRequest(req, res);
    } catch (error) {
      console.error('Error handling session termination:', error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: '2.0',
          error: {
            code: -32603,
            message: 'Error handling session termination',
          },
          id: req?.body?.id,
        });
        return;
      }
    }
  });

  const cleanup = async () => {
    // Close all active transports to properly clean up resources
    for (const sessionId in transports) {
      try {
        console.error(`Closing transport for session ${sessionId}`);
        await transports.get(sessionId)!.close();
        transports.delete(sessionId);
      } catch (error) {
        console.error(
          `Error closing transport for session ${sessionId}:`,
          error,
        );
      }
    }
  };

  return [router, cleanup];
};
