from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from zai_roistat.coalescing import AsyncSingleFlight
from zai_roistat.transport import (
    JsonHttpClient,
    ProviderAuthenticationError,
    ProviderError,
    ProviderHttpError,
    ProviderNotFoundError,
    ProviderRateLimited,
    ProviderTransientHttpError,
    request_hash,
)

OFFICIAL_BASE_URL = "https://cloud.roistat.com/api/v1"
OFFICIAL_HOST = "cloud.roistat.com"
MAX_LIMIT = 100
MAX_OFFSET = 10_000
MAX_PROJECT_ID = 2_147_483_647
MAX_PERIOD_DAYS_ANALYTICS = 93
MAX_PERIOD_DAYS_LIST = 31
MAX_DIMENSIONS = 2
MAX_METRICS = 12
MAX_FUNNEL_STAGES = 8
MAX_FUNNEL_STATUSES = 20
MAX_OBJECT_ID_LEN = 128
MAX_CHANNEL_LEN = 64
LOCAL_MAX_PER_SECOND = 5
LOCAL_MAX_PER_MINUTE = 30
LOCAL_MAX_PER_HOUR = 600
DAILY_STATS_MAX_PER_HOUR = 3
DEFAULT_LIMIT = 50
MAX_CATALOG_ROWS = 500
MAX_INDICATOR_GROUPS = 50
MAX_INDICATORS = 100
MAX_INDICATOR_MESSAGES = 20
MAX_INDICATOR_TEXT = 500
MAX_INDICATOR_DATE = 64
# Official status codes of /project/health/indicator/list.
INDICATOR_STATES = {1: "ok", 2: "errors", 3: "not_finished"}
REDACTED = "***redacted***"

ALLOWED_METRICS = frozenset(
    {
        "visits",
        "leads",
        "sales",
        "profit",
        "marketing_cost",
        "roi",
        "revenue",
        "visitCount",
        "leadCount",
        "impressions",
        "ctr",
        "visits2leads",
        "leads2orders",
        "conversion_visits_to_leads",
        "conversion_leads_to_sales",
        "average_sale",
        "averageRevenue",
        "cpc",
        "cpl",
        "cpo",
        "cv1",
        "cv2",
    }
)
ALLOWED_DIMENSIONS = frozenset(
    {
        "marker_level_1",
        "marker_level_2",
        "marker_level_3",
        "marker_level_4",
        "marker_level_5",
    }
)
ALLOWED_ATTRIBUTIONS = frozenset(
    {
        "default",
        "first_click",
        "last_click",
        "last_paid_click",
        "u_shape",
        "linear",
    }
)
ALLOWED_INTERVALS = frozenset({"1d", "1w", "1m"})
ALLOWED_FILTER_OPS = frozenset({">", "<", "=", "!=", "<>", ">=", "<=", "in", "not_in"})
ALLOWED_ORDER_FILTER_FIELDS = frozenset(
    {"id", "creation_date", "update_date", "status", "visit_id", "client_id"}
)
ALLOWED_CALL_FILTER_FIELDS = frozenset({"id", "date", "status", "visit_id", "order_id"})
ALLOWED_VISIT_FILTER_FIELDS = frozenset({"id", "date", "landing_page", "host", "source.system_name"})
ALLOWED_CLIENT_FILTER_FIELDS = frozenset({"id", "external_id"})
ALLOWED_CALL_STATUSES = frozenset(
    {"ACTIVE", "ANSWER", "BUSY", "NOANSWER", "CANCELLED", "FAILED", "CONGESTION", "CHANUNAVAIL"}
)
ALLOWED_TIMEZONES = frozenset(
    {
        "UTC",
        "Europe/Moscow",
        "Europe/Samara",
        "Europe/Kaliningrad",
        "Asia/Yekaterinburg",
        "Asia/Novosibirsk",
        "Asia/Krasnoyarsk",
        "Asia/Irkutsk",
        "Asia/Yakutsk",
        "Asia/Vladivostok",
        "Asia/Magadan",
        "Asia/Kamchatka",
        "Asia/Almaty",
        "Asia/Tashkent",
        "Europe/Kiev",
        "Europe/Minsk",
    }
)
PII_KEYS = frozenset(
    {
        "phone",
        "email",
        "phones",
        "emails",
        "client_phones",
        "client_emails",
        "client_name",
        "caller",
        "callee",
        "ip",
        "birth_date",
        "text",
    }
)
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
_OBJECT_ID = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
_CHANNEL = re.compile(r"[A-Za-z0-9_]{1,64}\Z")
_DAILY_PERIOD = re.compile(r"\d{4}-\d{2}-\d{2}-\d{4}-\d{2}-\d{2}\Z")
_ISO_OFFSET = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:?\d{2})\Z")
_SAFE_ERROR = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")

UNSUPPORTED_WRITES = frozenset(
    {
        "create_ad_platform",
        "delete_ad_platform",
        "create_channel",
        "delete_channel",
        "create_crm_integration",
        "delete_crm_integration",
        "delete_orders_batch",
        "buy_phone",
        "create_project",
        "delete_call",
    }
)


@dataclass(frozen=True, slots=True)
class _ReadSpec:
    method: str
    segments: tuple[str, ...]
    needs_project: bool = True
    array_response: bool = False


@dataclass(frozen=True, slots=True)
class _WriteSpec:
    risk: str
    method: str
    segments: tuple[str, ...]
    array_body: bool = False


READ_SPECS: dict[str, _ReadSpec] = {
    "list_projects": _ReadSpec("GET", ("user", "projects"), needs_project=False),
    "analytics_data": _ReadSpec("POST", ("project", "analytics", "data")),
    "analytics_metrics": _ReadSpec("POST", ("project", "analytics", "metrics-new")),
    "analytics_dimensions": _ReadSpec("POST", ("project", "analytics", "dimensions")),
    "analytics_dimension_values": _ReadSpec("POST", ("project", "analytics", "dimension-values")),
    "analytics_custom_metrics": _ReadSpec("GET", ("project", "analytics", "metrics", "custom", "list")),
    "analytics_attribution": _ReadSpec("POST", ("project", "analytics", "attribution-models")),
    "statistics_daily": _ReadSpec("POST", ("project", "statistics", "get-daily")),
    "list_orders": _ReadSpec("POST", ("project", "integration", "order", "list")),
    "get_order": _ReadSpec("GET", ("project", "orders", "{order_id}", "info")),
    "list_order_statuses": _ReadSpec("POST", ("project", "integration", "status", "list")),
    "list_leads": _ReadSpec("GET", ("project", "proxy-leads")),
    "get_lead": _ReadSpec("GET", ("project", "proxy-leads", "{lead_id}")),
    "list_lead_duplicates": _ReadSpec("GET", ("project", "proxy-leads", "duplicates")),
    "list_calls": _ReadSpec("POST", ("project", "calltracking", "call", "list")),
    "calltracking_summary": _ReadSpec("POST", ("project", "calltracking", "data")),
    "funnel": _ReadSpec("POST", ("project", "reports", "funnel", "data")),
    "list_visits": _ReadSpec("POST", ("project", "site", "visit", "list")),
    "list_clients": _ReadSpec("POST", ("project", "clients")),
    # https://help-ru.roistat.com/API/methods/indicator/
    "health_indicators": _ReadSpec("GET", ("project", "health", "indicator", "list")),
    # https://help-ru.roistat.com/API/methods/channels/
    "list_channels": _ReadSpec("POST", ("project", "analytics", "source", "list")),
    "list_channel_costs": _ReadSpec(
        "POST", ("project", "analytics", "source", "cost", "list"), array_response=True
    ),
    # https://help-ru.roistat.com/API/methods/managers/
    "list_managers": _ReadSpec("POST", ("project", "integration", "manager", "list")),
    # Coverage round 2026-10 (opt-in toolset extras):
    # https://help-ru.roistat.com/API/methods/calltracking/
    "calltracking_scripts": _ReadSpec("POST", ("project", "calltracking", "script", "list")),
    "calltracking_phones": _ReadSpec("POST", ("project", "calltracking", "phone", "list")),
    # https://help-ru.roistat.com/API/methods/events/ (heading says GET, the documented curl
    # sends POST with a JSON body {name, date_from, date_to}; a GET cannot carry those filters)
    "events_log": _ReadSpec("POST", ("project", "events", "log")),
    # https://help-ru.roistat.com/API/methods/clients/ (client activity feed):
    # GET ...?project=<id>&client=<id>, response {"feed": [...]}
    "client_feed": _ReadSpec("GET", ("project", "clients", "detail", "feed")),
}
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.]+(?:Z|[+-]\d{2}:?\d{2})?)?")
EXTRA_READS = ("calltracking_scripts", "calltracking_phones", "events_log", "client_feed")

