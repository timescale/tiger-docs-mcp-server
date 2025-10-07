import { z } from 'zod';
import { ApiFactory } from '../shared/boilerplate/src/types.js';
import { ServerContext } from '../types.js';
import { prompts } from '../prompts/index.js';

// Create enum schema dynamically
const inputSchema = {
  name: z
    .enum(Array.from(prompts.keys()) as [string, ...string[]])
    .describe('The name of the prompt template to retrieve'),
} as const;

const outputSchema = {
  name: z.string().describe('The name of the requested prompt template'),
  title: z.string().describe('The display title of the prompt template'),
  description: z.string().describe('Description of what this prompt template does'),
  content: z.string().describe('The full prompt template content'),
} as const;

export const getPromptTemplateFactory: ApiFactory<
  ServerContext,
  typeof inputSchema,
  typeof outputSchema
> = () => ({
  name: 'get_prompt_template',
  config: {
    title: 'Get Prompt Template',
    description: `Retrieve detailed prompt templates for TimescaleDB operations and best practices.

Available Templates:

${Array.from(prompts.values()).map(p => `**${p.name}** - ${p.description}`).join('\n\n')}
`,
    inputSchema,
    outputSchema,
  },
  fn: async ({ name }) => {
    const prompt = prompts.get(name);

    if (!prompt) {
      throw new Error(`Prompt template '${name}' not found`);
    }

    return {
      name: prompt.name,
      title: prompt.title || prompt.name,
      description: prompt.description || '',
      content: prompt.content,
    };
  },
});