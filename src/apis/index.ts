import { semanticSearchPostgresDocsFactory } from './semanticSearchPostgresDocs.js';
import { semanticSearchTimescaleDocsFactory } from './semanticSearchTimescaleDocs.js';

export const apiFactories = [
  semanticSearchPostgresDocsFactory,
  semanticSearchTimescaleDocsFactory,
] as const;