WRITE_ALLOWLIST: dict[str, _WriteSpec] = {
    "update_order_status": _WriteSpec(
        "medium",
        "POST",
        ("project", "integration", "order", "{order_id}", "status", "update"),
    ),
    "import_order": _WriteSpec("medium", "POST", ("project", "add-orders"), array_body=True),
    "import_client": _WriteSpec("medium", "POST", ("project", "clients", "import"), array_body=True),
    "delete_order": _WriteSpec(
        "high",
        "POST",
        ("project", "integration", "order", "{order_id}", "delete"),
    ),
    # Calltracking writes and events, per help-en.roistat.com/API/methods/{calltracking,events}/.
    "calltracking_script_create": _WriteSpec(
        "medium", "POST", ("project", "calltracking", "script", "create")
    ),
    "calltracking_script_update": _WriteSpec(
        "medium", "POST", ("project", "calltracking", "script", "update")
    ),
    "calltracking_script_delete": _WriteSpec("high", "POST", ("project", "calltracking", "script", "delete")),
    "calltracking_phone_create": _WriteSpec("medium", "POST", ("project", "calltracking", "phone", "create")),
    "calltracking_phone_update": _WriteSpec("medium", "POST", ("project", "calltracking", "phone", "update")),
    "calltracking_phone_delete": _WriteSpec("high", "POST", ("project", "calltracking", "phone", "delete")),
    "events_send": _WriteSpec("low", "POST", ("project", "events", "send")),
    "events_bulk_send": _WriteSpec("medium", "POST", ("project", "events", "bulk", "send"), array_body=True),
    "events_add": _WriteSpec("medium", "POST", ("project", "events", "add"), array_body=True),
}

# Without ROISTAT_WRITE_OPERATIONS only the original four writes are enabled; calltracking and
# events writes must be named there explicitly, so upgrading never widens an operator's surface.
DEFAULT_WRITE_OPERATIONS = frozenset({"update_order_status", "import_order", "import_client", "delete_order"})

_SCRIPT_KEYS = ("name", "is_enabled", "creation_date", "options", "integration")
_PHONE = re.compile(r"^\d{11,15}$")


def _event_body(item: Mapping[str, Any]) -> dict[str, Any]:
    name = item.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        raise ProviderError("Roistat event requires a name configured in Roistat")
    body: dict[str, Any] = {"name": name.strip()}
    if item.get("visit") is not None:
        body["visit"] = str(item["visit"]).strip()[:64]
    if item.get("data") is not None:
        if not isinstance(item["data"], Mapping) or len(item["data"]) > 50:
            raise ProviderError("Roistat event data must be an object with <=50 keys")
        body["data"] = dict(item["data"])
    return body


class JsonRequester(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]: ...


def _validate_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or parsed.hostname != OFFICIAL_HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"/api/v1", ""}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Roistat base URL must be the official HTTPS API v1 endpoint")
    return OFFICIAL_BASE_URL


