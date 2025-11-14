import { ApiFactory } from '@tigerdata/mcp-boilerplate';
import { z } from 'zod';
import { ServerContext } from '../types.js';
import { skills, viewSkillContent } from '../prompts/index.js';

// Create enum schema dynamically
const inputSchema = {
  name: z
    .enum(Array.from(skills.keys()) as [string, ...string[]])
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

${Array.from(skills.values()).map(s => `**${s.name}** - ${s.description}`).join('\n\n')}
`,
    inputSchema,
    outputSchema,
  },
  fn: async ({ name }) => {
    const skill = skills.get(name);

    if (!skill) {
      throw new Error(`Prompt template '${name}' not found`);
    }

    const content = await viewSkillContent(name);

    return {
      name: skill.name,
      title: skill.name, // Using name as title for backward compatibility
      description: skill.description || '',
      content,
    };
  },
});
