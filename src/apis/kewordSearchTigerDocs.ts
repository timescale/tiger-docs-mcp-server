import { ApiFactory } from '@tigerdata/mcp-boilerplate';
import { z } from 'zod';
import { ServerContext } from '../types.js';

const inputSchema = {
  limit: z.coerce
    .number()
    .min(1)
    .nullable()
    .describe('The maximum number of matches to return. Defaults to 10.'),
  keywords: z
    .string()
    .min(1)
    .describe(
      'The set of keywords to search for.',
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
  score: z
    .number()
    .describe(
      'The score indicating the relevance of the entry to the keywords. Higher values indicate higher relevance.',
    ),
});

type EmbeddedDoc = z.infer<typeof zEmbeddedDoc>;

const outputSchema = {
  results: z.array(zEmbeddedDoc),
} as const;

export const keywordSearchTigerDocsFactory: ApiFactory<
  ServerContext,
  typeof inputSchema,
  typeof outputSchema,
  z.infer<(typeof outputSchema)['results']>
> = ({ pgPool, schema }) => ({
  name: 'keyword_search_tiger_docs',
  method: 'get',
  route: '/keyword-search/tiger-docs',
  config: {
    title: 'Keyword Search of Tiger Documentation',
    description:
      'This retrieves relevancy ranked documentation entries based on a set of keywords, using a bm25 search. The content covers Tiger Cloud and TimescaleDB topics.',
    inputSchema,
    outputSchema,
  },
  disabled: process.env.ENABLE_KEYWORD_SEARCH !== 'true',
  fn: async ({ keywords, limit }) => {
    const result = await pgPool.query<EmbeddedDoc>(
      /* sql */ `
SELECT
  id::int,
  content,
  metadata::text,
  -(content <@> to_bm25query($1, $3)) as score
 FROM ${schema}.timescale_chunks
 ORDER BY content <@> to_bm25query($1, $3)
 LIMIT $2
`,
      [keywords, limit ?? 10, `${schema}.timescale_chunks_content_idx`],
    );

    return {
      results: result.rows,
    };
  },
  pickResult: (r) => r.results,
});
