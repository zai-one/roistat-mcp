import pytest

from zai_roistat import adapter as mod


def test_extra_specs_registered():
    for kind in mod.EXTRA_READS:
        assert kind in mod.READ_SPECS
    assert mod.READ_SPECS["events_log"].method == "POST"  # documented curl sends a JSON body


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

    async def fake_call(kind, *, project_id=None, payload=None, params=None, **kw):
        seen.update(kind=kind, payload=payload, params=params)
        return {"feed": [{"type": "call", "phone": "+7999"}], "total": 1}

    obj.authorize_project = lambda p, writing=False: str(p)
    obj._call = fake_call
    out = await obj.extra_read("client_feed", 12345, client_id="c-1")
    # Docs: GET /project/clients/detail/feed?project=..&client=..; response key "feed".
    assert seen == {"kind": "client_feed", "payload": None, "params": {"client": "c-1"}}
    assert mod.READ_SPECS["client_feed"].method == "GET"
    assert out["returned_count"] == 1
    assert out["items"][0]["phone"] != "+7999" and out["source"] == "project/clients/detail/feed"
    with pytest.raises(ValueError):
        await obj.extra_read("client_feed", 12345)


async def test_events_log_sends_documented_filters():
    obj = object.__new__(mod.RoistatAdapter)
    seen = {}

    async def fake_call(kind, *, project_id=None, payload=None, params=None, **kw):
        seen.update(payload=payload, params=params)
        return {"items": [{"id": "123", "display_name": "cart"}], "status": "success"}

    obj.authorize_project = lambda p, writing=False: str(p)
    obj._call = fake_call
    out = await obj.extra_read(
        "events_log", 1, event_name="cart", date_from="2026-10-01T00:00:00Z", date_to="2026-10-02"
    )
    assert seen["payload"] == {"name": "cart", "date_from": "2026-10-01T00:00:00Z", "date_to": "2026-10-02"}
    assert out["returned_count"] == 1
    with pytest.raises(ValueError):
        await obj.extra_read("events_log", 1, date_from="yesterday")


SIP_PASSWORD = "sip-trunk-pass-synthetic"


def _script(redirect_type="sip_trunk", value=SIP_PASSWORD):
    return {
        "id": 7,
        "name": "Basic",
        "options": {"redirect": {"type": redirect_type, "value": value, "sip_trunk_postfix": 5}},
    }


def _fake(obj, response):
    async def fake_call(kind, *, project_id=None, payload=None, params=None, **kw):
        return response

    obj.authorize_project = lambda p, writing=False: str(p)
    obj._call = fake_call


async def test_calltracking_forwarding_value_is_redacted_in_reads():
    """Regression: options.redirect.value may hold a Roistat SIP password, a SIP account or a phone."""
    obj = object.__new__(mod.RoistatAdapter)
    nested_phone = {"id": 9, "script": _script("phone", "74951234567")}
    _fake(obj, {"data": [_script(), _script("sip", "user@sip.example"), nested_phone], "total": 3})
    out = await obj.extra_read("calltracking_scripts", 1)
    text = repr(out)
    assert SIP_PASSWORD not in text and "user@sip.example" not in text and "74951234567" not in text
    redirect = out["items"][0]["options"]["redirect"]
    assert redirect["type"] == "sip_trunk" and redirect["sip_trunk_postfix"] == 5


async def test_client_feed_lead_hunter_contacts_are_redacted():
    """Regression: lead_hunter_caught keeps the entered phone in `field` and the lead name in `name`."""
    obj = object.__new__(mod.RoistatAdapter)
    caught = {"type": "lead_hunter_caught", "page": "/", "name": "Jane", "field": "71234567890"}
    event = {"type": "event", "metaId": 1, "name": "cart"}
    _fake(obj, {"feed": [caught, event], "status": "success"})
    out = await obj.extra_read("client_feed", 1, client_id="c-1")
    assert "Jane" not in repr(out) and "71234567890" not in repr(out)
    assert out["items"][0]["type"] == "lead_hunter_caught" and out["items"][0]["page"] == "/"
    assert out["items"][1]["name"] == "cart"  # event names are not personal data


async def test_calltracking_write_response_redacts_forwarding_value():
    class Http:
        async def request(self, method, url, **kwargs):
            return {"status": "success", "data": _script()}

    adapter = mod.RoistatAdapter(
        "synthetic-key", project_allowlist="1", write_operations="calltracking_script_update", http=Http()
    )
    result = await adapter.apply_write("calltracking_script_update", 1, {"id": 7, "name": "Basic"})
    assert SIP_PASSWORD not in repr(result)


@pytest.mark.parametrize(
    "response",
    [
        {"status": "success"},  # no collection at all
        {"status": "success", "data": [{"id": 1}], "total": 40},  # partial page, target not in it
        {"status": "success", "data": [{"id": 1}], "total": "many"},  # unreadable total
    ],
)
async def test_delete_readback_does_not_infer_deletion_from_missing_coverage(response):
    """Regression: absence in an empty or partial listing was reported as verified deletion."""
    obj = object.__new__(mod.RoistatAdapter)
    _fake(obj, response)
    out = await obj.readback("calltracking_script_delete", 1, "7")
    assert out["verified"] is False and out["deleted"] is None


@pytest.mark.parametrize(
    ("response", "deleted"),
    [
        ({"status": "success", "data": [], "total": 0}, True),
        ({"status": "success", "data": [{"id": 1}]}, True),
        ({"status": "success", "data": [{"id": 7, "is_deleted": 1}], "total": 1}, True),
        ({"status": "success", "data": [{"id": 7, "is_deleted": 0}], "total": 1}, False),
    ],
)
async def test_delete_readback_with_complete_listing(response, deleted):
    obj = object.__new__(mod.RoistatAdapter)
    _fake(obj, response)
    out = await obj.readback("calltracking_script_delete", 1, "7")
    assert out["verified"] is True and out["deleted"] is deleted


async def test_calltracking_readback_lets_rate_limits_reach_the_runtime():
    obj = object.__new__(mod.RoistatAdapter)
    obj.authorize_project = lambda p, writing=False: str(p)

    async def limited(kind, **kw):
        raise mod.ProviderRateLimited("provider returned HTTP 429", retry_after_seconds=120)

    obj._call = limited
    with pytest.raises(mod.ProviderRateLimited):
        await obj.readback("calltracking_script_update", 1, "7")
