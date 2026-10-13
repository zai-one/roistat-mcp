import pytest

from zai_roistat import adapter as mod


def test_extra_specs_registered():
    for kind in mod.EXTRA_READS:
        assert kind in mod.READ_SPECS
    assert mod.READ_SPECS["events_log"].method == "GET"


def test_redaction_applies_to_feed_items():
    assert mod._redact_pii([{"phone": "+7999", "id": "1"}])[0]["phone"] != "+7999"


@pytest.mark.parametrize("kind", ["bogus", "delete_order"])
async def test_unknown_kind_rejected(kind):
    obj = object.__new__(mod.RoistatAdapter) if hasattr(mod, "RoistatAdapter") else None
    if obj is None:
        pytest.skip("adapter class name differs")
    with pytest.raises(ValueError):
        await obj.extra_read(kind, 1)


async def test_extra_read_client_feed_payload_and_redaction():
    obj = object.__new__(mod.RoistatAdapter)
    seen = {}

    async def fake_call(kind, *, project_id=None, payload=None, **kw):
        seen.update(kind=kind, payload=payload)
        return {"data": [{"id": "1", "phone": "+7999"}], "total": 1}

    obj.authorize_project = lambda p, writing=False: str(p)
    obj._call = fake_call
    out = await obj.extra_read("client_feed", 12345, client_id="c-1")
    assert seen == {"kind": "client_feed", "payload": {"client_id": "c-1"}}
    assert out["items"][0]["phone"] != "+7999" and out["source"] == "project/clients/detail/feed"
    with pytest.raises(ValueError):
        await obj.extra_read("client_feed", 12345)
