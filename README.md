# Tiger Docs MCP Server

An [MCP server](https://modelcontextprotocol.io/docs/learn/server-concepts) that supercharges AI assistants with deep PostgreSQL, TimescaleDB, and Tiger Cloud knowledge through semantic documentation search and curated prompt templates. 

## Quick Start

Want to use this MCP Server without running it yourself? Use the publicly available endpoint hosted by TigerData! [https://mcp.tigerdata.com/docs](https://mcp.tigerdata.com/docs)

Add the MCP server to Claude Code with this command:

```bash
claude mcp add --transport http tiger-docs https://mcp.tigerdata.com/docs
```

## API

All methods are exposed as MCP tools and REST API endpoints.

### Semantic Search - PostgreSQL Documentation

Searches the PostgreSQL documentation for relevant entries based on semantic similarity to the search prompt.

**MCP Tool**: `semantic_search_postgres_docs`
**REST Endpoint**: `GET /api/semantic-search/postgres-docs`

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
**REST Endpoint**: `GET /api/semantic-search/tiger-docs`

#### Input

```jsonc
{
  "prompt": "How do I set up continuous aggregates?",
  "limit": 10  // optional, default is 10
}
```

#### Output

Same format as PostgreSQL semantic search above.

### Prompt Templates

Retrieves curated prompt templates for common PostgreSQL and TimescaleDB tasks.

**MCP Tool**: `get_guide`

#### Input

```jsonc
{
  "prompt_name": "setup_hypertable"  // see available guides in tool description
}
```

#### Output

```jsonc
{
  "prompt_name": "setup_hypertable",
  "title": "Setup Hypertable",
  "description": "Step-by-step instructions for...",
  "content": "..."  // full guide content
}
```

**Available Prompt Templates**: Check the MCP tool description for the current list of available prompt templates.

## Development

Clone the repo.

```bash
git clone git@github.com:timescale/tiger-docs-mcp-server.git
```

### Configuration

Create a `.env` file based on the `.env.sample` file.

```bash
cp .env.sample .env
```

Add your OPENAI_API_KEY to be used for generating embeddings.

### Run a TimescaleDB Database

You will need a database with the [pgvector extension](https://github.com/pgvector/pgvector).

#### Using Tiger Cloud

Use the [tiger CLI](https://github.com/timescale/tiger-cli) to create a Tiger Cloud service.

```bash
tiger service create --free --with-password -o json
```
Copy your database connection parameters into your .env file.

#### Using Docker

Run the database in a docker container.

```bash
# pull the latest image
docker pull timescale/timescaledb-ha:pg17

# run the database container
docker run -d --name tiger-docs \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=tsdb \
  -e POSTGRES_USER=tsdbadmin \
  -p 127.0.0.1:5432:5432 \
  timescale/timescaledb-ha:pg17
```

Copy your database connection parameters to your .env file:

```dotenv
PGHOST=localhost
PGPORT=5432
PGDATABASE=tsdb
PGUSER=tsdbadmin
PGPASSWORD=password
```

### Building the MCP Server

Run `npm i` to install dependencies and build the project. Use `npm run watch` to rebuild on changes.

### Loading the Database

The database is NOT preloaded with the documentation. To make the MCP server usable, you need to scrape, chunk, embed, load, and index the documentation.
Follow the [directions in the ingest directory](/ingest/README.md) to load the database.

### Testing

The MCP Inspector is a very handy to exercise the MCP server from a web-based UI.

```bash
npm run inspector
```

| Field          | Value           |
| -------------- | --------------- |
| Transport Type | `STDIO`         |
| Command        | `node`          |
| Arguments      | `dist/index.js` |

#### Testing in Claude Desktop

Create/edit the file `~/Library/Application Support/Claude/claude_desktop_config.json` to add an entry like the following, making sure to use the absolute path to your local `tiger-docs-mcp-server` project, and real database credentials.

```json
{
  "mcpServers": {
    "tiger-docs": {
      "command": "node",
      "args": [
        "/absolute/path/to/tiger-docs-mcp-server/dist/index.js",
        "stdio"
      ],
      "env": {
        "PGHOST": "x.y.tsdb.cloud.timescale.com",
        "PGDATABASE": "tsdb",
        "PGPORT": "32467",
        "PGUSER": "readonly_mcp_user",
        "PGPASSWORD": "abc123",
        "DB_SCHEMA": "docs",
        "OPENAI_API_KEY": "sk-svcacct"
      }
    }
  }
}
```
