import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';
import matter from 'gray-matter';
import { z } from 'zod';
import { PromptFactory } from '../shared/boilerplate/src/types.js';

const PromptArgumentSchema = z.object({
  name: z.string(),
  description: z.string().optional(),
  required: z.boolean().optional().default(false),
});

const PromptFrontmatterSchema = z.object({
  name: z.string(),
  title: z.string().optional(),
  description: z.string().optional(),
  arguments: z.array(PromptArgumentSchema).optional().default([]),
});

export const loadMarkdownPrompt = <Context extends Record<string, unknown>>(
  filePath: string,
): PromptFactory<Context, any> => {
  const fileContent = readFileSync(filePath, 'utf-8');
  const { data, content } = matter(fileContent);
  
  const frontmatter = PromptFrontmatterSchema.parse(data);
  
  // Create zod schema from arguments
  const inputSchemaShape: Record<string, z.ZodTypeAny> = {};
  for (const arg of frontmatter.arguments) {
    let schema: z.ZodTypeAny = z.string();
    if (arg.description) {
      schema = schema.describe(arg.description);
    }
    if (!arg.required) {
      schema = schema.optional();
    }
    inputSchemaShape[arg.name] = schema;
  }

  return () => ({
    name: frontmatter.name,
    config: {
      title: frontmatter.title,
      description: frontmatter.description,
      inputSchema: inputSchemaShape,
    },
    fn: async (args) => {
      return {
        description: frontmatter.description || frontmatter.title || frontmatter.name,
        messages: [
          {
            role: 'user',
            content: {
              type: 'text',
              text: content.trim(),
            },
          },
        ],
      };
    },
  });
};

export const loadMarkdownPromptsFromDirectory = <Context extends Record<string, unknown>>(
  dirPath: string,
): PromptFactory<Context, any>[] => {
  const files = readdirSync(dirPath).filter((file: string) => file.endsWith('.md'));
  
  return files.map((file: string) => 
    loadMarkdownPrompt<Context>(join(dirPath, file))
  );
};