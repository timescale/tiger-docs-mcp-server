import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import { loadMarkdownPromptsFromDirectory } from './markdownLoader.js';
import { ServerContext } from '../types.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const markdownPromptsDir = join(__dirname, 'md');

export const promptFactories = [
  ...loadMarkdownPromptsFromDirectory<ServerContext>(markdownPromptsDir),
] as const;