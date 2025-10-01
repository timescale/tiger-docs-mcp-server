import { ApiFactory } from '@tigerdata/mcp-boilerplate';
import { z } from 'zod';
import { ServerContext } from '../types.js';
import { prompts } from '../prompts/index.js';

// Create enum schema dynamically
const inputSchema = {
  guide_name: z
    .enum(Array.from(prompts.keys()) as [string, ...string[]])
    .describe('The name of the guide to retrieve'),
} as const;

const outputSchema = {
  guide_name: z.string().describe('The name of the requested guide'),
  title: z.string().describe('The display title of the guide'),
  description: z.string().describe('Description of what this guide does'),
  content: z.string().describe('The full guide content'),
} as const;

export const getPromptContentFactory: ApiFactory<
  ServerContext,
  typeof inputSchema,
  typeof outputSchema
> = () => ({
  name: 'get_guide',
  config: {
    title: 'Get TimescaleDB Guide',
    description: `Retrieve detailed TimescaleDB guides and best practices.

Available Guides:

${Array.from(prompts.values()).map(p => `**${p.name}** - ${p.description}`).join('\n\n')}
`,
    inputSchema,
    outputSchema,
  },
  fn: async ({ guide_name }) => {
    const prompt = prompts.get(guide_name);

    if (!prompt) {
      throw new Error(`Guide '${guide_name}' not found`);
    }

    return {
      guide_name: prompt.name,
      title: prompt.title || prompt.name,
      description: prompt.description || '',
      content: prompt.content,
    };
  },
});
