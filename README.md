# Tiger Docs MCP Server

A collection of tools to ingest the PostgreSQL and TigerData documentation into a database, chunk and generate vector embeddings, and provide a set of semantic search tools via the [Model Context Protocol](https://modelcontextprotocol.io/introduction). In addition, we have included some helpful development guides. These can be consumed by an LLM to better answer questions about PostgreSQL, TimescaleDB, and Tiger Cloud, with links to the relevant documentation. This also improves its ability to generate correct SQL queries.

## API

All methods are exposed as MCP tools and REST API endpoints.

### Postgres Docs Semantic Search

Searches the PostgreSQL documentation for relevant entries based on a semantic embedding of the search prompt.

**Tool name**
: `semanticSearchPostgresDocs`

**API endpoint**
: `GET /api/semantic-search/postgres-docs`

#### Input

(use query parameters for REST API)

```jsonc
{
  "prompt": "What is the SQL command to create a table?",
  "version": 17, // optional, default is 17
  "limit": 10, // optional, default is 10
}
```

#### Output

```jsonc
{
  "results": [
    {
      "id": 11716,
      "headerPath": ["The SQL Language", "Creating a New Table"],
      "content": "CREATE TABLE ...",
      "tokenCount": 595,
      "distance": 0.40739564321624144,
    },
    // more results...
  ],
}
```

(the REST API returns a JSON array, just the content of the `results` field above)

## Development

Cloning and running the server locally.

```bash
git clone git@github.com:timescale/tiger-docs-mcp-server.git
```

### Building

Run `npm i` to install dependencies and build the project. Use `npm run watch` to rebuild on changes.

Create a `.env` file based on the `.env.sample` file.

```bash
cp .env.sample .env
```

### Testing

The MCP Inspector is very handy.

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
        "OPENAI_API_KEY": "sk-svcacct"
      }
    }
  }
}
```

## Deployment

See [here](https://github.com/timescale/tiger-agents-deploy/tree/main/charts/tiger-docs-mcp-server) for our deployment setup.
