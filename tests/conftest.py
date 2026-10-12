from __future__ import annotations

import pytest

from zai_roistat import update_check


@pytest.fixture(autouse=True)
def _no_update_check_network(monkeypatch):
    # Tests never contact GitHub; update-check tests re-enable it with mocked HTTP.
    monkeypatch.setenv("ROISTAT_DISABLE_UPDATE_CHECK", "1")

    def no_real_client():
        raise AssertionError("update check tried to open a real network client")

    # Any check that forgets to inject a mocked client fails loudly instead of reaching GitHub.
    monkeypatch.setattr(update_check, "_open_client", no_real_client)
    monkeypatch.setattr(update_check, "_MEMORY", {})
