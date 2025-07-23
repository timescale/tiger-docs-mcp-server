/**
 * REST API alternative to MCP for direct use of the same tools.
 */

import { Router } from 'express';
import { z } from 'zod';
import { RouterFactory } from '../types.js';
import { apiFactories } from '../apis/index.js';

export const apiRouterFactory: RouterFactory = (context) => {
  const router = Router();

  for (const factory of apiFactories) {
    const tool = factory(context);
    if (!tool.method || !tool.route) continue;

    router[tool.method](tool.route, async (req, res) => {
      const Input = z.object(tool.config.inputSchema);
      const input = tool.method === 'get' ? req.query : req.body;
      const result = await tool.fn(Input.parse(input) as any);
      res.json(tool.pickResult ? tool.pickResult(result as any) : result);
    });
  }

  return [router, () => {}];
};
