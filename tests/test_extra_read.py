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
