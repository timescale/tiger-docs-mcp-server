import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import { readdirSync, readFileSync } from 'fs';
import matter from 'gray-matter';

const __dirname = dirname(fileURLToPath(import.meta.url));
const markdownPromptsDir = join(__dirname, 'md');

// Load all markdown prompts with their metadata
function loadPrompts() {
  const files = readdirSync(markdownPromptsDir).filter(file => file.endsWith('.md'));
  const promptsMap = new Map();
  
  for (const file of files) {
    const promptName = file.replace('.md', '');
    const filePath = join(markdownPromptsDir, file);
    const fileContent = readFileSync(filePath, 'utf-8');
    const { data, content } = matter(fileContent);
    
    promptsMap.set(promptName, {
      name: promptName,
      title: data.title,
      description: data.description,
      content: content.trim(),
    });
  }
  
  return promptsMap;
}

export const prompts = loadPrompts();