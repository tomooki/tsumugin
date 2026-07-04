from __future__ import annotations

import importlib.util

import pytest

from tsumugin.backends.gsasii import gsasii_available


def _mcp_available() -> bool:
    """mcp SDK (optional extra ``mcp``) が import 可能かを判定する (gsas と同型)。"""
    return importlib.util.find_spec("mcp") is not None


def _nested_available() -> bool:
    """外部サンプラ (optional extra ``nested``: dynesty/ultranest) の import 可否を判定する (gsas/mcp と同型)。"""
    return (
        importlib.util.find_spec("dynesty") is not None
        or importlib.util.find_spec("ultranest") is not None
    )


def pytest_collection_modifyitems(config, items):
    """未導入環境で `gsas`/`mcp`/`nested` マーカー付きテストを自動 skip する (同型)。"""
    gsas_ok = gsasii_available()
    mcp_ok = _mcp_available()
    nested_ok = _nested_available()
    if gsas_ok and mcp_ok and nested_ok:
        return
    skip_gsas = pytest.mark.skip(reason="GSAS-II (GSASIIscriptable) not installed")
    skip_mcp = pytest.mark.skip(reason="mcp SDK (optional extra mcp) not installed")
    skip_nested = pytest.mark.skip(
        reason="外部サンプラ (optional extra nested: dynesty/ultranest) not installed"
    )
    for item in items:
        if not gsas_ok and item.get_closest_marker("gsas"):
            item.add_marker(skip_gsas)
        if not mcp_ok and item.get_closest_marker("mcp"):
            item.add_marker(skip_mcp)
        if not nested_ok and item.get_closest_marker("nested"):
            item.add_marker(skip_nested)
