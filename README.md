🇬🇧 English · [🇷🇺 Русский](README.ru.md)

# Roistat MCP

**Ask what changed between ad spend and sales.**

Compare periods, follow a change in lead volume and inspect the orders or calls behind a report. Roistat MCP gives your assistant access to analytics and CRM-linked data from the projects you allow, while masking phone numbers, email addresses and visitor IPs in supported responses.

[Quick start](#quick-start) · [Connect your assistant](#connect-your-assistant) · [Issues](https://github.com/zai-one/roistat-mcp/issues)

Try asking your assistant:

> Compare last week with the previous week for my project: marketing cost, leads, sales and revenue. Separate changes supported by the data from hypotheses that need checking.

## What you can do

| Your task | What the MCP server provides |
|---|---|
| Understand performance | Analytics reports, period comparisons and daily statistics with supported metrics and attribution models. |
| Follow the sales funnel | Orders, statuses, leads and funnel reports for your allowed projects. |
| Check the underlying activity | Calltracking, visits, clients and duplicate-lead reports, with supported personal fields masked. |
| Check setup and spend inputs | Official project-state indicators (CRM sync, counter, analytics rebuild), advertising channels, manually entered channel costs and CRM managers (read-only). |
| Share a traceable report | [Analytics bundles](docs/ANALYTICS_BUNDLE.md): one or two periods, provider totals, attribution, exact request parameters and JSON/CSV. Missing values stay distinct from zero. |

## Quick start

Prefer a ready package? [Install the release and generate your client configuration](INSTALL.md#install-a-release-package). No source checkout is required.

Install **Python 3.12–3.14** and [uv](https://docs.astral.sh/uv/getting-started/installation/). Clone with Git or [download the ZIP](https://github.com/zai-one/roistat-mcp/archive/refs/heads/main.zip). With a ZIP, open the extracted directory and skip the first two commands.

You need a Roistat API key and the IDs of the projects you want to make available. The wizard saves the key locally and configures the project list.

```sh
git clone https://github.com/zai-one/roistat-mcp.git
cd roistat-mcp
uv sync --frozen
uv run --frozen python scripts/configure.py
uv run --frozen roistat-mcp --config mcp.local.json --check-config
```

The wizard creates a local configuration and stores secrets in private files. It refuses to overwrite an existing setup. `--check-config` validates local settings; the first request below checks your account connection.

## Connect your assistant

Add this configuration to an MCP client that uses `mcpServers`, such as Claude Desktop or Cursor. Replace `/ABSOLUTE/PATH/` with your absolute path; Windows JSON paths can use forward slashes, such as `D:/Tools/`.

```json
{
  "mcpServers": {
    "roistat": {
      "command": "uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/roistat-mcp",
        "run",
        "--frozen",
        "roistat-mcp",
        "--config",
        "/ABSOLUTE/PATH/roistat-mcp/mcp.local.json"
      ]
    }
  }
}
```

The client starts the MCP server for you. Refresh its tool list, then make your first request. For clients with a different config format, reuse the same `command` and `args`; `uv` must be available to the client process.

### First request

> List the available Roistat projects and the metrics supported for an analytics report. Ask me which project to use.

You should see projects accessible to your API key and the supported report catalogue. Select a project from the server allowlist before asking for a report; an empty or partial response is not proof of zero activity.

If tools do not appear, check the absolute path, whether the client can find `uv`, and the `--check-config` result. For access errors, check account credentials and permissions. [Installation and troubleshooting](INSTALL.md).

## Access and limits

Choose the same attribution model when comparing periods. Custom-metric discovery does not make every metric queryable: the report tool uses a defined metric list. Changes to Roistat data need separate configuration and approval.

Authenticated HTTP is available for a server deployment. See [HTTP setup](INSTALL.md#http), [configuration and permissions](docs/RUNTIME.md) and [Python package integration](INSTALL.md#python-package-and-platform-integration).

<details>
<summary>For developers: project checks</summary>

```sh
uv sync --frozen --all-groups
uv run --frozen python scripts/verify.py
uv run --frozen python scripts/verify_install.py
```

Tests use synthetic fixtures. A passing test run does not establish live provider connectivity.

</details>

## Updates

Ask your assistant to run `roistat_check_update`. It compares the installed version with the
[latest release](https://github.com/zai-one/roistat-mcp/releases) through the public GitHub API
(no credentials, 3-second timeout, result cached for 24 hours next to the state file) and returns
the current and latest versions, the release notes link and the matching update command
(`git pull --ff-only && uv sync --frozen` for a checkout, `uv tool install --force ...` for a release package).
When a newer version is already known from the cache, the server mentions it once in its startup
instructions and in `roistat_health`. Nothing is ever installed automatically. Offline, the check
reports `status: unknown` and the server keeps working. Set `ROISTAT_DISABLE_UPDATE_CHECK=1` to turn it off.

## Built by ZAI.ONE

[ZAI.ONE](https://zai.one) is a digital agency working on websites, SEO, advertising and analytics. We also build tools that connect AI assistants to everyday work. [Talk to us on Telegram](https://t.me/zai_one) about setup, automation or an integration for your team.

## Use and feedback

You may install and use this project for your own accounts under [LicenseRef-ZAI-ONE](LICENSE).
This is not an open-source license. Third-party notices remain in [NOTICE](NOTICE).
If it helps, give the repository a ⭐. Missing something or found a bug? [Open an issue](https://github.com/zai-one/roistat-mcp/issues/new/choose).
I'm working on this project; accepted improvements are implemented here. Support is not guaranteed.
