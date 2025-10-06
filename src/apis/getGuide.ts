import { ApiFactory } from '@tigerdata/mcp-boilerplate';
import { z } from 'zod';
import { ServerContext } from '../types.js';
import { prompts } from '../prompts/index.js';

// Create enum schema dynamically
const inputSchema = {
  prompt_name: z
    .enum(Array.from(prompts.keys()) as [string, ...string[]])
    .describe('The name of the prompt to retrieve'),
} as const;

const outputSchema = {
  prompt_name: z.string().describe('The name of the requested prompt'),
  title: z.string().describe('The display title of the prompt'),
  description: z.string().describe('Description of what this prompt does'),
  content: z.string().describe('The full prompt content'),
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
  fn: async ({ prompt_name }) => {
    const prompt = prompts.get(prompt_name);

    if (!prompt) {
      throw new Error(`Prompt '${prompt_name}' not found`);
    }

    return {
      prompt_name: prompt.name,
      title: prompt.title || prompt.name,
      description: prompt.description || '',
      content: prompt.content,
    };
  },
});
