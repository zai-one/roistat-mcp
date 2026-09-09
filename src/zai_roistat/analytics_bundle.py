"""Reproducible request metadata and bounded tables from provider analytics blocks."""

from __future__ import annotations

import csv
import io
import json
import math
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from zai_roistat import __version__
from zai_roistat.transport import ProviderError, request_hash


def numeric(value):
    if value is None:
        return None, "missing"
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None, "non_numeric"
    if isinstance(value, str) and len(value) > 128:
        return None, "out_of_range"
    try:
        number = float(value.replace(" ", "").replace(",", ".")) if isinstance(value, str) else float(value)
    except (ValueError, OverflowError):
        return None, "non_numeric"
    if not math.isfinite(number) or abs(number) > 1e15:
        return None, "out_of_range"
    try:
        exact = (
            Decimal(value.replace(" ", "").replace(",", ".")) if isinstance(value, str) else Decimal(value)
        )
        if exact.copy_abs() > Decimal("1e15") or (number == 0 and exact != 0):
            return None, "out_of_range"
    except (InvalidOperation, ValueError, OverflowError):
        return None, "non_numeric"
    return number, "present"


def metric_cells(raw, names):
    if raw is None:
        raw = []
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        raise ProviderError("unexpected metric collection")
    mapped = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ProviderError("unexpected metric record")
        name = item.get("metric_name", item.get("metric"))
        if name not in names:
            continue
        if name in mapped:
            raise ProviderError("multiple values for one requested metric; attribution is ambiguous")
        value, state = numeric(item.get("value"))
        attribution = item.get("attribution_model_id")
        if attribution is not None and type(attribution) not in (str, int):
            raise ProviderError("unexpected metric attribution")
        mapped[name] = {"value": value, "value_state": state, "attribution_model_id": attribution}
    return {
        name: mapped.get(name, {"value": None, "value_state": "missing", "attribution_model_id": None})
        for name in names
    }


def normalize(raw, metrics, dimensions, row_offset, max_rows):
    blocks = raw.get("data")
    if not isinstance(blocks, list) or len(blocks) > 93:
        raise ProviderError("expected at most 93 analytics blocks")
    rows, totals, total_count = [], [], 0
    for index, block in enumerate(blocks):
        if not isinstance(block, dict) or not isinstance(block.get("items"), list):
            raise ProviderError("unexpected analytics block")
        dates = {
            key: block.get(key) if isinstance(block.get(key), str) else None for key in ("dateFrom", "dateTo")
        }
        mean = block.get("mean")
        if mean is not None and not isinstance(mean, dict):
            raise ProviderError("unexpected provider totals")
        totals.append(
            {
                "block_index": index,
                **dates,
                "metrics": metric_cells(mean.get("metrics") if mean else None, metrics),
                "source": "provider_mean_not_sum_of_rows",
            }
        )
        for item in block["items"]:
            absolute = total_count
            total_count += 1
            if not isinstance(item, dict) or not isinstance(item.get("dimensions"), dict):
                raise ProviderError("unexpected analytics row dimensions")
            # Validate every row's metric shape, including rows outside the requested slice.
            values = metric_cells(item.get("metrics"), metrics)
            if not row_offset <= absolute < row_offset + max_rows:
                continue
            dims = {}
            for name in dimensions:
                cell = item["dimensions"].get(name)
                if cell is not None and not isinstance(cell, dict):
                    raise ProviderError("unexpected dimension cell")
                dims[name] = {
                    "value": cell.get("value") if cell else None,
                    "title": cell.get("title") if cell else None,
                }
            rows.append({"block_index": index, **dates, "dimensions": dims, "metrics": values})
    following = row_offset + len(rows)
    has_more = following < total_count
    return {
        "rows": rows,
        "totals_by_block": totals,
        "selection": {
            "row_offset": row_offset,
            "max_rows": max_rows,
            "rows_in_response": total_count,
            "returned_rows": len(rows),
            "next_row_offset": following if has_more and following <= 10000 else None,
            "stop_reason": "offset_limit"
            if has_more and following > 10000
            else ("more_response_rows" if has_more else "response_end"),
            "all_response_rows_included": row_offset == 0 and len(rows) == total_count,
            "provider_completeness": "not_asserted",
        },
    }


