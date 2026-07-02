from __future__ import annotations

import pytest

from tsumugin.backends.gsasii import gsasii_available


def pytest_collection_modifyitems(config, items):
    """GSAS-II 未導入環境では `gsas` マーカー付きテストを自動 skip する。"""
    if gsasii_available():
        return
    skip_gsas = pytest.mark.skip(reason="GSAS-II (GSASIIscriptable) not installed")
    for item in items:
        if item.get_closest_marker("gsas"):
            item.add_marker(skip_gsas)
