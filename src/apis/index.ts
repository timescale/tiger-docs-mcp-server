import { semanticSearchPostgresDocsFactory } from './semanticSearchPostgresDocs.js';
import { semanticSearchTigerDocsFactory } from './semanticSearchTigerDocs.js';
import { getPromptContentFactory } from './getGuide.js';

export const apiFactories = [
  semanticSearchPostgresDocsFactory,
  semanticSearchTigerDocsFactory,
  getPromptContentFactory,
] as const;