def _indicator_state(value: object) -> str:
    """Map a provider status code to a state; anything odd (lists, dicts, bools...) is unknown."""
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 3:
        value = int(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return INDICATOR_STATES.get(value, "unknown")
    return "unknown"


def _indicator_text(value: object, limit: int = MAX_INDICATOR_TEXT) -> str | None:
    """Provider text, bounded; non-text values are dropped rather than echoed."""
    return value[:limit] if isinstance(value, str) else None


def _indicator_scalar(value: object) -> int | str | None:
    """Provider id or status code: an integer or bounded string, nothing else."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return _indicator_text(value, MAX_OBJECT_ID_LEN)


def _indicator_flag(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _positive_int(value: object, field: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError(f"{field} must be a positive integer")
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if normalized < 1 or normalized > maximum:
        raise ValueError(f"{field} must be between 1 and {maximum}")
    return normalized


def _non_negative_int(value: object, field: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError(f"{field} must be a non-negative integer")
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative integer") from exc
    if normalized < 0 or normalized > maximum:
        raise ValueError(f"{field} must be between 0 and {maximum}")
    return normalized


def _int_id(value: object, field: str) -> int:
    text = _object_id(value, field)
    if not text.isdigit():
        raise ValueError(f"{field} must be a numeric Roistat id")
    return int(text)


def _object_id(value: object, field: str) -> str:
    if not isinstance(value, str | int) or isinstance(value, bool):
        raise ValueError(f"{field} must be a safe identifier")
    text = str(value).strip()
    if not text or "/" in text or "\\" in text or ".." in text or _OBJECT_ID.fullmatch(text) is None:
        raise ValueError(f"{field} must be a safe identifier")
    return text


def _parse_csv_ids(value: str) -> tuple[int, ...]:
    items: list[int] = []
    for raw in value.split(","):
        piece = raw.strip()
        if not piece:
            continue
        items.append(_positive_int(piece, "project_id", MAX_PROJECT_ID))
    return tuple(dict.fromkeys(items))


def _parse_csv_ops(value: str) -> frozenset[str]:
    items = {item.strip() for item in value.split(",") if item.strip()}
    return frozenset(items)


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if _ISO_OFFSET.fullmatch(text) is None:
        raise ValueError("timestamp must be ISO-8601 with an explicit offset")
    normalized = text.replace("Z", "+00:00")
    if len(normalized) >= 5 and normalized[-5] in {"+", "-"} and ":" not in normalized[-5:]:
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone offset")
    return parsed.astimezone(UTC)


def _parse_daily_period(value: str) -> tuple[str, date, date]:
    text = value.strip()
    if _DAILY_PERIOD.fullmatch(text) is None:
        raise ValueError("period must use YYYY-MM-DD-YYYY-MM-DD")
    start = date.fromisoformat(text[:10])
    end = date.fromisoformat(text[11:])
    if end < start:
        raise ValueError("period end must not precede start")
    if (end - start).days > MAX_PERIOD_DAYS_LIST:
        raise ValueError(f"period must be at most {MAX_PERIOD_DAYS_LIST} days")
    return f"{start.isoformat()}-{end.isoformat()}", start, end


def _bounded_period(period: Mapping[str, Any], *, max_days: int) -> dict[str, str]:
    if set(period) - {"from", "to"}:
        raise ValueError("period only accepts from and to")
    start = _parse_iso(str(period.get("from", "")))
    end = _parse_iso(str(period.get("to", "")))
    if end < start:
        raise ValueError("period end must not precede start")
    if (end - start) > timedelta(days=max_days):
        raise ValueError(f"period must be at most {max_days} days")
    return {
        "from": period["from"].strip() if isinstance(period["from"], str) else start.isoformat(),
        "to": period["to"].strip() if isinstance(period["to"], str) else end.isoformat(),
    }


# Schema-specific fields whose generic names ("value", "name", "field") carry secrets or PII:
# calltracking options.redirect.value is a phone, an external SIP account or a Roistat SIP
# password (help-en.roistat.com/API/methods/calltracking/); client-feed lead_hunter_* records
# keep the visitor's entered phone in "field" and their name in "name" (.../methods/clients/).
_FORWARDING_KEYS = frozenset({"redirect"})
_LEAD_HUNTER_CONTACT_KEYS = frozenset({"name", "field"})


def _redact_pii(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        record_type = value.get("type")
        lead_hunter = isinstance(record_type, str) and record_type.startswith("lead_hunter")
        for raw_key, child in value.items():
            key = str(raw_key)
            marker = "".join(character for character in key.lower() if character.isalnum())
            contact = lead_hunter and marker in _LEAD_HUNTER_CONTACT_KEYS and child is not None
            if marker in PII_KEYS or any(part == marker for part in PII_KEYS) or contact:
                redacted[key] = REDACTED
            elif marker in _FORWARDING_KEYS and isinstance(child, Mapping):
                forwarding = _redact_pii(child)
                if forwarding.get("value") is not None:
                    forwarding["value"] = REDACTED
                redacted[key] = forwarding
            else:
                redacted[key] = _redact_pii(child)
        return redacted
    if isinstance(value, list):
        return [_redact_pii(item) for item in value]
    return value


def _items_of(response: Mapping[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = response.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, Mapping):
            nested = value.get("items")
            if isinstance(nested, list):
                return nested
            if key == "data" and any(item in value for item in ("id", "items")):
                return [value]
    return []


def _full_collection(response: Mapping[str, Any], *keys: str) -> tuple[list[Any] | None, bool]:
    """Return the listed collection and whether it provably covers every object.

    None means the response carries no collection at all. Coverage holds only when a list is
    present and a reported total (if any) is a readable count not above the returned rows.
    """
    for key in keys:
        value = response.get(key)
        if isinstance(value, Mapping):
            value = value.get("items")
        if not isinstance(value, list):
            continue
        total = response.get("total")
        if total is None:
            return value, True
        if isinstance(total, bool) or not isinstance(total, int | str) or not str(total).isdigit():
            return value, False
        return value, int(total) <= len(value)
    return None, False


def _completeness(items: Sequence[Any] | None, total: object | None, *, limit: int | None) -> str:
    if items is None:
        return "unknown"
    if not items:
        return "unknown"
    if isinstance(total, int) and not isinstance(total, bool) and total > len(items):
        return "partial"
    if limit is not None and len(items) >= limit:
        return "partial"
    return "complete"


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(" ", "").replace(",", "."))
        except ValueError:
            return None
    return None


class RoistatAdapter:
    """Bounded Roistat REST adapter.

    Reads use official documented methods only. Writes are a fail-closed
    allowlist of single-object CRM mutations. Advertising-platform and CRM-
    integration create/delete have no official REST method and are rejected.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = OFFICIAL_BASE_URL,
        *,
        project_allowlist: str = "",
        write_operations: str = "",
        http: JsonRequester | None = None,
        coalescer: AsyncSingleFlight | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = _validate_base_url(base_url)
        self.project_allowlist = _parse_csv_ids(project_allowlist)
        configured = _parse_csv_ops(write_operations)
        self.write_operations = (
            DEFAULT_WRITE_OPERATIONS if not configured else frozenset(configured & set(WRITE_ALLOWLIST))
        )
        self.http = http or JsonHttpClient(timeout=timeout)
        self.coalescer = coalescer or AsyncSingleFlight()
        self._windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._last_rate_limited_at: float | None = None
        self._last_retry_after: int | None = None
        self._snapshots: dict[int, dict[str, Any]] = {}

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider": "roistat",
            "official_mcp": {
                "url": "https://mcp.roistat.com/mcp",
                "mode": "read_only",
                "proxied": False,
                "evidence": "official_mcp_read",
            },
            "rest_host": OFFICIAL_HOST,
            "auth": "Api-key header",
            "limits": {
                "official": {"per_second": 10, "per_minute": 100, "per_hour": 5000},
                "local": {
                    "per_second": LOCAL_MAX_PER_SECOND,
                    "per_minute": LOCAL_MAX_PER_MINUTE,
                    "per_hour": LOCAL_MAX_PER_HOUR,
                    "governor_per_minute": LOCAL_MAX_PER_MINUTE,
                    "max_concurrency": 1,
                    "get_daily_per_hour": DAILY_STATS_MAX_PER_HOUR,
                },
            },
            "reads": sorted(READ_SPECS),
            "writes": {
                name: {"risk": spec.risk, "enabled_when_flag_on": name in self.write_operations}
                for name, spec in WRITE_ALLOWLIST.items()
            },
            "unsupported_by_official_api": sorted(UNSUPPORTED_WRITES),
            "project_allowlist_configured": bool(self.project_allowlist),
            "matrix": "docs/ROISTAT_API_CAPABILITY_MATRIX.md",
        }

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ProviderError("Roistat API key is not configured")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Api-key": self.api_key,
            "Use-Http-Code": "1",
            "User-Agent": "ZAI-MCP-Platform/0.1.0 Roistat",
        }

    def authorize_project(self, project_id: object, *, writing: bool = False) -> str:
        normalized = str(_positive_int(project_id, "project_id", MAX_PROJECT_ID))
        if self.project_allowlist and int(normalized) not in self.project_allowlist:
            raise PermissionError("Roistat project is outside the server allowlist")
        if writing and not self.project_allowlist:
            raise PermissionError("Roistat writes require a configured project allowlist")
        return normalized

    def _url(self, segments: tuple[str, ...], path_ids: Mapping[str, str] | None = None) -> str:
        parts: list[str] = []
        for segment in segments:
            if segment.startswith("{") and segment.endswith("}"):
                key = segment[1:-1]
                value = (path_ids or {}).get(key)
                if value is None or _OBJECT_ID.fullmatch(value) is None:
                    raise ValueError("Roistat path identifier is invalid")
                parts.append(value)
                continue
            if _PATH_SEGMENT.fullmatch(segment) is None or "/" in segment or ".." in segment:
                raise ValueError("Roistat path segment is not allowlisted")
            parts.append(segment)
        return f"{self.base_url}/{'/'.join(parts)}"

    async def _admit(self, bucket: str, operation: str) -> None:
        now = time.monotonic()
        async with self._lock:
            for window, limit in (
                ("second", LOCAL_MAX_PER_SECOND),
                ("minute", LOCAL_MAX_PER_MINUTE),
                ("hour", LOCAL_MAX_PER_HOUR),
            ):
                span = {"second": 1.0, "minute": 60.0, "hour": 3600.0}[window]
                events = self._windows[(bucket, window)]
                while events and now - events[0] >= span:
                    events.popleft()
                if len(events) >= limit:
                    self._last_rate_limited_at = now
                    self._last_retry_after = 60 if window != "second" else 1
                    raise ProviderRateLimited(
                        "Roistat local rate limit reached",
                        retry_after_seconds=self._last_retry_after,
                    )
            if operation == "statistics_daily":
                daily = self._windows[(bucket, "daily_hour")]
                while daily and now - daily[0] >= 3600.0:
                    daily.popleft()
                if len(daily) >= DAILY_STATS_MAX_PER_HOUR:
                    self._last_rate_limited_at = now
                    self._last_retry_after = 1200
                    raise ProviderRateLimited(
                        "Roistat get-daily hour cap reached",
                        retry_after_seconds=1200,
                    )
                daily.append(now)
            for window in ("second", "minute", "hour"):
                self._windows[(bucket, window)].append(now)

    def _validate_response(self, response: dict[str, Any]) -> dict[str, Any]:
        status = str(response.get("status", "")).lower()
        error = response.get("error") or response.get("error_code")
        if status in {"error", "fail", "failed"} or error:
            code = error if isinstance(error, str) else status
            safe = code if isinstance(code, str) and _SAFE_ERROR.fullmatch(code) else ""
            if safe in {"authentication_failed", "authorization_failed", "access_denied"}:
                raise ProviderAuthenticationError(401 if "auth" in safe else 403)
            if safe == "request_limit_error":
                raise ProviderRateLimited("provider returned request_limit_error", retry_after_seconds=60)
            if safe == "resource_not_found":
                raise ProviderNotFoundError(404)
            if safe in {"internal_error", "unknown_error"}:
                raise ProviderTransientHttpError(500)
            raise ProviderError("Roistat returned an application error" + (f" code={safe}" if safe else ""))
        return cast(dict[str, Any], _redact_pii(response))

    async def _call(
        self,
        operation: str,
        *,
        project_id: str | None = None,
        payload: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        path_ids: Mapping[str, str] | None = None,
        idempotent: bool = True,
    ) -> dict[str, Any]:
        spec = READ_SPECS[operation]
        if spec.needs_project:
            if project_id is None:
                raise ValueError("project_id is required")
            self.authorize_project(project_id)
        query = dict(params or {})
        if spec.needs_project:
            query["project"] = project_id
        url = self._url(spec.segments, path_ids)

        async def fetch() -> dict[str, Any]:
            await self._admit(project_id or "account", operation)
            try:
                response = await self.http.request(
                    spec.method,
                    url,
                    headers=self._headers(),
                    payload=payload,
                    params=query or None,
                    idempotent=idempotent,
                    **({"array_response": True} if spec.array_response else {}),
                )
            except ProviderRateLimited as exc:
                self._last_rate_limited_at = time.monotonic()
                self._last_retry_after = exc.retry_after_seconds
                raise
            except ProviderHttpError:
                raise
            return self._validate_response(response)

        if not idempotent:
            return await fetch()
        key = request_hash(
            {
                "provider": "roistat",
                "operation": operation,
                "project_id": project_id,
                "payload": payload,
                "params": query,
                "path_ids": dict(path_ids or {}),
            }
        )
        return await self.coalescer.run(key, fetch)

    def _page(self, limit: int, offset: int) -> tuple[int, int]:
        return (
            _positive_int(limit, "limit", MAX_LIMIT),
            _non_negative_int(offset, "offset", MAX_OFFSET),
        )

    def _filters(
        self,
        value: object,
        *,
        allowed_fields: frozenset[str],
        extra_status: frozenset[str] | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return {"and": [self._filter_triple(item, allowed_fields, extra_status) for item in value]}
        if not isinstance(value, Mapping) or set(value) - {"and", "or"}:
            raise ValueError("filters must be a list or an and/or object")
        if len(value) != 1:
            raise ValueError("filters must contain exactly one of and/or")
        key, items = next(iter(value.items()))
        if not isinstance(items, list) or not items or len(items) > 8:
            raise ValueError("filters must contain between 1 and 8 clauses")
        return {key: [self._filter_triple(item, allowed_fields, extra_status) for item in items]}

    def _filter_triple(
        self,
        item: object,
        allowed_fields: frozenset[str],
        extra_status: frozenset[str] | None,
    ) -> list[Any]:
        if not isinstance(item, list) or len(item) != 3:
            raise ValueError("each filter must be [field, operator, value]")
        field, operator, raw = item
        if not isinstance(field, str) or field not in allowed_fields:
            raise ValueError("unsupported Roistat filter field")
        if not isinstance(operator, str) or operator not in ALLOWED_FILTER_OPS:
            raise ValueError("unsupported Roistat filter operator")
        if operator in {"in", "not_in"}:
            if not isinstance(raw, list) or not raw or len(raw) > 20:
                raise ValueError("in-filter values must contain between 1 and 20 items")
            values = [self._filter_value(field, entry, extra_status) for entry in raw]
            return [field, operator, values]
        return [field, operator, self._filter_value(field, raw, extra_status)]

    def _filter_value(self, field: str, raw: object, extra_status: frozenset[str] | None) -> str:
        if not isinstance(raw, str | int) or isinstance(raw, bool):
            raise ValueError("filter value must be a string or integer")
        text = str(raw).strip()
        if not text or len(text) > 128:
            raise ValueError("filter value is out of bounds")
        if field == "status" and extra_status is not None and text not in extra_status:
            raise ValueError("unsupported status filter")
        return text

    def validate_projects(self) -> dict[str, Any]:
        return {}

    async def list_projects(self) -> dict[str, Any]:
        response = await self._call("list_projects")
        projects = response.get("projects")
        items = projects if isinstance(projects, list) else []
        if self.project_allowlist:
            allowed = set(self.project_allowlist)
            items = [
                item for item in items if isinstance(item, Mapping) and int(item.get("id", 0) or 0) in allowed
            ]
        safe_items = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            safe_items.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "currency": item.get("currency"),
                    "is_owner": item.get("is_owner"),
                    "creation_date": item.get("creation_date"),
                    "profit": item.get("profit"),
                }
            )
        return {
            "projects": safe_items,
            "total": len(safe_items),
            "completeness": _completeness(safe_items, len(safe_items), limit=None),
            "status": response.get("status", "success"),
        }

    def validate_analytics(
        self,
        project_id: object,
        metrics: object,
        dimensions: object,
        period: object,
        *,
        attribution: object = None,
        interval: object = None,
    ) -> dict[str, Any]:
        project = self.authorize_project(project_id)
        if not isinstance(metrics, Sequence) or isinstance(metrics, str | bytes) or not metrics:
            raise ValueError("metrics must be a non-empty list")
        if len(metrics) > MAX_METRICS:
            raise ValueError(f"metrics must contain at most {MAX_METRICS} items")
        if not isinstance(dimensions, Sequence) or isinstance(dimensions, str | bytes) or not dimensions:
            raise ValueError("dimensions must be a non-empty list")
        if len(dimensions) > MAX_DIMENSIONS:
            raise ValueError(f"dimensions must contain at most {MAX_DIMENSIONS} items")
        if not isinstance(period, Mapping):
            raise ValueError("period must be an object")
        normalized_metrics: list[Any] = []
        for item in metrics:
            if isinstance(item, str):
                name = item.strip()
                if name not in ALLOWED_METRICS:
                    raise ValueError("unsupported Roistat metric")
                if name not in normalized_metrics:
                    normalized_metrics.append(name)
                continue
            if not isinstance(item, Mapping):
                raise ValueError("metric must be a name or {metric, attribution}")
            name = str(item.get("metric", "")).strip()
            model = str(item.get("attribution", "default")).strip()
            if name not in ALLOWED_METRICS or model not in ALLOWED_ATTRIBUTIONS:
                raise ValueError("unsupported Roistat metric or attribution")
            normalized_metrics.append({"metric": name, "attribution": model})
        normalized_dimensions: list[str] = []
        for item in dimensions:
            if not isinstance(item, str) or item not in ALLOWED_DIMENSIONS:
                raise ValueError("unsupported Roistat dimension")
            if item not in normalized_dimensions:
                normalized_dimensions.append(item)
        payload: dict[str, Any] = {
            "metrics": normalized_metrics,
            "dimensions": normalized_dimensions,
            "period": _bounded_period(period, max_days=MAX_PERIOD_DAYS_ANALYTICS),
        }
        if attribution is not None:
            model = str(attribution).strip()
            if model not in ALLOWED_ATTRIBUTIONS:
                raise ValueError("unsupported attribution model")
            payload["metrics"] = [
                item if isinstance(item, Mapping) else {"metric": item, "attribution": model}
                for item in normalized_metrics
            ]
        if interval is not None:
            text = str(interval).strip()
            if text not in ALLOWED_INTERVALS:
                raise ValueError("interval must be one of 1d, 1w, 1m")
            payload["interval"] = text
        return {"project_id": project, "payload": payload}

    def validate_discovery(self, project_id, dimension=None, limit=100):
        project = self.authorize_project(project_id)
        _positive_int(limit, "limit", 200)
        if dimension is not None and dimension not in ALLOWED_DIMENSIONS:
            raise ValueError("unsupported Roistat dimension")
        return project

    async def analytics_dimension_values(self, project_id, dimension, limit=100):
        project = self.validate_discovery(project_id, dimension, limit)
        raw = await self._call(
            "analytics_dimension_values", project_id=project, params={"dimension": dimension}
        )
        rows = raw.get("values")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ProviderError("invalid dimension values response")
        return {
            "project_id": project,
            "dimension": dimension,
            "values": rows[:limit],
            "returned_count": min(len(rows), limit),
            "available_in_response": len(rows),
            "truncated": len(rows) > limit,
            "completeness": "partial",
            "source": "project/analytics/dimension-values",
        }

    async def analytics_custom_metrics(self, project_id, limit=100):
        project = self.validate_discovery(project_id, limit=limit)
        raw = await self._call("analytics_custom_metrics", project_id=project)
        rows = raw.get("data")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ProviderError("invalid custom metrics response")
        return {
            "project_id": project,
            "metrics": rows[:limit],
            "returned_count": min(len(rows), limit),
            "available_in_response": len(rows),
            "truncated": len(rows) > limit,
            "completeness": "partial",
            "source": "project/analytics/metrics/custom/list",
        }

    async def analytics_catalog(self, project_id: object) -> dict[str, Any]:
        project = self.authorize_project(project_id)
        metrics = await self._call("analytics_metrics", project_id=project)
        dimensions = await self._call("analytics_dimensions", project_id=project)
        models = await self._call("analytics_attribution", project_id=project)

        def names(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
            rows = payload.get(key) or payload.get("data") or []
            result: list[dict[str, Any]] = []
            if not isinstance(rows, list):
                return result
            for item in rows:
                if not isinstance(item, Mapping):
                    continue
                name = item.get("name") or item.get("id")
                if not isinstance(name, str):
                    continue
                result.append({"name": name, "title": item.get("title"), "group": item.get("group")})
            return result[:200]

        return {
            "project_id": project,
            "metrics": names(metrics, "metrics"),
            "dimensions": names(dimensions, "dimensions"),
            "attribution_models": names(models, "models") or names(models, "data"),
            "queryable_metrics": sorted(ALLOWED_METRICS),
            "queryable_dimensions": sorted(ALLOWED_DIMENSIONS),
            "completeness": "partial",
        }

    async def analytics_report(
        self,
        project_id: object,
        metrics: object,
        dimensions: object,
        period: object,
        attribution: object = None,
        interval: object = None,
    ) -> dict[str, Any]:
        validated = self.validate_analytics(
            project_id,
            metrics,
            dimensions,
            period,
            attribution=attribution,
            interval=interval,
        )
        response = await self._call(
            "analytics_data",
            project_id=validated["project_id"],
            payload=validated["payload"],
        )
        data = response.get("data")
        blocks = data if isinstance(data, list) else []
        rows: list[Any] = []
        for block in blocks:
            if isinstance(block, Mapping) and isinstance(block.get("items"), list):
                rows.extend(block["items"])
        return {
            "project_id": validated["project_id"],
            "period": validated["payload"]["period"],
            "items": rows[:MAX_LIMIT],
            "raw_blocks": len(blocks),
            "completeness": _completeness(rows, None, limit=MAX_LIMIT),
            "status": response.get("status", "success"),
        }

    async def analytics_compare(
        self,
        project_id: object,
        metrics: object,
        dimensions: object,
        current_period: object,
        previous_period: object,
        attribution: object = None,
    ) -> dict[str, Any]:
        current = await self.analytics_report(
            project_id, metrics, dimensions, current_period, attribution=attribution
        )
        previous = await self.analytics_report(
            project_id, metrics, dimensions, previous_period, attribution=attribution
        )

        def metric_map(item: Mapping[str, Any]) -> dict[str, float | None]:
            values: dict[str, float | None] = {}
            rows = item.get("metrics")
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, Mapping):
                        name = str(row.get("metric_name") or row.get("metric") or "")
                        values[name] = _numeric(row.get("value"))
            return values

        def dim_key(item: Mapping[str, Any]) -> str:
            dims = item.get("dimensions")
            if isinstance(dims, Mapping):
                return request_hash({key: dims[key] for key in sorted(dims)})
            return "row"

        previous_by_key = {
            dim_key(item): metric_map(item) for item in previous["items"] if isinstance(item, Mapping)
        }
        deltas: list[dict[str, Any]] = []
        for item in current["items"]:
            if not isinstance(item, Mapping):
                continue
            key = dim_key(item)
            now = metric_map(item)
            then = previous_by_key.get(key, {})
            changes: dict[str, Any] = {}
            for name, value in now.items():
                prior = then.get(name)
                if value is None or prior is None:
                    changes[name] = {"current": value, "previous": prior, "delta": None, "state": "unknown"}
                    continue
                changes[name] = {
                    "current": value,
                    "previous": prior,
                    "delta": value - prior,
                    "state": "compared",
                }
            deltas.append({"dimensions": item.get("dimensions"), "metrics": changes})
        return {
            "project_id": current["project_id"],
            "current": {"period": current["period"], "completeness": current["completeness"]},
            "previous": {"period": previous["period"], "completeness": previous["completeness"]},
            "items": deltas,
            "completeness": (
                "unknown"
                if current["completeness"] == "unknown" or previous["completeness"] == "unknown"
                else "partial"
                if "partial" in {current["completeness"], previous["completeness"]}
                else "complete"
            ),
        }

    def validate_statistics(
        self, project_id: object, period: object, time_zone: object = None, channel: object = None
    ) -> dict[str, Any]:
        project = self.authorize_project(project_id)
        if not isinstance(period, str):
            raise ValueError("statistics period must be YYYY-MM-DD-YYYY-MM-DD")
        normalized, _, _ = _parse_daily_period(period)
        payload: dict[str, Any] = {"period": normalized}
        if time_zone is not None:
            zone = str(time_zone).strip()
            if zone not in ALLOWED_TIMEZONES:
                raise ValueError("unsupported time_zone")
            payload["time_zone"] = zone
        if channel is not None:
            name = str(channel).strip()
            if _CHANNEL.fullmatch(name) is None:
                raise ValueError("channel must be a documented system name")
            payload["channel"] = name
        return {"project_id": project, "payload": payload}

    async def statistics_daily(
        self,
        project_id: object,
        period: object,
        time_zone: object = None,
        channel: object = None,
    ) -> dict[str, Any]:
        validated = self.validate_statistics(project_id, period, time_zone, channel)
        response = await self._call(
            "statistics_daily",
            project_id=validated["project_id"],
            payload=validated["payload"],
        )
        items = response.get("StatisticsItems")
        rows = items if isinstance(items, list) else []
        last_date = None
        if rows and isinstance(rows[-1], Mapping):
            last_date = rows[-1].get("dateEnd") or rows[-1].get("dateStart")
        return {
            "project_id": validated["project_id"],
            "period": validated["payload"]["period"],
            "items": rows[:366],
            "summary": response.get("SummaryItem"),
            "average": response.get("AverageItem"),
            "last_available_date": last_date,
            "completeness": _completeness(rows, None, limit=None),
            "status": response.get("status", "success"),
        }

    def validate_list(
        self,
        project_id: object,
        *,
        limit: int,
        offset: int,
        period: object | None = None,
        filters: object | None = None,
        allowed_fields: frozenset[str] = ALLOWED_ORDER_FILTER_FIELDS,
        extra_status: frozenset[str] | None = None,
        require_period: bool = False,
    ) -> dict[str, Any]:
        project = self.authorize_project(project_id)
        page_limit, page_offset = self._page(limit, offset)
        payload: dict[str, Any] = {"limit": page_limit, "offset": page_offset}
        query: dict[str, Any] = {}
        if period is not None:
            if isinstance(period, str):
                normalized, _, _ = _parse_daily_period(period)
                query["period"] = normalized
            elif isinstance(period, Mapping):
                payload["period"] = _bounded_period(period, max_days=MAX_PERIOD_DAYS_LIST)
            else:
                raise ValueError("period is invalid")
        elif require_period:
            raise ValueError("period is required")
        normalized_filters = self._filters(filters, allowed_fields=allowed_fields, extra_status=extra_status)
        if normalized_filters is not None:
            payload["filters"] = normalized_filters
        return {
            "project_id": project,
            "payload": payload,
            "params": query,
            "limit": page_limit,
            "offset": page_offset,
        }

    async def list_orders(
        self,
        project_id: object,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        filters: object | None = None,
    ) -> dict[str, Any]:
        validated = self.validate_list(
            project_id,
            limit=limit,
            offset=offset,
            filters=filters,
            allowed_fields=ALLOWED_ORDER_FILTER_FIELDS,
        )
        response = await self._call(
            "list_orders", project_id=validated["project_id"], payload=validated["payload"]
        )
        items = _items_of(response, "data")
        return {
            "project_id": validated["project_id"],
            "items": items[: validated["limit"]],
            "total": response.get("total"),
            "limit": validated["limit"],
            "offset": validated["offset"],
            "completeness": _completeness(items, response.get("total"), limit=validated["limit"]),
            "status": response.get("status", "success"),
        }

    async def get_order(self, project_id: object, order_id: object) -> dict[str, Any]:
        project = self.authorize_project(project_id)
        identifier = _object_id(order_id, "order_id")
        response = await self._call("get_order", project_id=project, path_ids={"order_id": identifier})
        return {
            "project_id": project,
            "order_id": identifier,
            "order": response.get("order"),
            "visits": response.get("visits") if isinstance(response.get("visits"), list) else [],
            "products": response.get("products") if isinstance(response.get("products"), list) else [],
            "completeness": "unknown" if response.get("order") in (None, {}) else "complete",
            "status": response.get("status", "success"),
        }

    async def list_order_statuses(self, project_id: object) -> dict[str, Any]:
        project = self.authorize_project(project_id)
        response = await self._call("list_order_statuses", project_id=project)
        items = _items_of(response, "data", "statuses")
        return {
            "project_id": project,
            "items": items[:200],
            "total": response.get("total", len(items)),
            "completeness": _completeness(items, response.get("total"), limit=200),
            "status": response.get("status", "success"),
        }

    async def list_leads(
        self,
        project_id: object,
        period: object,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        validated = self.validate_list(
            project_id, limit=limit, offset=offset, period=period, require_period=True
        )
        response = await self._call(
            "list_leads",
            project_id=validated["project_id"],
            params=validated["params"],
        )
        items = response.get("ProxyLeads")
        rows = items if isinstance(items, list) else []
        sliced = rows[validated["offset"] : validated["offset"] + validated["limit"]]
        return {
            "project_id": validated["project_id"],
            "period": validated["params"].get("period"),
            "items": sliced,
            "total": len(rows) if rows else response.get("total"),
            "limit": validated["limit"],
            "offset": validated["offset"],
            "completeness": _completeness(rows, len(rows) if rows else None, limit=validated["limit"]),
            "status": response.get("status", "success"),
        }

    async def get_lead(self, project_id: object, lead_id: object) -> dict[str, Any]:
        project = self.authorize_project(project_id)
        identifier = _object_id(lead_id, "lead_id")
        response = await self._call("get_lead", project_id=project, path_ids={"lead_id": identifier})
        lead = response.get("ProxyLead")
        return {
            "project_id": project,
            "lead_id": identifier,
            "lead": lead,
            "completeness": "unknown" if lead in (None, {}) else "complete",
            "status": response.get("status", "success"),
        }

    async def list_lead_duplicates(
        self, project_id: object, period: object, *, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> dict[str, Any]:
        validated = self.validate_list(
            project_id, limit=limit, offset=offset, period=period, require_period=True
        )
        response = await self._call(
            "list_lead_duplicates",
            project_id=validated["project_id"],
            params=validated["params"],
        )
        items = response.get("ProxyLeads")
        rows = items if isinstance(items, list) else []
        sliced = rows[validated["offset"] : validated["offset"] + validated["limit"]]
        return {
            "project_id": validated["project_id"],
            "period": validated["params"].get("period"),
            "items": sliced,
            "total": len(rows) if rows else response.get("total"),
            "completeness": _completeness(rows, len(rows) if rows else None, limit=validated["limit"]),
            "status": response.get("status", "success"),
        }

    async def list_calls(
        self,
        project_id: object,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        filters: object | None = None,
    ) -> dict[str, Any]:
        validated = self.validate_list(
            project_id,
            limit=limit,
            offset=offset,
            filters=filters,
            allowed_fields=ALLOWED_CALL_FILTER_FIELDS,
            extra_status=ALLOWED_CALL_STATUSES,
        )
        response = await self._call(
            "list_calls", project_id=validated["project_id"], payload=validated["payload"]
        )
        items = _items_of(response, "data")
        return {
            "project_id": validated["project_id"],
            "items": items[: validated["limit"]],
            "total": response.get("total"),
            "limit": validated["limit"],
            "offset": validated["offset"],
            "completeness": _completeness(items, response.get("total"), limit=validated["limit"]),
            "status": response.get("status", "success"),
        }

    async def calltracking_summary(self, project_id: object, period: object) -> dict[str, Any]:
        project = self.authorize_project(project_id)
        if isinstance(period, Mapping):
            payload = {"period": _bounded_period(period, max_days=MAX_PERIOD_DAYS_LIST)}
        elif isinstance(period, str):
            _normalized, start, finish = _parse_daily_period(period)
            payload = {
                "period": {
                    "from": f"{start.isoformat()}T00:00:00+0000",
                    "to": f"{finish.isoformat()}T23:59:59+0000",
                }
            }
        else:
            raise ValueError("period is required")
        response = await self._call("calltracking_summary", project_id=project, payload=payload)
        data = response.get("data")
        return {
            "project_id": project,
            "data": data if isinstance(data, Mapping) else {},
            "completeness": "unknown" if data in (None, {}, []) else "complete",
            "status": response.get("status", "success"),
        }

    async def list_visits(
        self,
        project_id: object,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        filters: object | None = None,
    ) -> dict[str, Any]:
        validated = self.validate_list(
            project_id,
            limit=limit,
            offset=offset,
            filters=filters,
            allowed_fields=ALLOWED_VISIT_FILTER_FIELDS,
        )
        response = await self._call(
            "list_visits", project_id=validated["project_id"], payload=validated["payload"]
        )
        items = _items_of(response, "data")
        return {
            "project_id": validated["project_id"],
            "items": items[: validated["limit"]],
            "total": response.get("total"),
            "limit": validated["limit"],
            "offset": validated["offset"],
            "completeness": _completeness(items, response.get("total"), limit=validated["limit"]),
            "status": response.get("status", "success"),
        }

    async def list_clients(
        self,
        project_id: object,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        filters: object | None = None,
    ) -> dict[str, Any]:
        validated = self.validate_list(
            project_id,
            limit=limit,
            offset=offset,
            filters=filters,
            allowed_fields=ALLOWED_CLIENT_FILTER_FIELDS,
        )
        response = await self._call(
            "list_clients", project_id=validated["project_id"], payload=validated["payload"]
        )
        items = response.get("clients")
        rows = items if isinstance(items, list) else _items_of(response, "data")
        return {
            "project_id": validated["project_id"],
            "items": rows[: validated["limit"]],
            "total": response.get("total"),
            "limit": validated["limit"],
            "offset": validated["offset"],
            "completeness": _completeness(rows, response.get("total"), limit=validated["limit"]),
            "status": response.get("status", "success"),
        }

    def validate_funnel(self, project_id: object, period: object, funnel: object) -> dict[str, Any]:
        project = self.authorize_project(project_id)
        if not isinstance(period, Mapping):
            raise ValueError("period must be an object")
        if not isinstance(funnel, Sequence) or isinstance(funnel, str | bytes) or not funnel:
            raise ValueError("funnel must be a non-empty list")
        if len(funnel) > MAX_FUNNEL_STAGES:
            raise ValueError(f"funnel must contain at most {MAX_FUNNEL_STAGES} stages")
        stages: list[dict[str, Any]] = []
        for index, stage in enumerate(funnel):
            if not isinstance(stage, Mapping):
                raise ValueError("funnel stage must be an object")
            title = stage.get("title")
            statuses = stage.get("statuses")
            if not isinstance(title, str) or not title.strip() or len(title) > 64:
                raise ValueError("funnel title is invalid")
            if not isinstance(statuses, list) or not statuses or len(statuses) > MAX_FUNNEL_STATUSES:
                raise ValueError("funnel statuses are out of bounds")
            safe_statuses = [_object_id(item, "status_id") for item in statuses]
            stages.append({"title": title.strip(), "statuses": safe_statuses, "order": str(index + 1)})
        return {
            "project_id": project,
            "payload": {
                "period": _bounded_period(period, max_days=MAX_PERIOD_DAYS_ANALYTICS),
                "funnel": stages,
                "dimensions": ["marker_level_1"],
            },
        }

    async def funnel(self, project_id: object, period: object, funnel: object) -> dict[str, Any]:
        validated = self.validate_funnel(project_id, period, funnel)
        response = await self._call(
            "funnel", project_id=validated["project_id"], payload=validated["payload"]
        )
        data = response.get("data")
        items: list[Any] = []
        if isinstance(data, Mapping) and isinstance(data.get("items"), list):
            items = data["items"]
        elif isinstance(data, list):
            items = data
        return {
            "project_id": validated["project_id"],
            "items": items[:MAX_LIMIT],
            "completeness": _completeness(items, None, limit=MAX_LIMIT),
            "status": response.get("status", "success"),
        }

    async def health_indicators(self, project_id: object, messages_per_indicator: int = 3) -> dict[str, Any]:
        """Official project-state processes (``GET /project/health/indicator/list``)."""
        project = self.authorize_project(project_id)
        keep = _positive_int(messages_per_indicator, "messages_per_indicator", MAX_INDICATOR_MESSAGES)
        response = await self._call("health_indicators", project_id=project)
        groups = response.get("data")
        if not isinstance(groups, list):
            raise ProviderError("invalid health indicator response")
        counts = {"ok": 0, "errors": 0, "not_finished": 0, "unknown": 0}
        categories: list[dict[str, Any]] = []
        for group in groups[:MAX_INDICATOR_GROUPS]:
            if not isinstance(group, Mapping):
                continue
            indicators: list[dict[str, Any]] = []
            raw_indicators = group.get("indicators")
            for item in (raw_indicators if isinstance(raw_indicators, list) else [])[:MAX_INDICATORS]:
                if not isinstance(item, Mapping):
                    continue
                state = _indicator_state(item.get("status"))
                counts[state] += 1
                messages = item.get("messages") if isinstance(item.get("messages"), list) else []
                indicators.append(
                    {
                        "id": _indicator_scalar(item.get("id")),
                        "name": _indicator_text(item.get("name")),
                        "state": state,
                        "status_code": _indicator_scalar(item.get("status")),
                        "is_running": _indicator_flag(item.get("is_running")),
                        "is_executable": _indicator_flag(item.get("is_executable")),
                        "messages": [
                            {
                                "state": _indicator_state(message.get("s")),
                                "message": _indicator_text(message.get("m")),
                                "date": _indicator_text(message.get("d"), MAX_INDICATOR_DATE),
                            }
                            for message in messages[:keep]
                            if isinstance(message, Mapping)
                        ],
                        "messages_truncated": len(messages) > keep,
                    }
                )
            categories.append({"category": _indicator_text(group.get("name")), "indicators": indicators})
        healthy = None if not any(counts.values()) else counts["errors"] == 0 and counts["not_finished"] == 0
        return {
            "project_id": project,
            "categories": categories,
            "summary": {**counts, "healthy": healthy},
            "completeness": "unknown" if not categories else "complete",
            "source": "project/health/indicator/list",
            "status": response.get("status", "success"),
        }

    async def list_channels(self, project_id: object, limit: int = 200) -> dict[str, Any]:
        """Advertising channels used in the project (``POST /project/analytics/source/list``)."""
        project = self.authorize_project(project_id)
        page = _positive_int(limit, "limit", MAX_CATALOG_ROWS)
        response = await self._call("list_channels", project_id=project)
        items = _items_of(response, "data")
        return {
            "project_id": project,
            "items": items[:page],
            "total": response.get("total", len(items)),
            "returned_count": min(len(items), page),
            "truncated": len(items) > page,
            "completeness": _completeness(items, response.get("total"), limit=page),
            "source": "project/analytics/source/list",
            "status": response.get("status", "success"),
        }

    async def list_channel_costs(
        self,
        project_id: object,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Manually entered channel costs (``POST /project/analytics/source/cost/list``).

        The provider returns every cost ever entered; slicing and the optional
        ``source`` prefix filter are applied locally.
        """
        project = self.authorize_project(project_id)
        page_limit, page_offset = self._page(limit, offset)
        if source is not None and (not isinstance(source, str) or _CHANNEL.fullmatch(source) is None):
            raise ValueError("source must be a Roistat channel system name")
        response = await self._call("list_channel_costs", project_id=project)
        rows = _items_of(response, "data")
        if source:
            rows = [
                row
                for row in rows
                if isinstance(row, Mapping) and str(row.get("source", "")).startswith(source)
            ]
        window = rows[page_offset : page_offset + page_limit]
        return {
            "project_id": project,
            "items": window,
            "matched": len(rows),
            "limit": page_limit,
            "offset": page_offset,
            "source_filter": source,
            "truncated": page_offset + page_limit < len(rows),
            "completeness": "unknown" if not rows else "complete",
            "source": "project/analytics/source/cost/list",
        }

    async def list_managers(self, project_id: object, limit: int = 200) -> dict[str, Any]:
        """CRM managers known to the project; email and phone are redacted."""
        project = self.authorize_project(project_id)
        page = _positive_int(limit, "limit", MAX_CATALOG_ROWS)
        response = await self._call("list_managers", project_id=project)
        items = _items_of(response, "data")
        return {
            "project_id": project,
            "items": items[:page],
            "total": response.get("total", len(items)),
            "returned_count": min(len(items), page),
            "truncated": len(items) > page,
            "completeness": _completeness(items, response.get("total"), limit=page),
            "source": "project/integration/manager/list",
            "status": response.get("status", "success"),
        }

    async def extra_read(
        self,
        kind: str,
        project_id: object,
        *,
        is_deleted: bool | None = None,
        client_id: str | None = None,
        event_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Calltracking scripts/phones, events log, one client's activity feed; PII is redacted."""
        if kind not in EXTRA_READS:
            raise ValueError("kind must be one of: " + ", ".join(EXTRA_READS))
        project = self.authorize_project(project_id)
        page = _positive_int(limit, "limit", MAX_CATALOG_ROWS)
        payload: dict[str, Any] | None = None
        params: dict[str, Any] | None = None
        if kind == "calltracking_scripts" and is_deleted is not None:
            payload = {"is_deleted": int(bool(is_deleted))}
        if kind == "events_log":
            body: dict[str, Any] = {}
            if event_name is not None:
                if not isinstance(event_name, str) or not event_name.strip() or len(event_name) > 256:
                    raise ValueError("event_name must be a non-empty string up to 256 chars")
                body["name"] = event_name
            for key, value in (("date_from", date_from), ("date_to", date_to)):
                if value is not None:
                    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
                        raise ValueError(f"{key} must be ISO 8601, e.g. 2026-10-01T00:00:00Z")
                    body[key] = value
            payload = body or None
        if kind == "client_feed":
            if not isinstance(client_id, str) or _OBJECT_ID.fullmatch(client_id) is None:
                raise ValueError("client_feed requires client_id")
            params = {"client": client_id}
        response = await self._call(kind, project_id=project, payload=payload, params=params)
        items = _items_of(response, "data", "items", "feed", "scripts", "phones")
        return {
            "project_id": project,
            "kind": kind,
            "items": _redact_pii(items[:page]),
            "total": response.get("total", len(items)),
            "returned_count": min(len(items), page),
            "truncated": len(items) > page,
            "completeness": _completeness(items, response.get("total"), limit=page),
            "source": "/".join(READ_SPECS[kind].segments),
        }

    def rate_limit_state(self) -> dict[str, Any]:
        return {
            "limited": self._last_rate_limited_at is not None
            and (time.monotonic() - self._last_rate_limited_at) < 60,
            "retry_after_seconds": self._last_retry_after,
        }

    async def health(self, project_id: object | None = None) -> dict[str, Any]:
        auth = {"reachable": False, "authenticated": False}
        freshness: dict[str, Any] = {"last_available_date": None, "state": "unknown"}
        try:
            projects = await self.list_projects()
            auth = {"reachable": True, "authenticated": True}
        except ProviderAuthenticationError:
            return {
                "auth": {"reachable": True, "authenticated": False},
                "freshness": freshness,
                "completeness": "unknown",
                "rate_limit": self.rate_limit_state(),
                "drift": None,
            }
        except ProviderError:
            return {
                "auth": auth,
                "freshness": freshness,
                "completeness": "unknown",
                "rate_limit": self.rate_limit_state(),
                "drift": None,
            }
        snapshot = {
            "project_ids": [item.get("id") for item in projects["projects"]],
            "count": projects["total"],
        }
        project = "0"
        if project_id is not None:
            project = self.authorize_project(project_id)
            end = date.today()
            start = end - timedelta(days=6)
            period = f"{start.isoformat()}-{end.isoformat()}"
            try:
                stats = await self.statistics_daily(project, period, time_zone="UTC")
                freshness = {
                    "last_available_date": stats.get("last_available_date"),
                    "state": stats["completeness"],
                    "source": "statistics_daily",
                }
                snapshot["last_available_date"] = stats.get("last_available_date")
                snapshot["project_id"] = project
            except ProviderRateLimited:
                freshness = {"last_available_date": None, "state": "partial", "source": "rate_limited"}
            except ProviderError:
                freshness = {"last_available_date": None, "state": "unknown", "source": "statistics_daily"}
        snapshot_key = int(project) if project_id is not None else 0
        previous = self._snapshots.get(snapshot_key)
        drift = None
        if previous is not None:
            drift = {
                "changed": previous != snapshot,
                "previous_count": previous.get("count"),
                "current_count": snapshot.get("count"),
                "last_available_date": {
                    "previous": previous.get("last_available_date"),
                    "current": snapshot.get("last_available_date"),
                },
            }
        self._snapshots[snapshot_key] = snapshot
        return {
            "auth": auth,
            "freshness": freshness,
            "completeness": projects["completeness"]
            if project_id is None
            else freshness.get("state", "unknown"),
            "rate_limit": self.rate_limit_state(),
            "drift": drift,
            "projects": projects["total"],
        }

    @staticmethod
    def risk_tier(operation: str) -> str:
        if operation in UNSUPPORTED_WRITES:
            return "high"
        spec = WRITE_ALLOWLIST.get(str(operation).strip())
        return spec.risk if spec is not None else "unknown"

    def validate_write(
        self, operation: str, project_id: object, payload: dict[str, Any] | None
    ) -> dict[str, Any]:
        name = str(operation).strip()
        if name in UNSUPPORTED_WRITES or name not in WRITE_ALLOWLIST:
            if name in {
                "create_ad_platform",
                "delete_ad_platform",
                "create_channel",
                "delete_channel",
                "create_crm_integration",
                "delete_crm_integration",
            }:
                raise ProviderError("Roistat capability is unsupported_by_official_api")
            if name in {"delete_orders_batch", "delete_orders"}:
                raise ProviderError("Roistat batch delete is rejected")
            raise ProviderError("Roistat operation is not in the write allowlist")
        if name not in self.write_operations:
            raise ProviderError("Roistat write operation is not enabled on the server")
        project = self.authorize_project(project_id, writing=True)
        values = dict(payload or {})
        spec = WRITE_ALLOWLIST[name]
        if name == "update_order_status":
            order_id = _object_id(values.get("order_id"), "order_id")
            status_id = _object_id(values.get("status_id") or values.get("status"), "status_id")
            return {
                "operation": name,
                "project_id": project,
                "risk_tier": spec.risk,
                "path_ids": {"order_id": order_id},
                "body": {"status_id": status_id},
                "object_id": order_id,
            }
        if name == "delete_order":
            if values.get("confirm_delete") is not True:
                raise ProviderError("Roistat delete_order requires confirm_delete=true")
            if any(key in values for key in ("order_ids", "ids", "filters")):
                raise ProviderError("Roistat delete_order is single-object only")
            order_id = _object_id(values.get("order_id"), "order_id")
            return {
                "operation": name,
                "project_id": project,
                "risk_tier": spec.risk,
                "path_ids": {"order_id": order_id},
                "body": None,
                "object_id": order_id,
            }
        if name == "import_order":
            raw_order = values.get("order")
            order: Mapping[str, Any] = raw_order if isinstance(raw_order, Mapping) else values
            required = {"id", "date_create", "status"}
            missing = sorted(field for field in required if not str(order.get(field, "")).strip())
            if missing:
                raise ProviderError("Roistat import_order requires fields: " + ", ".join(missing))
            if any(key in values for key in ("orders", "items")):
                raise ProviderError("Roistat import_order is single-object only")
            body = {
                "id": _object_id(order.get("id"), "order.id"),
                "date_create": str(order.get("date_create")).strip(),
                "status": _object_id(order.get("status"), "status"),
            }
            if order.get("name") is not None:
                name_value = str(order.get("name")).strip()
                if not name_value or len(name_value) > 255:
                    raise ProviderError("Roistat import_order name is invalid")
                body["name"] = name_value
            for optional in ("price", "cost", "roistat", "client_id"):
                if optional in order and order[optional] is not None:
                    body[optional] = str(order[optional]).strip()[:64]
            return {
                "operation": name,
                "project_id": project,
                "risk_tier": spec.risk,
                "path_ids": {},
                "body": [body],
                "object_id": body["id"],
            }
        if name.startswith(("calltracking_", "events_")):
            body, object_id = self._validate_calltracking_or_event(name, values)
            return {
                "operation": name,
                "project_id": project,
                "risk_tier": spec.risk,
                "path_ids": {},
                "body": body,
                "object_id": object_id,
            }
        raw_client = values.get("client")
        client: Mapping[str, Any] = raw_client if isinstance(raw_client, Mapping) else values
        if any(key in values for key in ("clients", "items")):
            raise ProviderError("Roistat import_client is single-object only")
        client_id = _object_id(client.get("id"), "client.id")
        client_name = client.get("name")
        if not isinstance(client_name, str) or not client_name.strip() or len(client_name) > 255:
            raise ProviderError("Roistat import_client requires a non-empty name")
        body = {"id": client_id, "name": client_name.strip()}
        if client.get("company") is not None:
            company = str(client.get("company")).strip()
            if company and len(company) <= 255:
                body["company"] = company
        return {
            "operation": name,
            "project_id": project,
            "risk_tier": spec.risk,
            "path_ids": {},
            "body": [body],
            "object_id": client_id,
        }

    @staticmethod
    def _validate_calltracking_or_event(name: str, values: dict[str, Any]) -> tuple[Any, str]:
        if name.endswith("_delete") and values.get("confirm_delete") is not True:
            raise ProviderError(f"Roistat {name} requires confirm_delete=true")
        if name == "calltracking_script_create":
            options = values.get("options")
            needed = ("css_selector", "redirect", "replaceable_numbers")
            if not isinstance(options, Mapping) or any(k not in options for k in needed):
                raise ProviderError("Roistat script options need css_selector, redirect, replaceable_numbers")
            if options.get("calltracking_type", "dynamic") not in {"dynamic", "static"}:
                raise ProviderError("Roistat calltracking_type must be dynamic or static")
            if not isinstance(values.get("name"), str) or not values["name"].strip():
                raise ProviderError("Roistat script requires a name")
            return {k: values[k] for k in _SCRIPT_KEYS if k in values}, str(values["name"]).strip()
        if name == "calltracking_script_update":
            script_id = _object_id(values.get("id"), "id")
            body = {"id": _int_id(script_id, "id"), **{k: values[k] for k in _SCRIPT_KEYS if k in values}}
            if len(body) == 1:
                raise ProviderError("Roistat script update needs at least one field")
            return body, script_id
        if name == "calltracking_script_delete":
            script_id = _object_id(values.get("id"), "id")
            return {"id": _int_id(script_id, "id")}, script_id
        if name == "calltracking_phone_create":
            phones = values.get("phones")
            if not isinstance(phones, list) or not 1 <= len(phones) <= 20:
                raise ProviderError("Roistat phone/create needs 1-20 phones")
            clean = [str(p).strip().lstrip("+") for p in phones]
            if not all(_PHONE.match(p) for p in clean):
                raise ProviderError("Roistat phones must be digits in international format")
            return {"phones": clean}, f"{len(clean)} phones"
        if name == "calltracking_phone_update":
            phone_id = _object_id(values.get("id"), "id")
            body = {"id": _int_id(phone_id, "id"), "script_id": _int_id(values.get("script_id"), "script_id")}
            if values.get("last_use_date") is not None:
                body["last_use_date"] = str(values["last_use_date"]).strip()
            return body, phone_id
        if name == "calltracking_phone_delete":
            if any(key in values for key in ("phones", "ids")):
                raise ProviderError("Roistat phone delete is single-object only")
            phone_id = _object_id(values.get("id"), "id")
            return {"phones": [_int_id(phone_id, "id")]}, phone_id
        if name == "events_send":
            body = _event_body(values.get("event") if isinstance(values.get("event"), Mapping) else values)
            return body, body["name"]
        items = values.get("events")
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise ProviderError(f"Roistat {name} needs 1-100 events")
        if name == "events_bulk_send":
            return [_event_body(item) for item in items], f"{len(items)} events"
        out = []
        for item in items:
            if not isinstance(item, Mapping) or item.get("type") not in {"js", "url"}:
                raise ProviderError("Roistat events/add items need type js or url")
            display = str(item.get("display_name") or "").strip()
            parameter = str(item.get("parameter") or "").strip()
            if not display or not parameter or len(display) > 255 or len(parameter) > 2048:
                raise ProviderError("Roistat events/add items need display_name and parameter")
            out.append({"display_name": display, "type": item["type"], "parameter": parameter})
        return out, f"{len(out)} event definitions"

    async def apply_write(
        self, operation: str, project_id: object, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        validated = self.validate_write(operation, project_id, payload)
        spec = WRITE_ALLOWLIST[validated["operation"]]
        url = self._url(spec.segments, validated["path_ids"])
        await self._admit(validated["project_id"], validated["operation"])
        response = await self.http.request(
            spec.method,
            url,
            headers=self._headers(),
            payload=validated["body"],
            params={"project": validated["project_id"]},
            idempotent=False,
        )
        checked = self._validate_response(response)
        return {
            "provider": "roistat",
            "operation": validated["operation"],
            "project_id": validated["project_id"],
            "object_id": validated["object_id"],
            "risk_tier": validated["risk_tier"],
            "applied": True,
            "response": checked,
        }

    async def readback(self, operation: str, project_id: object, object_id: object) -> dict[str, Any]:
        name = str(operation).strip()
        if name in {"update_order_status", "import_order"}:
            return await self.get_order(project_id, object_id)
        if name == "import_client":
            return await self.list_clients(
                project_id,
                limit=1,
                offset=0,
                filters=[["external_id", "=", str(object_id)]],
            )
        if name == "delete_order":
            try:
                result = await self.get_order(project_id, object_id)
            except ProviderNotFoundError:
                return {"deleted": True, "object_id": str(object_id), "completeness": "complete"}
            except ProviderError as exc:
                if "resource_not_found" in str(exc):
                    return {"deleted": True, "object_id": str(object_id), "completeness": "complete"}
                raise
            return {
                "deleted": False,
                "order": result.get("order"),
                "completeness": result.get("completeness"),
            }
        if name.startswith("calltracking_"):
            return await self._calltracking_readback(name, project_id, object_id)
        if name.startswith("events_"):
            return {
                "verified": False,
                "object_id": str(object_id),
                "reason": "Roistat has no per-event readback; inspect roistat_extra_read(kind='events_log')",
            }
        raise ProviderError("Roistat readback is not defined for this operation")

    async def _calltracking_readback(
        self, name: str, project_id: object, object_id: object
    ) -> dict[str, Any]:
        """Readback after an applied calltracking write; never turns success into an error.

        Deletion is reported only from a listing that provably covers every object: an empty,
        malformed or partial response leaves ``deleted`` unknown (None) and ``verified`` false.
        Rate limits propagate so the runtime records the provider cooldown.
        """
        kind = "calltracking_scripts" if "_script_" in name else "calltracking_phones"
        delete = name.endswith("_delete")
        unverified: dict[str, Any] = {"verified": False, "object_id": str(object_id)}
        if delete:
            unverified["deleted"] = None
        if name == "calltracking_phone_create":
            # Phone numbers are redacted in reads, so new numbers cannot be matched.
            return {**unverified, "reason": "phone numbers are redacted"}
        try:
            project = self.authorize_project(project_id)
            response = await self._call(kind, project_id=project)
        except ProviderRateLimited:
            raise
        except ProviderError:
            return {**unverified, "reason": "readback read failed"}
        items, complete = _full_collection(response, "data", "items", "scripts", "phones")
        if items is None:
            return {**unverified, "reason": "readback response has no listing"}
        field = "name" if name == "calltracking_script_create" else "id"
        matches = [
            item
            for item in _redact_pii(items)
            if isinstance(item, Mapping) and str(item.get(field)) == str(object_id)
        ]
        if delete:
            if matches:
                deleted = all(item.get("is_deleted") in (1, True, "1") for item in matches)
                return {"verified": True, "deleted": deleted, "object_id": str(object_id)}
            if not complete:
                return {**unverified, "reason": "listing is partial; absence does not prove deletion"}
            return {"verified": True, "deleted": True, "object_id": str(object_id)}
        return {
            "verified": bool(matches),
            "object_id": str(object_id),
            "item": matches[0] if matches else None,
            "completeness": "complete" if complete else "partial",
        }
