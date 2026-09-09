from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest

from zai_roistat.policy import PolicyStore
from zai_roistat.server import AdmittedHttpClient
from zai_roistat.transport import ProviderAdmissionDenied, ProviderTransientHttpError, RetryPolicy


@pytest.mark.parametrize("idempotent,expected", [(True, 3), (False, 1)])
async def test_actual_transport_counts_read_retries_and_never_retries_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, idempotent: bool, expected: int
):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={"errors": "temporary"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "zai_roistat.transport.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    store = PolicyStore(tmp_path / "state.sqlite", "default", 10, 10)
    store.begin("execution", "request", "alice", "hash")
    client = AdmittedHttpClient(store, "execution", "alice")
    client.retry = RetryPolicy(attempts=3, base_delay_seconds=0)
    with pytest.raises(ProviderTransientHttpError):
        await client.request("POST", "https://cloud.roistat.com/api/v1/fixture", idempotent=idempotent)
    assert len(calls) == expected
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == expected


async def test_retry_quota_is_enforced_before_next_http_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "zai_roistat.transport.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    store = PolicyStore(tmp_path / "state.sqlite", "default", 1, 1)
    store.begin("execution", "request", "alice", "hash")
    client = AdmittedHttpClient(store, "execution", "alice")
    client.retry = RetryPolicy(attempts=3, base_delay_seconds=0)
    with pytest.raises(ProviderAdmissionDenied):
        await client.request("POST", "https://cloud.roistat.com/api/v1/fixture", idempotent=True)
    assert len(calls) == 1


def test_second_minute_hour_daily_and_concurrency_survive_new_store(tmp_path, monkeypatch):
    now = [10000.0]
    monkeypatch.setattr("zai_roistat.policy.time.time", lambda: now[0])
    path = tmp_path / "state.sqlite"
    store = PolicyStore(path, "default", 30, 30)
    store.begin("owner", "request", "alice", "hash")
    store.admit("owner", "alice", 1)
    other = PolicyStore(path, "default", 30, 30)
    other.begin("other", "request2", "bob", "hash")
    with pytest.raises(ProviderAdmissionDenied, match="concurrency"):
        other.admit("other", "bob", 1)
    store.finish("owner", "success")
    for attempt in range(1, 5):
        other.admit("other", "bob", attempt)
    with pytest.raises(ProviderAdmissionDenied, match="window"):
        other.admit("other", "bob", 5)
    other.finish("other", "success")
    now[0] += 2
    for attempt in range(1, 4):
        current = PolicyStore(path, "default", 30, 30)
        execution = f"daily-{attempt}"
        current.begin(execution, execution, "alice", "hash")
        current.admit(execution, "alice", 1, daily=True)
        current.finish(execution, "success")
    with pytest.raises(ProviderAdmissionDenied, match="get-daily"):
        PolicyStore(path, "default", 30, 30).admit("daily-4", "bob", 1, daily=True)
    # Age only the short windows; the persisted hour cap remains.
    now[0] += 61
    with store.connect() as db:
        db.executemany(
            "INSERT INTO attempts VALUES(?, 1, 'alice', 'default', ?, 0)",
            [(f"history-{i}", now[0] - 62) for i in range(600)],
        )
    with pytest.raises(ProviderAdmissionDenied, match="window"):
        PolicyStore(path, "default", 30, 30).admit("hour-next", "bob", 1)


async def test_daily_route_retries_consume_durable_special_cap(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "zai_roistat.transport.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    path = tmp_path / "state.sqlite"
    for index in range(2):
        store = PolicyStore(path, "default", 30, 30)
        execution = str(index)
        store.begin(execution, execution, "alice", "hash")
        client = AdmittedHttpClient(store, execution, "alice")
        client.retry = RetryPolicy(attempts=3, base_delay_seconds=0)
        with pytest.raises(ProviderTransientHttpError if index == 0 else ProviderAdmissionDenied):
            await client.request(
                "POST", "https://cloud.roistat.com/api/v1/project/statistics/get-daily", idempotent=True
            )
        store.finish(execution, "error")
    assert len(calls) == 3
