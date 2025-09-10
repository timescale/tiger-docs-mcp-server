import { semanticSearchPostgresDocsFactory } from './semanticSearchPostgresDocs.js';
import { semanticSearchTimescaleDocsFactory } from './semanticSearchTimescaleDocs.js';
import { getPromptContentFactory } from './getGuide.js';

export const apiFactories = [
  semanticSearchPostgresDocsFactory,
  semanticSearchTimescaleDocsFactory,
  getPromptContentFactory,
] as const;
