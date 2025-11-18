import type { McpFeatureFlags } from '@tigerdata/mcp-boilerplate';

export interface FeatureFlags {
  mcpSkillsEnabled: boolean;
}

/**
 * Parse feature flags from query parameters or environment variables
 * Supports both HTTP (?disable_mcp_skills=1) and stdio transport (env var)
 */
export const parseFeatureFlags = (
  query?: McpFeatureFlags['query'],
): FeatureFlags => {
  // Default: skills enabled
  let mcpSkillsEnabled = true;

  // Check query parameters first (for HTTP transport)
  if (query) {
    if (
      query.disable_mcp_skills === '1' ||
      query.disable_mcp_skills === 'true'
    ) {
      mcpSkillsEnabled = false;
    }
  }
  // Fall back to environment variables (for stdio transport)
  else if (process.env.DISABLE_MCP_SKILLS) {
    if (
      process.env.DISABLE_MCP_SKILLS === '1' ||
      process.env.DISABLE_MCP_SKILLS === 'true'
    ) {
      mcpSkillsEnabled = false;
    }
  }

  return {
    mcpSkillsEnabled,
  };
};
