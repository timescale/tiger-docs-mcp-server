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
  tags: z
    .array(z.string())
    .nullable()
    .describe('Filter results to only include posts with these tags.'),
  prompt: z
    .string()
    .min(1)
    .describe(
      'The natural language query used to search the Tiger blog for relevant information.',
    ),
} as const;

const zBlogChunk = z.object({
  id: z
    .string()
    .describe('The unique identifier of the blog chunk.'),
  content: z.string().describe('The content of the blog chunk.'),
  metadata: z
    .string()
    .describe(
      'Additional metadata about the blog chunk, including title, tags, authors, and URL, as a JSON encoded string.',
    ),
  distance: z
    .number()
    .describe(
      'The distance score indicating the relevance of the chunk to the prompt. Lower values indicate higher relevance.',
    ),
});

type BlogChunk = z.infer<typeof zBlogChunk>;

const outputSchema = {
  results: z.array(zBlogChunk),
} as const;

export const semanticSearchTigerBlogFactory: ApiFactory<
  ServerContext,
  typeof inputSchema,
  typeof outputSchema,
  z.infer<(typeof outputSchema)['results']>
> = ({ pgPool, schema }) => ({
  name: 'semanticSearchTigerBlog',
  method: 'get',
  route: '/semantic-search/tiger-blog',
  config: {
    title: 'Semantic Search of Tiger Blog Content',
    description:
      'This retrieves relevant Tiger blog post chunks based on a natural language query.',
    inputSchema,
    outputSchema,
  },
  fn: async ({ prompt, limit, tags }) => {
    const { embedding } = await embed({
      model: openai.embedding('text-embedding-3-small'),
      value: prompt,
    });

    // Build the query with optional tag filtering
    let query = /* sql */ `
SELECT
  c.id,
  c.content,
  c.metadata::text,
  c.embedding <=> $1::vector(1536) AS distance
 FROM ${schema}.tiger_blog_chunks c
 JOIN ${schema}.tiger_blog_pages p ON c.page_id = p.id
`;

    const queryParams: any[] = [JSON.stringify(embedding)];

    if (tags && tags.length > 0) {
      query += ` WHERE p.tags && $${queryParams.length + 1}`;
      queryParams.push(tags);
    }

    query += ` ORDER BY distance LIMIT $${queryParams.length + 1}`;
    queryParams.push(limit || 10);

    const result = await pgPool.query<BlogChunk>(query, queryParams);

    return {
      results: result.rows,
    };
  },
  pickResult: (r) => r.results,
});