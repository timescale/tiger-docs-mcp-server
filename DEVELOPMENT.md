# Development Guide

## Getting Started

Clone the repo.

```bash
git clone git@github.com:timescale/pg-aiguide.git
```

## Configuration

Create a `.env` file based on the `.env.sample` file.

```bash
cp .env.sample .env
```

Add your OPENAI_API_KEY to be used for generating embeddings.

### Configuration Parameters

The server supports disabling MCP skills through different mechanisms for each transport:

#### HTTP Transport

Pass parameters as query strings:

```
https://mcp.tigerdata.com/docs?disable_mcp_skills=1
```

#### Stdio Transport

Use environment variables in the connection configuration:

```json
{
  "mcpServers": {
    "pg-aiguide": {
      "command": "node",
      "args": ["/path/to/dist/index.js", "stdio"],
      "env": {
        "DISABLE_MCP_SKILLS": "1"
      }
    }
  }
}
```

Or when running directly:

```bash
DISABLE_MCP_SKILLS=1 node dist/index.js stdio
```

#### Available Parameters

| Parameter          | HTTP Query           | Stdio Env Var        | Values    | Description                                                                                                                                                   |
| ------------------ | -------------------- | -------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Disable MCP Skills | `disable_mcp_skills` | `DISABLE_MCP_SKILLS` | 1 or true | Disable all MCP skills (tools and prompt templates). This removes the `view_skill` tool and all skill-based prompt templates from the available capabilities. |

**Examples:**

- HTTP: `?disable_mcp_skills=1`
- Stdio: `DISABLE_MCP_SKILLS=1`
- Default (skills enabled): No parameter needed

## Run a TimescaleDB Database

You will need a database with the [pgvector extension](https://github.com/pgvector/pgvector).

### Using Tiger Cloud

Use the [tiger CLI](https://github.com/timescale/tiger-cli) to create a Tiger Cloud service.

```bash
tiger service create --free --with-password -o json
```

Copy your database connection parameters into your .env file.

### Using Docker

Run the database in a docker container.

```bash
# pull the latest image
docker pull timescale/timescaledb-ha:pg17

# run the database container
docker run -d --name pg-aiguide \
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

## Building the MCP Server

Run `npm i` to install dependencies and build the project. Use `npm run watch` to rebuild on changes.

## Loading the Database

The database is NOT preloaded with the documentation. To make the MCP server usable, you need to scrape, chunk, embed, load, and index the documentation.
Follow the [directions in the ingest directory](/ingest/README.md) to load the database.

## Testing

The MCP Inspector is a very handy to exercise the MCP server from a web-based UI.

```bash
npm run inspector
```

| Field          | Value           |
| -------------- | --------------- |
| Transport Type | `STDIO`         |
| Command        | `node`          |
| Arguments      | `dist/index.js` |

### Testing in Claude Desktop

Create/edit the file `~/Library/Application Support/Claude/claude_desktop_config.json` to add an entry like the following, making sure to use the absolute path to your local `pg-aiguide` project, and real database credentials.

```json
{
  "mcpServers": {
    "pg-aiguide": {
      "command": "node",
      "args": ["/absolute/path/to/pg-aiguide/dist/index.js", "stdio"],
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
