from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_update_check_network(monkeypatch):
    # Tests never contact GitHub; update-check tests re-enable it with mocked HTTP.
    monkeypatch.setenv("ROISTAT_DISABLE_UPDATE_CHECK", "1")
