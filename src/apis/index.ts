import { semanticSearchPostgresDocsFactory } from './semanticSearchPostgresDocs.js';
import { semanticSearchTimescaleDocsFactory } from './semanticSearchTimescaleDocs.js';
import { semanticSearchTigerBlogFactory } from './semanticSearchTigerBlog.js';
import { getPromptContentFactory } from './getGuide.js';

export const apiFactories = [
  semanticSearchPostgresDocsFactory,
  semanticSearchTimescaleDocsFactory,
  semanticSearchTigerBlogFactory,
  getPromptContentFactory,
] as const;
