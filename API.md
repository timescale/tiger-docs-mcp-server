# API

All methods are exposed as MCP tools.

## Semantic Search

### `semantic_search_postgres_docs`

Searches the PostgreSQL documentation for relevant entries based on semantic similarity to the search prompt.

**MCP Tool**: `semantic_search_postgres_docs`

#### Input

```jsonc
{
  "prompt": "What is the SQL command to create a table?",
  "version": 17, // optional, default is 17 (supports versions 14-18)
  "limit": 10, // optional, default is 10
}
```

#### Output

```jsonc
{
  "results": [
    {
      "id": 11716,
      "content": "CREATE TABLE ...",
      "metadata": "{...}", // JSON-encoded metadata
      "distance": 0.407, // lower = more relevant
    },
    // ...more results
  ],
}
```

### `semantic_search_tiger_docs`

Searches the TigerData and TimescaleDB documentation using semantic similarity.

**MCP Tool**: `semantic_search_tiger_docs`

#### Input

```jsonc
{
  "prompt": "How do I set up continuous aggregates?",
  "limit": 10, // optional, default is 10
}
```

#### Output

Same format as PostgreSQL semantic search above.

## Skills

### `view_skill`

Retrieves curated skills for common PostgreSQL and TimescaleDB tasks. This tool is disabled
when deploying as a claude plugin (which use [agent skills ](https://www.claude.com/blog/skills) directly).

**MCP Tool**: `view_skill`

### Input

```jsonc
{
  "name": "setup-timescaledb-hypertables", // see available skills in tool description
  "path": "SKILL.md", // optional, defaults to "SKILL.md"
}
```

### Output

```jsonc
{
  "name": "setup-timescaledb-hypertables",
  "path": "SKILL.md",
  "description": "Step-by-step instructions for designing table schemas and setting up TimescaleDB with hypertables, indexes, compression, retention policies, and continuous aggregates.",
  "content": "...", // full skill content
}
```

**Available Skills**: Check the MCP tool description for the current list of available skills or look in the `skills` directory.
