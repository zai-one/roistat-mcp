# Roistat API capability matrix

Evidence is limited to official Roistat help pages. Interface how-tos,
unofficial blogs and the hosted MCP prompt text are not treated as REST write
proof. The official hosted MCP at `https://mcp.roistat.com/mcp` is documented
as a read-only assistant connector; this platform does **not** proxy it.

Status values:

| Status | Meaning |
| --- | --- |
| `official_mcp_read` | Official MCP article describes a read scenario (analytics, orders, leads, calls). Not a REST contract. |
| `verified_rest_read` | Official REST page documents method, URL, auth and response. |
| `verified_rest_write` | Official REST page documents a mutating method and URL. |
| `unsupported_by_official_api` | No official REST method found; UI-only or hosted-MCP-only. |
| `unknown_needs_live_discovery` | Official page exists but live field/shape still needs a canary. |

Risk uses the platform vocabulary: `low` (read), `medium` (reversible single-object write), `high` (destructive or paid).

Readback is the official method used to confirm state after a write. `n/a` means the capability is read-only or not executable here.

## Sources

- [Roistat MCP](https://help-ru.roistat.com/API/mcp/) and [MCP product article](https://help-ru.roistat.com/features/Roistat_MCP_dlya_AI_assistentov/)
- [REST API overview, auth, limits](https://help-ru.roistat.com/API/methods/about/)
- [Projects](https://help-ru.roistat.com/API/methods/projects/)
- [Analytics](https://help-ru.roistat.com/API/methods/analytics/)
- [Statistics](https://help-ru.roistat.com/API/methods/statystics/)
- [Orders / deals](https://help-ru.roistat.com/API/methods/orders/)
- [Proxy leads](https://help-ru.roistat.com/API/methods/proxy-leads/)
- [Clients](https://help-ru.roistat.com/API/methods/clients/)
- [Calltracking](https://help-ru.roistat.com/API/methods/calltracking/)
- [Visits](https://help-ru.roistat.com/API/methods/visit/)

## Official transport and limits

| Fact | Evidence | Platform decision |
| --- | --- | --- |
| Base URL `https://cloud.roistat.com/api/v1` | about | Fixed HTTPS host allowlist; HTTP and other hosts rejected |
| Auth: header `Api-key` (recommended) or `key` query | about | Header only. Query-string key is never sent |
| Project id in `project=` query except `/user/projects` and `/account/project/create` | about, projects | Enforced per operation |
| Default HTTP 200 even on errors; `Use-Http-Code: 1` returns 400/401/403/429/5xx | about | Adapter always sends `Use-Http-Code: 1` and still inspects `status` |
| 10 req/s, 100 req/min, 5000 req/hour per project | about | Governor 30/min, concurrency 1; adapter 5/s, 30/min, 600/hour fail-closed |
| `statistics/get-daily` extra 5 req/hour | statistics | Adapter extra cap 3/hour |
| Official MCP `https://mcp.roistat.com/mcp` is read-only | MCP articles | Not installed, not proxied |

## Matrix

| Entity | Official endpoint | Platform tool | R/W | Risk | Readback | Evidence status | v1 surface |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Hosted MCP connector | `https://mcp.roistat.com/mcp` | none | read | low | n/a | `official_mcp_read` | closed; do not install |
| Projects | `GET /user/projects` | `roistat_list_projects` | read | low | n/a | `verified_rest_read` | enabled |
| Project create | `POST /account/project/create` | rejected | write | high | `GET /user/projects` | `verified_rest_write` | closed (billing/new project) |
| Counter code | `POST /project/settings/module/list` | none | read | low | n/a | `verified_rest_read` | not exposed (JS snippet) |
| Analytics catalog | `POST /project/analytics/metrics-new` | `roistat_analytics_catalog` | read | low | n/a | `verified_rest_read` | enabled |
| Analytics dimensions | `POST /project/analytics/dimensions` | `roistat_analytics_catalog` | read | low | n/a | `verified_rest_read` | enabled |
| Attribution models | `POST /project/analytics/attribution-models` | `roistat_analytics_catalog` | read | low | n/a | `verified_rest_read` | enabled |
| Analytics report | `POST /project/analytics/data` | `roistat_analytics_report`, `roistat_analytics_compare` | read | low | n/a | `verified_rest_read` + `official_mcp_read` | enabled; metrics/dimensions allowlisted |
| Analytics Excel export | `POST /project/analytics/data/export/excel` | none | read | low | n/a | `verified_rest_read` | closed (binary) |
| Dimension values | `POST /project/analytics/dimension-values` | none | read | low | n/a | `verified_rest_read` | not in v1 |
| Analytics orders slice | `POST /project/analytics/list-orders` | none | read | low | n/a | `verified_rest_read` | use `roistat_list_orders` |
| Custom metric list | `GET /project/analytics/metrics/custom/list` | none | read | low | n/a | `verified_rest_read` | not in v1 |
| Custom metric values | `POST /project/analytics/metrics/custom/manual/value/list` | none | read | low | n/a | `verified_rest_read` | not in v1 |
| Custom metric add | `POST /project/analytics/metrics/custom/manual/value/add` | rejected | write | medium | value/list | `verified_rest_write` | closed |
| Custom metric delete | `POST /project/analytics/metrics/custom/manual/value/delete` | rejected | write | high | value/list | `verified_rest_write` | closed |
| Analytics calendar event | `POST /project/analytics/event/add` | rejected | write | medium | none proven | `verified_rest_write` | closed |
| Status funnel | `POST /project/reports/funnel/data` | `roistat_funnel` | read | low | n/a | `verified_rest_read` | enabled |
| Daily statistics | `POST /project/statistics/get-daily` | `roistat_statistics_daily` | read | low | n/a | `verified_rest_read` + `official_mcp_read` | enabled; extra hour cap |
| Orders list | `POST /project/integration/order/list` | `roistat_list_orders` | read | low | n/a | `verified_rest_read` + `official_mcp_read` | enabled |
| Order card | `GET /project/orders/{orderId}/info` | `roistat_get_order` | read | low | n/a | `verified_rest_read` + `official_mcp_read` | enabled |
| Order CRM URL | `GET /project/orders/{orderId}/external-url` | none | read | low | n/a | `verified_rest_read` | not in v1 |
| Funnel statuses | `POST /project/integration/status/list` | `roistat_list_order_statuses` | read | low | n/a | `verified_rest_read` | enabled |
| Order custom fields | `POST /project/analytics/order-custom-fields` | none | read | low | n/a | `verified_rest_read` | not in v1 |
| Import orders | `POST /project/add-orders` | `roistat_prepare_write` / `roistat_apply_write` `import_order` | write | medium | `GET /project/orders/{id}/info` | `verified_rest_write` | gated; single object; disabled by default |
| Set status catalog | `POST /project/set-statuses` | rejected | write | medium | status/list | `verified_rest_write` | closed |
| Update order status | `POST /project/integration/order/{orderId}/status/update` | `update_order_status` | write | medium | order info | `verified_rest_write` | gated; single object |
| Update order goal | `POST /project/integration/order/{orderId}/goal/update` | rejected | write | medium | order info | `verified_rest_write` | not in v1 |
| Bulk order update | `POST /project/integration/order/update` | rejected | write | medium | order info | `verified_rest_write` | closed (multi-object) |
| Delete one order | `POST /project/integration/order/{orderId}/delete` | `delete_order` | write | high | order info / 404 | `verified_rest_write` | gated; per-object approval; no batch |
| Batch delete orders | `POST /project/integration/order/delete` | rejected | write | high | none | `verified_rest_write` | **rejected**; no batch delete |
| Proxy leads | `GET /project/proxy-leads` | `roistat_list_leads` | read | low | n/a | `verified_rest_read` + `official_mcp_read` | enabled |
| Lead duplicates | `GET /project/proxy-leads/duplicates` | `roistat_list_lead_duplicates` | read | low | n/a | `verified_rest_read` | enabled |
| One lead | `GET /project/proxy-leads/{proxyLeadId}` | `roistat_get_lead` | read | low | n/a | `verified_rest_read` + `official_mcp_read` | enabled |
| Clients list | `POST /project/clients` | `roistat_list_clients` | read | low | n/a | `verified_rest_read` | enabled; PII redacted |
| Client feed | `GET /project/clients/detail/feed` | none | read | low | n/a | `verified_rest_read` | not in v1 |
| Import client | `POST /project/clients/import` | `import_client` | write | medium | clients list | `verified_rest_write` | gated; single object |
| Visits | `POST /project/site/visit/list` | `roistat_list_visits` | read | low | n/a | `verified_rest_read` | enabled; IP redacted |
| Visit param update | `POST /project/site/visit/params/update` | rejected | write | medium | visit list | `verified_rest_write` | closed |
| Call list | `POST /project/calltracking/call/list` | `roistat_list_calls` | read | low | n/a | `verified_rest_read` + `official_mcp_read` | enabled; phones redacted |
| Call dashboard | `POST /project/calltracking/data` | `roistat_calltracking_summary` | read | low | n/a | `verified_rest_read` | enabled |
| Call XLS export | `POST /project/calltracking/call/xls/export` | none | read | low | n/a | `verified_rest_read` | closed (binary) |
| Call audio | `POST /project/calltracking/call/{id}/file` | none | read | low | n/a | `verified_rest_read` | closed (binary) |
| Script list | `POST /project/calltracking/script/list` | none | read | low | n/a | `verified_rest_read` | not in v1 (redirect/PII) |
| Phone list | `POST /project/calltracking/phone/list` | none | read | low | n/a | `verified_rest_read` | not in v1 (phone numbers) |
| Prefix list | `POST /project/calltracking/phone/prefix/list` | none | read | low | n/a | `verified_rest_read` | not in v1 |
| Script create/update | `POST .../script/create`, `.../script/update` | rejected | write | medium | script list | `verified_rest_write` | closed in v1 |
| Script delete | `POST .../script/delete` | rejected | write | high | script list | `verified_rest_write` | closed |
| Call update | `POST .../call/update` | rejected | write | medium | call list | `verified_rest_write` | closed |
| Create call record | `POST /project/phone-call` | rejected | write | medium | call list | `verified_rest_write` | closed |
| Delete call | `POST .../call/delete` | rejected | write | high | call list | `verified_rest_write` | closed |
| Rent Roistat number | `POST .../phone/buy` | rejected | write | high | phone list | `verified_rest_write` | closed (paid) |
| Phone create/update/delete | `POST .../phone/{create,update,delete}` | rejected | write | high | phone list | `verified_rest_write` | closed |
| Advertising platform / channel create | none in official REST | rejected | write | high | none | `unsupported_by_official_api` | closed; UI only |
| Advertising platform / channel delete | none in official REST | rejected | write | high | none | `unsupported_by_official_api` | closed; UI only |
| CRM integration connect/disconnect | none in official REST | rejected | write | high | none | `unsupported_by_official_api` | closed; UI only |
| Integration health / last-sync field | no dedicated official method | `roistat_health` | read | low | n/a | `unknown_needs_live_discovery` | inferred from projects + last report date; empty ≠ zero |
| Generic passthrough / browser automation | n/a | none | n/a | high | n/a | `unsupported_by_official_api` | forbidden |

## Official MCP versus this provider

The official MCP article says assistants can read analytics, compare periods,
inspect a lead/order by id and list calls. It also says configuration and
writes belong in the Roistat UI. This provider covers those read scenarios
through documented REST methods and keeps advertising-platform and CRM-
integration create/delete closed because no official REST write exists.

## Honesty notes

- Metric names in examples mix `visits`/`leads` with `visitCount`/`leadCount`.
  The adapter allowlists both documented spellings and refuses unknown names.
- Empty arrays are returned as `completeness=unknown`, never coerced to zero.
- Phones, emails and visitor IPs are redacted in tool results.
- Write tools exist only for proven single-object CRM endpoints and stay
  disabled until `MCP_ROISTAT_WRITE_ENABLED=true` plus an accepted approval.
