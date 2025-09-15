#!/usr/bin/env node
import { stdioServerFactory } from './shared/boilerplate/src/stdio.js';
import { apiFactories } from './apis/index.js';
import { prompts } from './prompts/index.js';
import { context, serverInfo } from './serverInfo.js';

// Convert prompts Map to promptFactories array for boilerplate compatibility
const promptFactories = Array.from(prompts.entries()).map(([name, promptData]) => 
  () => ({
    name,
    config: {
      title: promptData.title,
      description: promptData.description,
      inputSchema: {}, // No arguments for static prompts
    },
    fn: async () => ({
      description: promptData.description || promptData.title || name,
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text: promptData.content,
          },
        },
      ],
    }),
  })
);

stdioServerFactory({
  ...serverInfo,
  context,
  apiFactories,
  promptFactories,
});
