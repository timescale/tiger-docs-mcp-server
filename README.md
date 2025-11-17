# pg-aiguide 

pg-aiguide helps AI coding tools write better code. It supercharges AI assistants with deep PostgreSQL knowledge by providing:

- Comprehensive documentation search for the PostgreSQL manual.
- Specialized skills that are opinionated AI-optimized guides on how to write good Postgres code. See this [blog post](https://www.tigerdata.com/blog/free-postgres-mcp-prompt-templates) for more information.

Both documentation and skills can be deployed either as a an [MCP server](https://modelcontextprotocol.io/docs/learn/server-concepts)
or a [claude plugin](https://www.claude.com/blog/claude-code-plugins). The claude plugin exposed skills through it's native [agent skills support](https://www.claude.com/blog/skills). For other editors we expose skills through mcp tools that AI coding agents can detect and use automatically.

## Quick Start

Want to use this MCP Server without running it yourself? Use the publicly available endpoint hosted by TigerData! [https://mcp.tigerdata.com/docs](https://mcp.tigerdata.com/docs)

**Claude Code** installation: 

This repo serves as a claude code marketplace plugin. To install, run:

```bash
claude plugin marketplace install timescale/pg-aiguide
claude plugin install pg-aiguide@pg-aiguide
```

This plugin uses the skills available in the `skills` directory as well as our
publicly available MCP server endpoint hosted by TigerData for searching PostgreSQL documentation.


**Publicly available MCP Server**

This is the publicly available MCP server endpoint hosted by TigerData. It exposes both the skills and PostgreSQL documentation
search capabilities through MCP tools. This can be used by Cursor, Windsurf, Codex, or any other agent that [supports MCP](https://modelcontextprotocol.io/clients).

```
https://mcp.tigerdata.com/docs
```

**Cursor** installation:

```bash
// .cursor/mcp.json
{
  "mcpServers": {
    "tiger-docs": {
      "url": "https://mcp.tigerdata.com/docs"
    }
  }
}
```

## API

All methods are exposed as MCP tools.

### Semantic Search - PostgreSQL Documentation

Searches the PostgreSQL documentation for relevant entries based on semantic similarity to the search prompt.

**MCP Tool**: `semantic_search_postgres_docs`

#### Input

```jsonc
{
  "prompt": "What is the SQL command to create a table?",
  "version": 17,  // optional, default is 17 (supports versions 14-18)
  "limit": 10     // optional, default is 10
}
```

#### Output

```jsonc
{
  "results": [
    {
      "id": 11716,
      "content": "CREATE TABLE ...",
      "metadata": "{...}",  // JSON-encoded metadata
      "distance": 0.407     // lower = more relevant
    }
    // ...more results
  ]
}
```

### Semantic Search - Tiger Docs

Searches the TigerData and TimescaleDB documentation using semantic similarity.

**MCP Tool**: `semantic_search_tiger_docs`

#### Input

```jsonc
{
  "prompt": "How do I set up continuous aggregates?",
  "limit": 10  // optional, default is 10
}
```

#### Output

Same format as PostgreSQL semantic search above.

### Skills

Retrieves curated skills for common PostgreSQL and TimescaleDB tasks. This tool is disabled
when deploying as a claude plugin (which use [agent skills ](https://www.claude.com/blog/skills) directly).

**MCP Tool**: `view_skill`

#### Input

```jsonc
{
  "name": "setup-timescaledb-hypertables",  // see available skills in tool description
  "path": "SKILL.md"  // optional, defaults to "SKILL.md"
}
```

#### Output

```jsonc
{
  "name": "setup-timescaledb-hypertables",
  "path": "SKILL.md",
  "description": "Step-by-step instructions for designing table schemas and setting up TimescaleDB with hypertables, indexes, compression, retention policies, and continuous aggregates.",
  "content": "..."  // full skill content
}
```

**Available Skills**: Check the MCP tool description for the current list of available skills or look in the `skills` directory.

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed development instructions.
