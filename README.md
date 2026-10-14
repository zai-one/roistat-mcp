🇬🇧 English · [🇷🇺 Русский](README.ru.md)

# Roistat MCP

**Ask what changed between ad spend and sales.**

> MCP server for Roistat end-to-end analytics: channels, ROI/CPL/CPO, period comparison, leads, orders, calls and visits for allowlisted projects, with PII masking.

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

## Why this MCP

- Optional lazy tool loading: set `ROISTAT_TOOL_LOADING=lazy` (or choose it in the setup wizard) to start with a small core and enable toolsets on demand; see [Lazy tool loading](#lazy-tool-loading).
- Project allowlist; phone numbers, emails and visitor IPs are masked in supported responses.
- Writes need `roistat_prepare_write` → operator approval → `roistat_apply_write`; `ROISTAT_READ_ONLY=1` removes them.
- Analytics bundles with exact request parameters and JSON/CSV; missing values stay distinct from zero; Markdown tables for compact replies.
- Other Roistat MCP servers on GitHub ([NatrixAi/roistat-mcp](https://github.com/NatrixAi/roistat-mcp), 16 tools; [theYahia/roistat-mcp](https://github.com/theYahia/roistat-mcp), 6 tools) do not mask personal data.

## Lazy tool loading

Optional lazy tool loading: `ROISTAT_TOOL_LOADING=lazy` starts with a small core plus `roistat_enable_toolsets` and adds toolsets on demand (`tools/list_changed`). Startup cost (tools/list + instructions, ≈chars/4): eager ≈5164 tokens, lazy ≈1435 tokens (−72%). Default `eager` is unchanged; if your client ignores `tools/list_changed`, keep `eager` or reconnect after enabling. Scope: enablement is per MCP session (FastMCP session visibility), so one client's enabled toolsets never appear for another. The HTTP transport here is stateless (every request is its own session), so enabled toolsets do not persist there: for shared HTTP use `eager` or `ROISTAT_TOOLSETS`.

Clients and `notifications/tools/list_changed` (verified against official docs, changelogs or maintainer statements, 2026-10):

| Client | `tools/list_changed` | Source |
|---|---|---|
| Claude Code | Supported (interactive: tools, prompts, resources; `-p`/Agent SDK: tools) | [docs: Dynamic tool updates](https://code.claude.com/docs/en/mcp) |
| VS Code (GitHub Copilot) | Supported (dynamic tool discovery); new tools may reach the agent only on the next turn | [docs](https://code.visualstudio.com/api/extension-guides/ai/mcp), [#303012](https://github.com/microsoft/vscode/issues/303012) |
| Gemini CLI | Supported (refreshes the tool registry) | [PR #14375](https://github.com/google-gemini/gemini-cli/pull/14375), [PR #21050](https://github.com/google-gemini/gemini-cli/pull/21050) |
| Cursor | Unreliable: staff confirm a regression in 3.12.x; restart Cursor after enabling | [forum](https://forum.cursor.com/t/mcp-server-regression-does-not-reload-tools-disconnect-does-nothing-ignores-mcp-json-changes-etc/166216) |
| Claude Desktop, Windsurf, Codex CLI, Cline, Zed, Continue | Unverified: no official statement found; use `eager` or reconnect after enabling | — |

## Maintained and up to date

- Actively maintained by ZAI.ONE: current version 0.5.0; release notes in [CHANGELOG.md](CHANGELOG.md) and [Releases](https://github.com/zai-one/roistat-mcp/releases).
- Built-in update check: ask the assistant to run `roistat_check_update` (public GitHub API, no credentials, cached; nothing is installed automatically; `ROISTAT_DISABLE_UPDATE_CHECK=1` turns it off).
- Follows current MCP practice: tool annotations (read-only / destructive hints), toolsets and read-only mode, server `instructions`, prompts and resources, structured errors with recovery hints, secrets kept out of tool output, a token budget for tool descriptions enforced in tests.
- CI runs the test suite on Linux and Windows for every pull request.

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


<!-- agent-block:start -->
## Install in your agent

Run `roistat-mcp` straight from GitHub with [uv](https://docs.astral.sh/uv/). Pin a release tag (`@vX.Y.Z`) for
reproducible installs; placeholders below are examples, keep secrets in files outside the repo.

**Claude Code**

```bash
claude mcp add roistat --env ROISTAT_API_KEY_FILE=/path/to/roistat.token --env ROISTAT_PROJECT_ALLOWLIST=12345 --env ROISTAT_STATE_PATH=/path/to/roistat.sqlite -- uvx --from git+https://github.com/zai-one/roistat-mcp@v0.5.0 roistat-mcp
```

Skills for Claude Code: copy `skills/*` into `~/.claude/skills/` (or install this repo as a plugin — it
ships `.claude-plugin/plugin.json` with the skills and the MCP server).

**Cursor** — `.cursor/mcp.json` ([one-click install](cursor://anysphere.cursor-deeplink/mcp/install?name=roistat&config=eyJjb21tYW5kIjogInV2eCIsICJhcmdzIjogWyItLWZyb20iLCAiZ2l0K2h0dHBzOi8vZ2l0aHViLmNvbS96YWktb25lL3JvaXN0YXQtbWNwIiwgInJvaXN0YXQtbWNwIl0sICJlbnYiOiB7IlJPSVNUQVRfQVBJX0tFWV9GSUxFIjogIi9wYXRoL3RvL3JvaXN0YXQudG9rZW4iLCAiUk9JU1RBVF9QUk9KRUNUX0FMTE9XTElTVCI6ICIxMjM0NSIsICJST0lTVEFUX1NUQVRFX1BBVEgiOiAiL3BhdGgvdG8vcm9pc3RhdC5zcWxpdGUifX0=)):

```json
{
  "mcpServers": {
    "roistat": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/zai-one/roistat-mcp@v0.5.0",
        "roistat-mcp"
      ],
      "env": {
        "ROISTAT_API_KEY_FILE": "/path/to/roistat.token",
        "ROISTAT_PROJECT_ALLOWLIST": "12345",
        "ROISTAT_STATE_PATH": "/path/to/roistat.sqlite"
      }
    }
  }
}
```

**Codex** — `~/.codex/config.toml` (skills: copy `skills/*` into `~/.codex/skills/`, or keep the
repo's `.agents/skills` link):

```toml
[mcp_servers.roistat]
command = "uvx"
args = ["--from", "git+https://github.com/zai-one/roistat-mcp@v0.5.0", "roistat-mcp"]
env = { ROISTAT_API_KEY_FILE = "/path/to/roistat.token", ROISTAT_PROJECT_ALLOWLIST = "12345", ROISTAT_STATE_PATH = "/path/to/roistat.sqlite" }
```

**Claude Desktop** — `claude_desktop_config.json`: the same `mcpServers` block as Cursor.

## Skills (agent playbooks)

Each skill is a self-contained folder `skills/<name>/` (`SKILL.md` + its own `references/`,
`templates/`); copy the folder and it works. Agents load the short `SKILL.md` only when the task matches
and open the other files on demand. Clients without skills get the same flows as MCP prompts and the
`roistat://playbook` / `roistat://guide/{topic}` resources.

| Skill | What it does |
|---|---|
| `roistat-channel-roi` | ROI, CPL, CPO and revenue by channel with period comparison. |
| `roistat-lead-audit` | Duplicates, untagged leads, unattributed calls, orders without visit chain. |
| `roistat-write-safe` | Order status/import/delete, calltracking scripts/phones, events via prepare, operator acceptance and apply with readback. |

## Toolsets and read-only mode

Default: `meta`, `analytics`, `orders_visits`, `calls`, `settings_write`. Opt-in `extras` (`roistat_extra_read`: calltracking scripts and phone pool, events log, one client's activity feed; PII redacted). `ROISTAT_TOOLSETS=default` (when unset), `all`, or a comma list (see `roistat://toolsets`); `ROISTAT_TOOLS=a,b` adds single tools,
`ROISTAT_DISABLED_TOOLS=a,b` removes them, `ROISTAT_READ_ONLY=1` removes every write/paid tool.

## Example requests

- Какая окупаемость каналов за сентябрь по сравнению с августом?
- Сколько стоит лид в Директе и в SEO?
- Найди дыры в разметке: заявки и звонки без источника.
- Покажи воронку статусов за прошлый месяц.
- Сделай таблицу ROI по кампаниям Яндекс.Директа.
- Смени статус заказа 123 — сначала покажи черновик.
<!-- agent-block:end -->

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
reports `status: unknown` and the server keeps working; after a failure it waits 30 minutes before
asking again. At startup the server refreshes this cache in the background by calling `api.github.com`
(anonymous, at most once a day), including in HTTP deployments. Set `ROISTAT_DISABLE_UPDATE_CHECK=1` to turn it off.

## Built by ZAI.ONE

[ZAI.ONE](https://zai.one) is a digital agency working on websites, SEO, advertising and analytics. We also build tools that connect AI assistants to everyday work. [Talk to us on Telegram](https://t.me/zai_one) about setup, automation or an integration for your team.

## License, use and contributing

- **Use:** you may install and use this MCP server freely for yourself and your organisation, including commercial work. If it helps, please consider giving the repository a ⭐ — appreciated, never required.
- **Contribute:** [issues](https://github.com/zai-one/roistat-mcp/issues/new/choose) and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Never post tokens, cookies, sessions or account data.
- **Not allowed without written permission from ZAI.ONE:** copying code into other projects, forking for redistribution, embedding the server in other products or offering it as a competing service.
- License: [LicenseRef-ZAI-ONE 2.0](LICENSE) (source-available, not open source). Third-party notices and license history: [NOTICE](NOTICE).
