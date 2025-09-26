import { z } from 'zod';
import { openai } from '@ai-sdk/openai';
import { embed } from 'ai';
import { ApiFactory } from '../shared/boilerplate/src/types.js';
import { ServerContext } from '../types.js';

const inputSchema = {
  limit: z.coerce
    .number()
    .min(1)
    .nullable()
    .describe('The maximum number of matches to return. Defaults to 10.'),
  prompt: z
    .string()
    .min(1)
    .describe(
      'The natural language query used to search the documentation for relevant information.',
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

export const semanticSearchTigerDocsFactory: ApiFactory<
  ServerContext,
  typeof inputSchema,
  typeof outputSchema,
  z.infer<(typeof outputSchema)['results']>
> = ({ pgPool, schema }) => ({
  name: 'semanticSearchTigerDocs',
  method: 'get',
  route: '/semantic-search/tiger-docs',
  config: {
    title: 'Semantic Search of Tiger Documentation Embeddings',
    description:
      'This retrieves relevant documentation entries based on a natural language query. The content covers Tiger Cloud and TimescaleDB topics.',
    inputSchema,
    outputSchema,
  },
  fn: async ({ prompt, limit }) => {
    const { embedding } = await embed({
      model: openai.embedding('text-embedding-3-small'),
      value: prompt,
    });

    const result = await pgPool.query<EmbeddedDoc>(
      /* sql */ `
SELECT
  id::int,
  content,
  metadata::text,
  embedding <=> $1::vector(1536) AS distance
 FROM ${schema}.timescale_chunks
 ORDER BY distance
 LIMIT $2
`,
      [JSON.stringify(embedding), limit || 10],
    );

    return {
      results: result.rows,
    };
  },
  pickResult: (r) => r.results,
});
