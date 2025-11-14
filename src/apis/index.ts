import { semanticSearchPostgresDocsFactory } from './semanticSearchPostgresDocs.js';
import { semanticSearchTigerDocsFactory } from './semanticSearchTigerDocs.js';
import { getSkillFactory } from './getSkill.js';
import { keywordSearchTigerDocsFactory } from './kewordSearchTigerDocs.js';

export const apiFactories = [
  keywordSearchTigerDocsFactory,
  semanticSearchPostgresDocsFactory,
  semanticSearchTigerDocsFactory,
  getSkillFactory,
] as const;
