import { semanticSearchPostgresDocsFactory } from './semanticSearchPostgresDocs.js';
import { semanticSearchTigerDocsFactory } from './semanticSearchTigerDocs.js';
import { viewSkillFactory } from './viewSkill.js';
import { keywordSearchTigerDocsFactory } from './kewordSearchTigerDocs.js';

export const apiFactories = [
  keywordSearchTigerDocsFactory,
  semanticSearchPostgresDocsFactory,
  semanticSearchTigerDocsFactory,
  viewSkillFactory,
] as const;
