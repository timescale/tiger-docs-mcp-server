import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import { readdir, readFile } from 'fs/promises';
import matter from 'gray-matter';
import { z } from 'zod';
import { log, type PromptFactory } from '@tigerdata/mcp-boilerplate';
import { ServerContext } from '../types.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
// Skills directory at repo root level
const skillsDir = join(__dirname, '..', '..', 'skills');

// ===== Skill Types =====

export const zSkillMatter = z.object({
  name: z.string().trim().min(1),
  description: z.string(),
});
export type SkillMatter = z.infer<typeof zSkillMatter>;

export const zSkill = z.object({
  path: z.string(),
  name: z.string(),
  description: z.string(),
});
export type Skill = z.infer<typeof zSkill>;

// ===== Skill Loading Implementation =====

// Cache for skill content
const skillContentCache: Map<string, string> = new Map();
let skillMapPromise: Promise<Map<string, Skill>> | null = null;

/**
 * Parse a SKILL.md file and validate its metadata
 */
const parseSkillFile = async (
  fileContent: string,
): Promise<{
  matter: SkillMatter;
  content: string;
}> => {
  const { data, content } = matter(fileContent);
  const skillMatter = zSkillMatter.parse(data);

  // Normalize skill name
  if (!/^[a-zA-Z0-9-_]+$/.test(skillMatter.name)) {
    const normalized = skillMatter.name
      .toLowerCase()
      .replace(/\s+/g, '-')
      .replace(/[^a-z0-9-_]/g, '_')
      .replace(/-[-_]+/g, '-')
      .replace(/_[_-]+/g, '_')
      .replace(/(^[-_]+)|([-_]+$)/g, '');
    log.warn(
      `Skill name "${skillMatter.name}" contains invalid characters. Normalizing to "${normalized}".`,
    );
    skillMatter.name = normalized;
  }

  return {
    matter: skillMatter,
    content: content.trim(),
  };
};

/**
 * Load all skills from the filesystem
 */
async function doLoadSkills(): Promise<Map<string, Skill>> {
  const skills = new Map<string, Skill>();
  skillContentCache.clear();

  const alreadyExists = (name: string, path: string): boolean => {
    const existing = skills.get(name);
    if (existing) {
      log.warn(
        `Skill with name "${name}" already loaded from path "${existing.path}". Skipping duplicate at path "${path}".`,
      );
      return true;
    }
    return false;
  };

  const loadLocalPath = async (path: string): Promise<void> => {
    const skillPath = join(path, 'SKILL.md');
    try {
      const fileContent = await readFile(skillPath, 'utf-8');
      const {
        matter: { name, description },
        content,
      } = await parseSkillFile(fileContent);

      if (alreadyExists(name, path)) return;

      skills.set(name, {
        path,
        name,
        description,
      });

      skillContentCache.set(`${name}/SKILL.md`, content);
    } catch (err) {
      log.error(`Failed to load skill at path: ${skillPath}`, err as Error);
    }
  };

  try {
    // Load skills from subdirectories with SKILL.md files
    const dirEntries = await readdir(skillsDir, { withFileTypes: true });
    for (const entry of dirEntries) {
      if (!entry.isDirectory()) continue;
      await loadLocalPath(join(skillsDir, entry.name));
    }

    if (skills.size === 0) {
      log.warn(
        'No skills found. Please add SKILL.md files to the skills/ subdirectories.',
      );
    } else {
      log.info(`Successfully loaded ${skills.size} skill(s)`);
    }
  } catch (err) {
    log.error('Failed to load skills', err as Error);
  }

  return skills;
}

/**
 * Load skills with caching
 */
export const loadSkills = async (
  force = false,
): Promise<Map<string, Skill>> => {
  if (skillMapPromise && !force) {
    return skillMapPromise;
  }

  skillMapPromise = doLoadSkills().catch((err) => {
    log.error('Failed to load skills', err as Error);
    skillMapPromise = null;
    return new Map<string, Skill>();
  });

  return skillMapPromise;
};

/**
 * View skill content
 */
export const viewSkillContent = async (
  name: string,
  targetPath = 'SKILL.md',
): Promise<string> => {
  const skillsMap = await loadSkills();
  const skill = skillsMap.get(name);
  if (!skill) {
    throw new Error(`Skill not found: ${name}`);
  }

  const cacheKey = `${name}/${targetPath}`;
  const cached = skillContentCache.get(cacheKey);
  if (cached) {
    return cached;
  }

  // Read from filesystem
  try {
    const fullPath = join(skill.path, targetPath);
    const content = await readFile(fullPath, 'utf-8');
    skillContentCache.set(cacheKey, content);
    return content;
  } catch {
    throw new Error(`Failed to read skill content: ${name}/${targetPath}`);
  }
};

// Initialize skills on module load
export const skills = await loadSkills();

interface PromptResult {
  [x: string]: unknown;
  description: string;
  messages: {
    role: 'user';
    content: {
      type: 'text';
      text: string;
    };
  }[];
}

// Export skills as prompt factories for MCP server
export const promptFactories: PromptFactory<
  ServerContext,
  Record<string, never>
>[] = Array.from(skills.entries()).map(([name, skillData]) => () => ({
  name,
  config: {
    // Using the dash-separated name as the title to work around a problem in Claude Code
    // See https://github.com/anthropics/claude-code/issues/7464
    title: name,
    description: skillData.description,
    inputSchema: {}, // No arguments for static skills
  },
  fn: async (): Promise<PromptResult> => {
    const content = await viewSkillContent(name);
    return {
      description: skillData.description || name,
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text: content,
          },
        },
      ],
    };
  },
}));
