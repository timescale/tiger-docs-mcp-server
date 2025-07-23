# Tiger Docs MCP Server

A wrapper around our `slack-db` database, which contains embedded PostgreSQL documentation. This provides some focused tools to LLMs via the [Model Context Protocol](https://modelcontextprotocol.io/introduction).

See [slack-db](https://github.com/timescale/slack-db/) for details on how the database is populated.

## Development

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
```

Update `./chart/values/dev.yaml` with the output.
