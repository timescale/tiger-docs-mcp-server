import { ApiFactory } from '@tigerdata/mcp-boilerplate';
import { z } from 'zod';
import { ServerContext } from '../types.js';
import { skills, viewSkillContent } from '../skillutils/index.js';
import { parseFeatureFlags } from '../util/featureFlags.js';

// Create enum schema dynamically
const inputSchema = {
  name: z
    .enum(Array.from(skills.keys()) as [string, ...string[]])
    .describe('The name of the skill to retrieve'),
  path: z
    .string()
    .default('SKILL.md')
    .describe('Path within the skill directory (defaults to SKILL.md)'),
} as const;

const outputSchema = {
  name: z.string().describe('The name of the requested skill'),
  path: z.string().describe('The path within the skill (e.g., "SKILL.md")'),
  description: z.string().describe('Description of what this skill does'),
  content: z.string().describe('The full skill content'),
} as const;

export const getSkillFactory: ApiFactory<
  ServerContext,
  typeof inputSchema,
  typeof outputSchema
> = (_context, { query }) => {
  // Parse feature flags from query or environment
  const flags = parseFeatureFlags(query);

  // Return disabled factory if MCP skills are disabled
  if (!flags.mcpSkillsEnabled) {
    return { disabled: true } as any;
  }

  return {
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
    fn: async ({ name, path }) => {
      const skill = skills.get(name);

      if (!skill) {
        throw new Error(`Skill '${name}' not found`);
      }

      const content = await viewSkillContent(name, path);

      return {
        name: skill.name,
        path,
        description: skill.description || '',
        content,
      };
    },
  };
};