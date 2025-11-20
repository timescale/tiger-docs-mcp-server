import { ApiFactory, InferSchema } from '@tigerdata/mcp-boilerplate';
import { openai } from '@ai-sdk/openai';
import { embed } from 'ai';
import { z } from 'zod';
import { ServerContext } from '../types.js';

const inputSchema = {
  version: z
    .enum(['14', '15', '16', '17', '18'])
    .describe(
      'The PostgreSQL major version to use for the query. Recommended to assume the latest version if unknown.',
    ),
  limit: z.coerce
    .number()
    .int()
    .describe('The maximum number of matches to return. Defaults to 10.'),
  prompt: z
    .string()
    .describe(
      'The natural language query used to search the PostgreSQL documentation for relevant information.',
    ),
} as const;

const zEmbeddedDoc = z.object({
  id: z
    .number()
    .int()
    .describe('The unique identifier of the documentation entry.'),
  content: z.string().describe('The content of the documentation entry.'),
  metadata: z
    .string()
    .describe(
      'Additional metadata about the documentation entry, as a JSON encoded string.',
    ),
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

type OutputSchema = InferSchema<typeof outputSchema>;

export const semanticSearchPostgresDocsFactory: ApiFactory<
  ServerContext,
  typeof inputSchema,
  typeof outputSchema,
  z.infer<(typeof outputSchema)['results']>
> = ({ pgPool, schema }) => ({
  name: 'semantic_search_postgres_docs',
  method: 'get',
  route: '/semantic-search/postgres-docs',
  config: {
    title: 'Semantic Search of PostgreSQL Documentation Embeddings',
    description:
      'This retrieves relevant PostgreSQL documentation entries based on a natural language query.',
    inputSchema,
    outputSchema,
  },
  fn: async ({ prompt, version, limit }): Promise<OutputSchema> => {
    if (limit < 0) {
      throw new Error('Limit must be a non-negative integer.');
    }
    if (!prompt.trim()) {
      throw new Error('Prompt must be a non-empty string.');
    }

    const { embedding } = await embed({
      model: openai.embedding('text-embedding-3-small'),
      value: prompt,
    });

    const result = await pgPool.query<EmbeddedDoc>(
      /* sql */ `
SELECT
  c.id::int,
  c.content,
  c.metadata::text,
  c.embedding <=> $1::vector(1536) AS distance
 FROM ${schema}.postgres_chunks c
 JOIN ${schema}.postgres_pages p ON c.page_id = p.id
 WHERE p.version = $2
 ORDER BY distance
 LIMIT $3
`,
      [JSON.stringify(embedding), version, limit || 10],
    );

    return {
      results: result.rows,
    };
  },
  pickResult: (r) => r.results,
});
