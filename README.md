# pg-aiguide

**AI-optimized PostgreSQL expertise for coding assistants**

pg-aiguide helps AI coding tools write dramatically better PostgreSQL code. It provides:

- **Semantic search** across the official PostgreSQL manual (version-aware)
- **AI-optimized “skills”** — curated, opinionated Postgres best practices used automatically by AI agents
- **Extension ecosystem docs**, starting with TimescaleDB, with more coming soon

Use it either as:

- a **public MCP server** that can be used with any AI coding agent, or
- a **Claude Code plugin** optimized for use with Claude's native skill support.

## ⭐ Why pg-aiguide?

AI coding tools often generate Postgres code that is:

- outdated
- missing constraints and indexes
- unaware of modern PG features
- inconsistent with real-world best practices

pg-aiguide fixes that by giving AI agents deep, versioned PostgreSQL knowledge and proven patterns.

### See the difference

https://github.com/user-attachments/assets/5a426381-09b5-4635-9050-f55422253a3d

<details>
<summary>Video Transcript </summary>

Prompt given to Claude Code:

> Please describe the schema you would create for an e-commerce website two times, first with the tiger mcp server disabled, then with the tiger mcp server enabled. For each time, write the schema to its own file in the current working directory. Then compare the two files and let me know which approach generated the better schema, using both qualitative and quantitative reasons. For this example, only use standard Postgres.

Result (summarized):

- **4× more constraints**
- **55% more indexes** (including partial/expression indexes)
- **PG17-recommended patterns**
- **Modern features** (`GENERATED ALWAYS AS IDENTITY`, `NULLS NOT DISTINCT`)
- **Cleaner naming & documentation**

Conclusion: _pg-aiguide produces more robust, performant, maintainable schemas._

</details>

## 🚀 Quickstart

pg-aiguide is available as a **public MCP server**:

