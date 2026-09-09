🇬🇧 English · [🇷🇺 Русский](README.ru.md)

# Roistat MCP

MCP server for Roistat analytics. Retrieve reports, compare periods and inspect orders, leads, calls and sales funnels from an AI assistant.

## What you can do

- Build analytics reports, compare periods and retrieve daily statistics.
- Read orders, leads, calls, visits, clients and funnel data from allowed projects.
- Discover dimension values and custom metrics when preparing a report.

## Quick start

Install Python 3.12+ (below 3.15), [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git.

You need a Roistat API key and the IDs of the projects you want to make available. The wizard saves the key locally and configures the project list.

```sh
git clone https://github.com/zai-one/roistat-mcp.git
cd roistat-mcp
uv sync --frozen
uv run --frozen python scripts/configure.py
uv run --frozen roistat-mcp --config mcp.local.json --check-config
uv run --frozen roistat-mcp --config mcp.local.json
```

The last command starts stdio and waits for an MCP client; it is not an interactive chat.
See [INSTALL.md](INSTALL.md) for credentials, client configuration, HTTP and package integration.
`--check-config` checks local settings only; it never validates a provider account over the network.

## Scope and limits

Report metrics are restricted to the supported list; discovering a custom metric does not automatically enable it in reports. Supported write operations require separate configuration and approval. See [access and write settings](docs/RUNTIME.md).

## Verification

```sh
uv sync --frozen --all-groups
uv run --frozen python scripts/verify.py
uv run --frozen python scripts/verify_install.py
```

Tests use synthetic fixtures. A passing test run does not establish live provider connectivity.

## Use and feedback

You may install and use this project for your own accounts under [LicenseRef-ZAI-ONE](LICENSE).
This is not an open-source license. Third-party notices remain in [NOTICE](NOTICE).
If it helps, give the repository a ⭐. Missing something or found a bug? [Open an issue](https://github.com/zai-one/roistat-mcp/issues/new/choose).
I'm working on this project; accepted improvements are implemented here. Support is not guaranteed.
