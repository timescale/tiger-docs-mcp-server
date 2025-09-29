import { semanticSearchPostgresDocsFactory } from './semanticSearchPostgresDocs.js';
import { semanticSearchTigerDocsFactory } from './semanticSearchTigerDocs.js';
import { getPromptContentFactory } from './getGuide.js';
import { keywordSearchTigerDocsFactory } from './kewordSearchTigerDocs.js';

export const apiFactories = [
  keywordSearchTigerDocsFactory,
  semanticSearchPostgresDocsFactory,
  semanticSearchTigerDocsFactory,
  getPromptContentFactory,
] as const;