[https://mcp.tigerdata.com/docs](https://mcp.tigerdata.com/docs)

<details> 
<summary>Manual MCP configuration using JSON</summary>

```json
{
  "mcpServers": {
    "pg-aiguide": {
      "url": "https://mcp.tigerdata.com/docs"
    }
  }
}
```

</details>

Or it can be used as a **Claude Code Plugin**:

```bash
claude plugin marketplace add timescale/pg-aiguide
claude plugin install pg@aiguide
```

### Install by environment

#### One-click installs

[![Install in Cursor](https://img.shields.io/badge/Install_in-Cursor-000000?style=flat-square&logoColor=white)](https://cursor.com/en/install-mcp?name=pg-aiguide&config=eyJuYW1lIjoicGctYWlndWlkZSIsInR5cGUiOiJodHRwIiwidXJsIjoiaHR0cHM6Ly9tY3AudGlnZXJkYXRhLmNvbS9kb2NzIn0=)
[![Install in VS Code](https://img.shields.io/badge/Install_in-VS_Code-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=pg-aiguide&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcp.tigerdata.com%2Fdocs%22%7D)
[![Install in VS Code Insiders](https://img.shields.io/badge/Install_in-VS_Code_Insiders-24bfa5?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=pg-aiguide&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcp.tigerdata.com%2Fdocs%22%7D&quality=insiders)
[![Install in Visual Studio](https://img.shields.io/badge/Install_in-Visual_Studio-C16FDE?style=flat-square&logo=visualstudio&logoColor=white)](https://vs-open.link/mcp-install?%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcp.tigerdata.com%2Fdocs%22%7D)
[![Install in Goose](https://block.github.io/goose/img/extension-install-dark.svg)](https://block.github.io/goose/extension?cmd=&arg=&id=pg-aiguide&name=pg-aiguide&description=MCP%20Server%20for%20pg-aiguide)
[![Add MCP Server pg-aiguide to LM Studio](https://files.lmstudio.ai/deeplink/mcp-install-light.svg)](https://lmstudio.ai/install-mcp?name=pg-aiguide&config=eyJuYW1lIjoicGctYWlndWlkZSIsInR5cGUiOiJodHRwIiwidXJsIjoiaHR0cHM6Ly9tY3AudGlnZXJkYXRhLmNvbS9kb2NzIn0=)

<details>
<summary>Claude Code</summary>

This repo serves as a claude code marketplace plugin. To install, run:

```bash
claude plugin marketplace add timescale/pg-aiguide
claude plugin install pg@aiguide
```

This plugin uses the skills available in the `skills` directory as well as our
publicly available MCP server endpoint hosted by TigerData for searching PostgreSQL documentation.

</details>

<details>
<summary> Codex </summary>

Run the following to add the MCP server to codex:

```bash
codex mcp add --url "https://mcp.tigerdata.com/docs" pg-aiguide
```

</details>

<details>
<summary> Cursor </summary>

One-click install:

[![Install MCP Server](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en-US/install-mcp?name=pg-aiguide&config=eyJ1cmwiOiJodHRwczovL21jcC50aWdlcmRhdGEuY29tL2RvY3MifQ%3D%3D)

Or add the following to `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "pg-aiguide": {
      "url": "https://mcp.tigerdata.com/docs"
    }
  }
}
```

</details>

<details>
<summary> Gemini CLI </summary>

Run the following to add the MCP server to Gemini CLI:

```bash
gemini mcp add -s user pg-aiguide "https://mcp.tigerdata.com/docs" -t http
```

</details>

<details>
<summary> Visual Studio </summary>

Click the button to install:

[![Install in Visual Studio](https://img.shields.io/badge/Install_in-Visual_Studio-C16FDE?style=flat-square&logo=visualstudio&logoColor=white)](https://vs-open.link/mcp-install?%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcp.tigerdata.com%2Fdocs%22%7D)

</details>

<details>
<summary> VS Code </summary>

Click the button to install:

[![Install in VS Code](https://img.shields.io/badge/Install_in-VS_Code-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=pg-aiguide&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcp.tigerdata.com%2Fdocs%22%7D)

Alternatively, run the following to add the MCP server to VS Code:

```bash
code --add-mcp '{"name":"pg-aiguide","type":"http","url":"https://mcp.tigerdata.com/docs"}'
```

</details>

<details>
<summary> VS Code Insiders </summary>

Click the button to install:

[![Install in VS Code Insiders](https://img.shields.io/badge/Install_in-VS_Code_Insiders-24bfa5?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=pg-aiguide&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcp.tigerdata.com%2Fdocs%22%7D&quality=insiders)

Alternatively, run the following to add the MCP server to VS Code Insiders:

```bash
code-insiders --add-mcp '{"name":"pg-aiguide","type":"http","url":"https://mcp.tigerdata.com/docs"}'
```

</details>

<details>
<summary> Windsurf </summary>

Add the following to `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "pg-aiguide": {
      "serverUrl": "https://mcp.tigerdata.com/docs"
    }
  }
}
```

</details>

### 💡 Your First Prompt

Once installed, pg-aiguide can answer Postgres questions or design schemas.

**Simple schema example prompt**

> Create a Postgres table schema for storing usernames and unique email addresses.

**Complex schema example prompt**

> You are a senior software engineer. You are given a task to generate a Postgres schema for an IoT device company.
> The devices collect environmental data on a factory floor. The data includes temperature, humidity, pressure, as
> the main data points as well as other measurements that vary from device to device. Each device has a unique id
> and a human-readable name. We want to record the time the data was collected as well. Analysis for recent data
> includes finding outliers and anomalies based on measurements, as well as analyzing the data of particular devices for ad-hoc analysis. Historical data analysis includes analyzing the history of data for one device or getting statistics for all devices over long periods of time.

## Features

### Semantic Search (MCP Tools)

- [**`semantic_search_postgres_docs`**](API.md#semantic_search_postgres_docs)  
  Performs semantic search over the official PostgreSQL manual, with results scoped to a specific Postgres version.

- [**`semantic_search_tiger_docs`** ](API.md#semantic_search_tiger_docs)
  Searches Tiger Data’s documentation corpus, including TimescaleDB and future ecosystem extensions.

### Skills (AI-Optimized Best Practices)

- **[`view_skill`](API.md#view_skill)**  
  Exposes curated, opinionated PostgreSQL best-practice skills used automatically by AI coding assistants.

  These skills provide guidance on:
  - Schema design
  - Indexing strategies
  - Data types
  - Data integrity and constraints
  - Naming conventions
  - Performance tuning
  - Modern PostgreSQL features

## 🔌 Ecosystem Documentation

Supported today:

- **TimescaleDB** (docs + skills)

Coming soon:

- **pgvector**
- **PostGIS**

We welcome contributions for additional extensions and tools.

## 🛠 Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for:

- running the MCP server locally
- adding new skills
- adding new docs

## 🤝 Contributing

We welcome:

- new Postgres best-practice skills
- additional documentation corpora
- search quality improvements
- bug reports and feature ideas

## 📄 License

Apache 2.0
