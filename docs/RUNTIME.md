# Roistat MCP

Independent Roistat MCP service with 20 read tools and two governed write tools.
The real REST adapter and original tool contracts come from the committed
development baseline in `SOURCE_PROVENANCE.json`. No AI Kit, platform package
or local ZAI paths are needed to install or run it. Install and configure it for your own accounts.

Install Python 3.12–3.14 and uv, then run:

```sh
uv sync --frozen --all-groups
uv run python scripts/verify.py
uv build
```

To install the built package elsewhere:

```sh
python -m pip install dist/zai_roistat_mcp-0.5.0-py3-none-any.whl
python -m zai_roistat --transport stdio
```

Set `ROISTAT_API_KEY_FILE` to a private file containing your API key, and
`ROISTAT_STATE_PATH` to a persistent SQLite file. The stdio process represents
`ROISTAT_LOCAL_PRINCIPAL` (default `local-operator`). Keep stdout for MCP.
See `.env.example` for the complete configuration; no key is included.

For HTTP, supply `ROISTAT_MCP_PUBLIC_KEY_FILE` with an RSA public verification
key and start `python -m zai_roistat --transport http --host 127.0.0.1 --port 8813`.
Tokens must use RS256, issuer `roistat-operator`, audience `roistat-mcp`, a
nonempty `sub`, future `exp` and `account_id` matching `ROISTAT_ACCOUNT_ID`.
Scopes are `roistat:read` and `roistat:write`; client arguments cannot widen them.
Use an authenticated TLS ingress when exposing HTTP outside the local host.

Update check: unless `ROISTAT_DISABLE_UPDATE_CHECK=1` is set, the server calls
`api.github.com` (anonymous, at most once a day) in the background at startup to
see whether a newer release exists; this also applies to HTTP/server deployments,
so disable it where outbound requests are not wanted. `roistat_check_update`
performs the same check on request. Results are cached in `update-check.json`
next to the state file. Every attempt is recorded there: after a failed request
no new request is made for 30 minutes, and `force=true` is honoured at most once
a minute. Only plain version tags (`v1.2.3`) are accepted. Nothing is installed
automatically.

Reads cover projects, capabilities, health, analytics, statistics, orders,
leads, calls, visits, clients and funnels. Exact names and input/output schemas
are in `contracts/roistat.json`. Source limitations and capability evidence are
preserved in `docs/ROISTAT_API_CAPABILITY_MATRIX.md`; those upstream observations
have not been refreshed as part of this local extraction.

Writes default to disabled. Enable `ROISTAT_WRITE_ENABLED=true` and configure
`ROISTAT_PROJECT_ALLOWLIST` before writing. Unset `ROISTAT_WRITE_OPERATIONS` enables
only the original four operations: update_order_status, import_order, import_client and
delete_order. Name the others there explicitly to enable them:
calltracking_script_create/update/delete, calltracking_phone_create/update/delete,
events_send, events_bulk_send and events_add. Deletes act on one object and require
confirm_delete. Phone purchase is not in the public API and stays unsupported.
Batch delete and advertising-platform or CRM-integration creation/deletion remain denied.

The write workflow is:

1. Call `roistat_prepare_write` with operation, project_id and payload. It creates
   an unaccepted 30-minute draft and returns its approval ID and request hash.
2. After reviewing those exact inputs, the trusted local operator accepts it:

```sh
python -m zai_roistat.approvals --state-path state/roistat.sqlite --account default \
  --approval-id APPROVAL_UUID --principal CALLER_SUB --request-hash RETURNED_HASH --accept
```

3. Call `roistat_apply_write` with the same inputs, approval_id and idempotency_key.

Acceptance is intentionally outside the MCP tool surface. The local CLI is a
filesystem administration boundary, so MCP clients must not have shell/file access
to that state file. Approval is bound to account, caller, operation and payload;
acceptance and consumption are recorded. Another caller cannot reuse the approval.
Platform embedding uses the existing central approval UI/API and ledger instead.

The SQLite file retains per-attempt admission, cooldown, metadata audit,
approvals and sanitized write results. Each actual HTTP attempt, including
retries and readbacks, counts against account caps: 5/second, 30/minute,
600/hour, concurrency 1; get-daily has a separate 3/hour account cap. Principal
limits may only reduce the minute cap. These durable account caps are at least
as restrictive as the extracted per-project in-memory limits. Keep a single
state file for each account; separate replica files do not provide a shared limit.

Successful writes return a readback and can be retrieved with the same key
after restart. A timeout, cancellation or readback error leaves `pending` state:
there is no automatic expiry or blind retry of an uncertain write. Reconcile
the exact upstream object before any new approval or key. Preserve the state
file during rollback. Health drift snapshots are process-local diagnostics.

The platform can embed `zai_roistat.tools.register_tools` from this exact package
with a host runtime supplying its registry, scopes, approval record/store,
current access, safe errors, read and write functions. The candidate's bridge
preserves central retry admission and internal adapter error handling. Standalone
SQLite is not used in that execution path. See the platform's integration document
for its pinned artifact workflow. Production is not switched by installing this repo.

The release CI verifies Python packages and the Docker build. See the workflow
status for the exact commit. Live provider validation remains an operator step.
