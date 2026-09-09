# Roistat MCP maintenance

Independent owner of the Roistat adapter and MCP tools. Follow the ZAI workspace
task protocol when located there; portable runtime must not depend on that workspace.
Use Python and offline fixtures. Preserve project allowlists, PII redaction,
approval binding, idempotency and readback. Never call live Roistat in tests.
No Git push, publication, real secrets or deployment in this extraction task.

Use Python for scripts. Preserve existing MCP names/schemas and server-owned
authorization, account boundaries, budgets, approvals and unknown-outcome state.
Do not use live provider accounts or credentials in tests. Keep setup local and explicit.
Run scripts/verify.py and scripts/verify_install.py before releases.
Use Issues for requested changes. Preserve LICENSE, NOTICE and third-party licenses.
Never publish operational handoffs, private extraction refs, credentials or runtime state.
Production deployment is a separate action.
When operating in a workspace with a task/verifier protocol, follow that protocol.
