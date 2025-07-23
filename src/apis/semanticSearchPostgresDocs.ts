import { z } from 'zod';
import { openai } from '@ai-sdk/openai';
import { embed } from 'ai';

import { type ApiFactory } from '../types.js';

const inputSchema = {
  version: z
    .number()
    .int()
    .optional()
    .default(17)
    .describe('The PostgreSQL version to use for the query. Defaults to 17.'),
  limit: z
    .number()
    .min(1)
    .optional()
    .default(10)
    .describe('The maximum number of matches to return. Defaults to 10.'),
  prompt: z
    .string()
    .min(1)
    .describe(
      'The natural language query used to search the PostgreSQL documentation for relevant information.',
    ),
} as const;

const zEmbeddedDoc = z.object({
  id: z
    .number()
    .int()
    .describe('The unique identifier of the documentation entry.'),
  headerPath: z
    .array(z.string())
    .describe('The path to the header of the documentation entry.'),
  content: z.string().describe('The content of the documentation entry.'),
  tokenCount: z
    .number()
    .int()
    .describe('The number of tokens in the documentation entry.'),
  distance: z
    .number()
    .describe(
      'The distance score indicating the relevance of the entry to the prompt. Lower values indicate higher relevance.',
    ),
});

type EmbeddedDoc = z.infer<typeof zEmbeddedDoc>;

const outputSchema = {
  results: z.array(zEmbeddedDoc),
} as const;

export const semanticSearchPostgresDocsFactory: ApiFactory<
  typeof inputSchema,
  typeof outputSchema,
  z.infer<(typeof outputSchema)['results']>
> = ({ pgPool }) => ({
  name: 'semanticSearchPostgresDocs',
  method: 'get',
  route: '/semantic-search/postgres-docs',
  config: {
    title: 'Semantic Search of PostgreSQL Documentation Embeddings',
    description:
      'This retrieves relevant PostgreSQL documentation entries based on a natural language query.',
    inputSchema,
    outputSchema,
  },
  fn: async ({ prompt, version, limit }) => {
    const { embedding } = await embed({
      model: openai.embedding('text-embedding-3-small'),
      value: prompt,
    });

    const result = await pgPool.query<EmbeddedDoc>(
      /* sql */ `
SELECT
  id::int,
  header_path AS "headerPath",
  content,
  token_count::int AS "tokenCount",
  embedding <=> $1::vector(1536) AS distance
 FROM docs.postgres
 WHERE version = $2
 ORDER BY distance
 LIMIT $3
`,
      [JSON.stringify(embedding), version, limit],
    );

    console.log(result.rows);

    return {
      results: result.rows,
    };
  },
  pickResult: (r) => r.results,
});
