import { ApiFactory } from '@tigerdata/mcp-boilerplate';
import { z } from 'zod';
import { ServerContext } from '../types.js';
import { skills, viewSkillContent } from '../skills/index.js';

// Create enum schema dynamically
const inputSchema = {
  name: z
    .enum(Array.from(skills.keys()) as [string, ...string[]])
    .describe('The name of the skill to retrieve'),
} as const;

const outputSchema = {
  name: z.string().describe('The name of the requested skill'),
  title: z.string().describe('The display title of the skill'),
  description: z.string().describe('Description of what this skill does'),
  content: z.string().describe('The full skill content'),
} as const;

export const getSkillFactory: ApiFactory<
  ServerContext,
  typeof inputSchema,
  typeof outputSchema
> = () => ({
  name: 'get_skill',
  config: {
    title: 'Get Skill',
    description: `Retrieve detailed skills for TimescaleDB operations and best practices.

Available Skills:

${Array.from(skills.values()).map(s => `**${s.name}** - ${s.description}`).join('\n\n')}
`,
    inputSchema,
    outputSchema,
  },
  fn: async ({ name }) => {
    const skill = skills.get(name);

    if (!skill) {
      throw new Error(`Skill '${name}' not found`);
    }

    const content = await viewSkillContent(name);

    return {
      name: skill.name,
      title: skill.name, // Using name as title
      description: skill.description || '',
      content,
    };
  },
});