# Tiger Docs MCP Server

A wrapper around our `slack-db` database, which contains embedded PostgreSQL documentation. This provides some focused tools to LLMs via the [Model Context Protocol](https://modelcontextprotocol.io/introduction).

See [slack-db](https://github.com/timescale/slack-db/) for details on how the database is populated.

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
git clone --recurse-submodules git@github.com:timescale/tiger-docs-mcp-server.git
```

### Submodules

This project uses git submodules to include the mcp boilerplate code. If you cloned the repo without the `--recurse-submodules` flag, run the following command to initialize and update the submodules:

```bash
git submodule update --init --recursive
```

You may also need to run this command if you pull changes that update a submodule. You can simplify this process by changing you git configuration to automatically update submodules when you pull:

```bash
git config --global submodule.recurse true
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

We use a Helm chart to deploy to Kubernetes. See the `chart/` directory for details.

The service is accessible to other services in the cluster via the DNS name `tiger-docs-mcp-server.savannah-system.svc.cluster.local`.

### Secrets

Run the following to create the necessary sealed secrets. Be sure to fill in the correct values.

```bash
kubectl -n savannah-system create secret generic tiger-docs-mcp-server-database \
  --dry-run=client \
  --from-literal=user="readonly_mcp_user" \
  --from-literal=password="abv123" \
  --from-literal=database="tsdb" \
  --from-literal=host="x.y.tsdb.cloud.timescale.com" \
  --from-literal=port="32467" \
  -o yaml | kubeseal -o yaml

kubectl -n savannah-system create secret generic tiger-docs-mcp-server-openai \
  --dry-run=client \
  --from-literal=apiKey="sk-svcacct" \
  -o yaml | kubeseal -o yaml

kubectl -n savannah-system create secret generic tiger-docs-mcp-server-logfire \
  --dry-run=client \
  --from-literal=token="pylf_v1_us_" \
  -o yaml | kubeseal -o yaml
```

Update `./chart/values/dev.yaml` with the output.
