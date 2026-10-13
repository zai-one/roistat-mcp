---
name: roistat-write-safe
description: Safely change Roistat data (order status, import order/client, delete order) - prepare draft, show it, operator acceptance, apply with readback. Use for "смени статус заказа", "импортируй заказ", "Roistat write".
license: LicenseRef-ZAI-ONE
compatibility: Requires roistat-mcp with the settings_write toolset and a local operator who can accept approvals.
metadata:
  service: roistat
---
# Safe Roistat write

## Steps
1. Read current state first (`roistat_get_order`, `roistat_list_order_statuses`).
2. `roistat_prepare_write(operation, project_id, payload)` → returns approval_id + request hash.
   Nothing is sent to Roistat.
3. Show the user exactly what will change (before → after) and the approval_id.
4. The operator accepts it outside MCP:
   `python -m zai_roistat.approvals --state-path ... --account default --approval-id ID --principal SUB
   --request-hash HASH --accept`. The agent never runs this itself.
5. After the user says it is accepted: `roistat_apply_write` with the same operation/project/payload,
   approval_id and an idempotency_key. Report the readback.

## Guardrails
- Drafts expire in 30 minutes; changed payload = new draft.
- `delete_order` is destructive: require an explicit second confirmation.
- Manual cost upload is not supported by this server yet.
- Errors: [references/errors.md](references/errors.md).
