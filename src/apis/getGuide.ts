import { z } from 'zod';
import { readdirSync, readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import matter from 'gray-matter';
import { ApiFactory } from '../shared/boilerplate/src/types.js';
import { ServerContext } from '../types.js';
import { promptFactories } from '../prompts/index.js';

// Get all available prompt names dynamically from markdown files
const __dirname = dirname(fileURLToPath(import.meta.url));
const markdownPromptsDir = join(__dirname, '../prompts/md');

function getAvailablePrompts() {
  const files = readdirSync(markdownPromptsDir).filter(file => file.endsWith('.md'));
  const prompts = files.map(file => {
    const filePath = join(markdownPromptsDir, file);
    const fileContent = readFileSync(filePath, 'utf-8');
    const { data } = matter(fileContent);
    return {
      name: data.name,
      title: data.title,
      description: data.description,
    };
  });
  return prompts;
}

const availablePrompts = getAvailablePrompts();
const promptNames = availablePrompts.map(p => p.name);

// Create enum schema dynamically
const inputSchema = {
  prompt_name: z
    .enum(promptNames as [string, ...string[]])
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
> = ({ pgPool }) => ({
  name: 'getGuide',
  config: {
    title: 'Get TimescaleDB Guide',
    description: `Retrieve detailed TimescaleDB guides and best practices.

Available Guides:

${availablePrompts.map(p => `**${p.name}** - ${p.description}`).join('\n\n')}
`,
    inputSchema,
    outputSchema,
  },
  fn: async ({ prompt_name }) => {
    // Find the prompt factory by name
    const promptFactory = promptFactories.find(factory => {
      const prompt = factory({} as ServerContext);
      return prompt.name === prompt_name;
    });

    if (!promptFactory) {
      throw new Error(`Prompt '${prompt_name}' not found`);
    }

    // Create the prompt instance
    const prompt = promptFactory({} as ServerContext);

    // Execute the prompt to get its content
    const result = await prompt.fn({});

    // Extract content from the prompt result
    const content = result.messages?.[0]?.content?.text || '';

    return {
      prompt_name: prompt.name,
      title: prompt.config.title || prompt.name,
      description: prompt.config.description || '',
      content: String(content),
    };
  },
});