from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def read_secret_file(value: str) -> str:
    if not value:
        raise ValueError("credential file required")
    path = Path(value)
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("credential file missing or too large")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("credential file must be owner-private")
    result = path.read_text(encoding="utf-8").strip()
    if not result:
        raise ValueError("credential file empty")
    return result


@dataclass(frozen=True)
class ServiceConfig:
    api_key: str = field(repr=False)
    state_path: Path
    project_allowlist: str = ""
    write_operations: str = ""
    account_id: str = "default"
    principal_id: str = "local-operator"
    public_key: str = ""
    issuer: str = "roistat-operator"
    audience: str = "roistat-mcp"
    local_scopes: frozenset[str] = frozenset({"roistat:read", "roistat:write"})
    write_enabled: bool = False
    rate_limit: int = 30
    principal_rate_limit: int = 30
    max_concurrency: int = 1

    def __post_init__(self) -> None:
        if not self.api_key or len(self.api_key) > 4096:
            raise ValueError("valid API key required")
        if not all(
            isinstance(value, str) and 1 <= len(value) <= 256
            for value in (self.account_id, self.principal_id, self.issuer, self.audience)
        ):
            raise ValueError("identity fields required")
        if not self.local_scopes <= {"roistat:read", "roistat:write"}:
            raise ValueError("unknown local scope")
        if not 1 <= self.principal_rate_limit <= self.rate_limit <= 30:
            raise ValueError("invalid request limits")
        if self.max_concurrency != 1:
            raise ValueError("invalid concurrency limit")
        from zai_roistat.adapter import RoistatAdapter

        adapter = RoistatAdapter(
            self.api_key, project_allowlist=self.project_allowlist, write_operations=self.write_operations
        )
        if self.write_enabled and not adapter.project_allowlist:
            raise ValueError("writes require a project allowlist")

    @classmethod
    def from_env(cls) -> ServiceConfig:
        public_path = os.environ.get("ROISTAT_MCP_PUBLIC_KEY_FILE", "")
        enabled = os.environ.get("ROISTAT_WRITE_ENABLED", "false")
        if enabled not in {"true", "false"}:
            raise ValueError("ROISTAT_WRITE_ENABLED must be true or false")
        return cls(
            api_key=read_secret_file(os.environ.get("ROISTAT_API_KEY_FILE", "")),
            state_path=Path(os.environ.get("ROISTAT_STATE_PATH", "state/roistat.sqlite")),
            project_allowlist=os.environ.get("ROISTAT_PROJECT_ALLOWLIST", ""),
            write_operations=os.environ.get("ROISTAT_WRITE_OPERATIONS", ""),
            account_id=os.environ.get("ROISTAT_ACCOUNT_ID", "default"),
            principal_id=os.environ.get("ROISTAT_LOCAL_PRINCIPAL", "local-operator"),
            public_key=Path(public_path).read_text(encoding="utf-8") if public_path else "",
            issuer=os.environ.get("ROISTAT_MCP_ISSUER", "roistat-operator"),
            audience=os.environ.get("ROISTAT_MCP_AUDIENCE", "roistat-mcp"),
            write_enabled=enabled == "true",
            rate_limit=int(os.environ.get("ROISTAT_RATE_LIMIT", "30")),
            principal_rate_limit=int(os.environ.get("ROISTAT_PRINCIPAL_RATE_LIMIT", "30")),
            max_concurrency=int(os.environ.get("ROISTAT_MAX_CONCURRENCY", "1")),
        )