def export_csv(reports, metrics, dimensions):
    fields = ["period", "block_index", "dateFrom", "dateTo"]
    for name in dimensions:
        fields.extend([name + ".value", name + ".title"])
    for name in metrics:
        fields.extend(name + "." + key for key in ("value", "value_state", "attribution_model_id"))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for report in reports:
        for row in report["rows"]:
            cells = {
                "period": report["label"],
                **{key: row[key] for key in ("block_index", "dateFrom", "dateTo")},
            }
            for kind in ("dimensions", "metrics"):
                for name, data in row[kind].items():
                    for key, value in data.items():
                        if isinstance(value, (dict, list)):
                            value = json.dumps(value, sort_keys=True, ensure_ascii=False)
                        cells[name + "." + key] = value
            for key, value in cells.items():
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    cells[key] = "'" + value
            writer.writerow(cells)
    return stream.getvalue()


async def bundle(
    runtime,
    project_id,
    metrics,
    dimensions,
    period,
    comparison_period,
    attribution,
    interval,
    row_offset,
    max_rows,
    format,
):
    if format not in {"json", "csv"} or type(max_rows) is not int or not 1 <= max_rows <= 250:
        raise ValueError("provide json/csv format and max_rows between 1 and 250")
    if type(row_offset) is not int or not 0 <= row_offset <= 10000:
        raise ValueError("row_offset must be between 0 and 10000")
    if (
        not isinstance(metrics, list)
        or any(not isinstance(name, str) for name in metrics)
        or len(set(metrics)) != len(metrics)
        or any(name != name.strip() for name in metrics)
    ):
        raise ValueError("provide distinct metric names; one attribution is selected for this bundle")
    if not isinstance(dimensions, list) or len(set(dimensions)) != len(dimensions):
        raise ValueError("provide distinct dimension names")
    adapter = runtime.roistat()
    periods = [period] + ([comparison_period] if comparison_period is not None else [])
    # All project, scope, metric, dimension and period checks precede the first provider call.
    validated = [
        adapter.validate_analytics(
            project_id, metrics, dimensions, value, attribution=attribution, interval=interval
        )
        for value in periods
    ]
    reports, started = [], datetime.now(UTC).isoformat()
    for index, query in enumerate(validated):
        raw = await runtime.read(
            "roistat",
            "analytics_bundle",
            query,
            lambda query=query: adapter._call(
                "analytics_data", project_id=query["project_id"], payload=query["payload"]
            ),
        )
        # _call applies existing recursive PII redaction; runtime.read cleans credentials before hashing/CSV.
        report = normalize(raw, metrics, dimensions, row_offset, max_rows)
        reports.append(
            {
                "label": "current" if index == 0 else "comparison",
                "request": query,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "response_sha256": request_hash(raw),
                **report,
            }
        )
    replay = dict(
        project_id=project_id,
        metrics=metrics,
        dimensions=dimensions,
        period=period,
        comparison_period=comparison_period,
        attribution=attribution,
        interval=interval,
        row_offset=row_offset,
        max_rows=max_rows,
        format=format,
    )
    result = runtime.clean(
        {
            "schema_version": 1,
            "package_version": __version__,
            "reports": reports,
            "replay": {"tool": "roistat_analytics_bundle", "arguments": replay},
            "request_sha256": request_hash(validated),
            "started_at": started,
            "endpoint": "project/analytics/data",
            "notes": [
                "Repeating a request can return changed data; response digests describe cleaned responses.",
                "Row offsets slice this API response locally, not a provider snapshot or server cursor.",
                "Missing metrics remain null. Provider totals are not recomputed from a partial table.",
                "PII filtering covers known structured fields; free text is not guaranteed anonymous.",
            ],
        }
    )
    if format == "csv":
        result["csv"] = export_csv(result["reports"], metrics, dimensions)
        for report in result["reports"]:
            report.pop("rows")
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > 262144:
        raise ValueError("analytics bundle too large; reduce max_rows, dimensions or reporting interval")
    return result


def register_bundle(server, runtime):
    @server.tool(auth=runtime.require_scopes("roistat:read"))
    async def roistat_analytics_bundle(
        project_id: int,
        metrics: list[str],
        dimensions: list[str],
        period: dict,
        comparison_period: dict | None = None,
        attribution: str = "default",
        interval: str | None = None,
        row_offset: int = 0,
        max_rows: int = 100,
        format: str = "json",
    ) -> dict:
        """Bundle one or two reports with provider totals, attribution, replay metadata and JSON/CSV."""
        return await bundle(
            runtime,
            project_id,
            metrics,
            dimensions,
            period,
            comparison_period,
            attribution,
            interval,
            row_offset,
            max_rows,
            format,
        )
