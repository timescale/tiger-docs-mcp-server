import { semanticSearchPostgresDocsFactory } from './semanticSearchPostgresDocs.js';
import { semanticSearchTigerDocsFactory } from './semanticSearchTigerDocs.js';
import { getPromptTemplateFactory } from './getPromptTemplate.js';
import { keywordSearchTigerDocsFactory } from './kewordSearchTigerDocs.js';

export const apiFactories = [
  keywordSearchTigerDocsFactory,
  semanticSearchPostgresDocsFactory,
  semanticSearchTigerDocsFactory,
  getPromptTemplateFactory,
] as const;
