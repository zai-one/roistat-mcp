# Analytics bundles

[Русский](#русский) · [Back to Roistat MCP](../README.md)

Use `roistat_analytics_bundle` when a report needs to be checked, repeated or shared: it keeps the exact query, provider totals, attribution and the source of every row together. One call retrieves one or two periods. It does not calculate a new attribution model or period deltas; your assistant can compare the returned reports.

Try: “Prepare a CSV of visits and leads by channel for these two periods. Keep the attribution model the same, show missing values separately and explain which rows were included.”

```json
{
  "project_id": 12345,
  "metrics": ["visits", "leads"],
  "dimensions": ["marker_level_1"],
  "period": {"from": "2026-06-01T00:00:00+00:00", "to": "2026-06-08T00:00:00+00:00"},
  "comparison_period": {"from": "2026-05-25T00:00:00+00:00", "to": "2026-06-01T00:00:00+00:00"},
  "attribution": "default",
  "row_offset": 0,
  "max_rows": 100,
  "format": "csv"
}
```

Use your own project ID. Omit `comparison_period` for a single report. `interval` optionally accepts `1d`, `1w` or `1m`. All periods and fields are validated before the first request.

| Returned field | How to read it |
|---|---|
| `reports[].rows` | JSON rows with block dates, selected dimensions and metric cells. CSV replaces these rows with the top-level `csv` string. |
| `value` / `value_state` | A supported numeric value, including real zero; or `null` with `missing`, `non_numeric` or `out_of_range`. Numeric magnitudes above 10¹⁵, non-finite values and underflow to zero are rejected as values. |
| `attribution_model_id` | The ID returned by the provider. A requested model is not substituted for a missing ID. Multiple values for the same metric are rejected as ambiguous. |
| `totals_by_block` | Provider `mean.metrics`, separately for every returned time block. These are never recomputed by summing a partial table or ratios. |
| `selection` | Count of rows in the response and in this local slice; `next_row_offset` and `stop_reason`. `all_response_rows_included` refers only to this response. Provider completeness is not asserted. |
| `replay` | Tool name and arguments to repeat the request. Repeating it can return changed data. |
| `request_sha256` / `response_sha256` | Digests of the validated provider queries and each cleaned provider response. The request digest excludes local slice/format settings; those are retained in `replay`. These are not provider signatures or an immutable snapshot. |

The report accepts 1–12 distinct supported metric names, 1–2 distinct supported dimensions and up to 93 days per period. Discover supported names with the existing report catalog. Custom metric discovery does not expand this allowlist. Exports include 1–250 rows per period, with offsets 0–10,000, and at most 256 KiB of JSON. At the offset boundary a partial result has `stop_reason: offset_limit` and no next offset. Reduce the report scope if needed.

**Row limits apply to the local export.** They do not reduce the provider response or its API cost. There is no provider cursor or stable snapshot behind `row_offset`. Compare response digests when repeating a request to extract another slice; matching digests describe identical cleaned responses, not guaranteed future stability. The tool preserves up to 93 provider time blocks, including their totals.

## Access and privacy

The tool uses `roistat:read`, the existing account binding, project authorization and per-request admission, audit and timeout rules. Every HTTP attempt counts, including retries. A nonempty project allowlist restricts access; an empty list leaves read access to the API credential's permissions. The setup wizard configures an explicit list.

Supported structured personal fields and configured credentials are cleaned before hashing and CSV serialization. Formula-like CSV text is quoted as text. Free text is not guaranteed anonymous: review the report before sharing. No new local report archive is created. Changing CRM data remains a separate operation.

The response mapping follows the provider's [analytics API](https://help-en.roistat.com/API/methods/analytics/) and [attribution documentation](https://help-en.roistat.com/features/analytics/attribution_models/). Tests exercise synthetic responses, denied access, malformed/missing values, interval totals, export bounds and installation without live Roistat calls.

## Русский

`roistat_analytics_bundle` собирает отчёт, который удобно проверить, повторить и передать коллеге: параметры запроса, итоги Roistat, атрибуция и происхождение строк остаются рядом с цифрами. За один вызов можно получить один или два периода. Инструмент не пересчитывает атрибуцию и не вычисляет разницу периодов — сравнение выполняет ассистент по возвращённым данным.

Попробуйте: «Подготовь CSV визитов и заявок по каналам за эти два периода. Используй одну модель атрибуции, отдели пропуски от нулей и объясни, какие строки вошли в выгрузку».

В примере выше замените `project_id` на свой. Для одного периода уберите `comparison_period`. Необязательный `interval` принимает `1d`, `1w` или `1m`. Все параметры обоих периодов проверяются до первого HTTP-запроса.

- `rows` содержит строки с датами блока, измерениями и метриками. При `format: csv` строки переходят в общий `csv`, остальные пояснения остаются в JSON.
- Настоящий ноль сохраняется. Отсутствующие, нечисловые, бесконечные, превышающие по модулю 10¹⁵ или исчезающие при преобразовании в ноль значения возвращаются как `null` с отдельным `value_state`.
- `attribution_model_id` берётся из ответа Roistat. Пропущенный ID не заменяется выбранной моделью. Несколько значений одной метрики считаются неоднозначным ответом.
- `totals_by_block` сохраняет `mean.metrics` провайдера по каждому интервалу. Суммировать обрезанную таблицу или проценты для получения итогов инструмент не пытается.
- `selection` показывает объём ответа и выгрузки, следующую позицию и причину остановки. `all_response_rows_included` означает только полноту данного ответа; полнота данных у провайдера не утверждается.
- `replay` сохраняет инструмент и аргументы. SHA-256 описывают проверенные запросы и очищенные ответы, а не подпись провайдера. Параметры локальной выборки и формата входят в `replay`, но не в хеш запроса к API.

Ограничения: 12 разных поддерживаемых метрик, 2 измерения, 93 дня на период и до 93 блоков ответа; 1–250 строк на период, смещение 0–10 000 и не более 256 КиБ JSON. Каталог пользовательских метрик не расширяет список разрешённых метрик отчёта. На границе смещения неполная выборка получает `stop_reason: offset_limit` без следующего смещения.

**Лимит строк ограничивает выгрузку локально, а не ответ и стоимость API.** Смещение не является курсором провайдера и не фиксирует снимок. Повторный запрос может вернуть другие данные: при выгрузке следующего фрагмента сравнивайте хеши очищенных ответов. Совпадение не гарантирует неизменность будущих ответов.

Сохраняются `roistat:read`, привязка аккаунта, разрешённые проекты, аудит и лимиты каждого HTTP-вызова. Непустой список проектов ограничивает доступ; при пустом списке права чтения определяются ключом Roistat. Мастер настройки создаёт явный список.

Поддерживаемые структурированные персональные поля и настроенные ключи очищаются до хеширования и CSV. Текст, похожий на формулу, экспортируется как текст. Произвольный текст не гарантированно анонимен — проверьте файл перед передачей. Новый локальный архив отчётов не создаётся.

[Документация API Roistat](https://help-ru.roistat.com/API/methods/analytics/). Проверки используют синтетические ответы и не обращаются к реальному аккаунту.
