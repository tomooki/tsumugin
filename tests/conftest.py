from __future__ import annotations

import importlib.util
import shutil

import numpy as np
import pytest

from tsumugin.backends.gsasii import gsasii_available


@pytest.fixture(autouse=True)
def _restore_numpy_errstate():
    """各テスト後に numpy のグローバル errstate を復元し、テスト間リークを断つ (Issue #31)。

    pymatgen/spglib 等の一部依存は import/呼び出し時に ``np.seterr`` 相当でグローバルな
    浮動小数点エラーハンドリングを ``raise`` に切り替えることがある。これが残ると、以降の
    (従来 invalid float 演算を黙認していた) テストが ``FloatingPointError`` を送出して
    実行順依存の偽 fail を起こす。テスト毎に保存・復元することで一括実行 (`uv run pytest`)
    の分離を保証する。
    """
    saved = np.geterr()
    try:
        yield
    finally:
        np.seterr(**saved)


def _mcp_available() -> bool:
    """mcp SDK (optional extra ``mcp``) が import 可能かを判定する (gsas と同型)。"""
    return importlib.util.find_spec("mcp") is not None


def _nested_available() -> bool:
    """外部サンプラ (optional extra ``nested``: dynesty/ultranest) の import 可否を判定する (gsas/mcp と同型)。"""
    return (
        importlib.util.find_spec("dynesty") is not None
        or importlib.util.find_spec("ultranest") is not None
    )


def _dysnomia_available() -> bool:
    """MEM 外部バイナリ (optional extra ``mem``: Dysnomia) が PATH に在るかを判定する (gsas と同型)。"""
    return shutil.which("dysnomia") is not None


def _pyboed_available() -> bool:
    """OED 獲得関数 (optional extra ``oed``: pyboed) が import 可能かを判定する (gsas/mcp と同型)。"""
    return importlib.util.find_spec("pyboed") is not None


def _mp_available() -> bool:
    """相ライブラリ供給元 (optional extra ``mp``: pymatgen/mp-api) の import 可否を判定する (gsas/mcp と同型)。"""
    return (
        importlib.util.find_spec("pymatgen") is not None
        and importlib.util.find_spec("mp_api") is not None
    )


def pytest_collection_modifyitems(config, items):
    """未導入環境で `gsas`/`mcp`/`nested`/`mem`/`oed`/`mp` マーカー付きテストを自動 skip する (同型)。"""
    gsas_ok = gsasii_available()
    mcp_ok = _mcp_available()
    nested_ok = _nested_available()
    mem_ok = _dysnomia_available()
    oed_ok = _pyboed_available()
    mp_ok = _mp_available()
    if gsas_ok and mcp_ok and nested_ok and mem_ok and oed_ok and mp_ok:
        return
    skip_gsas = pytest.mark.skip(reason="GSAS-II (GSASIIscriptable) not installed")
    skip_mcp = pytest.mark.skip(reason="mcp SDK (optional extra mcp) not installed")
    skip_nested = pytest.mark.skip(
        reason="外部サンプラ (optional extra nested: dynesty/ultranest) not installed"
    )
    skip_mem = pytest.mark.skip(
        reason="MEM 外部バイナリ (optional extra mem: Dysnomia) not installed"
    )
    skip_oed = pytest.mark.skip(
        reason="OED 獲得関数 (optional extra oed: pyboed) not installed"
    )
    skip_mp = pytest.mark.skip(
        reason="相ライブラリ供給元 (optional extra mp: pymatgen/mp-api) not installed"
    )
    for item in items:
        if not gsas_ok and item.get_closest_marker("gsas"):
            item.add_marker(skip_gsas)
        if not mcp_ok and item.get_closest_marker("mcp"):
            item.add_marker(skip_mcp)
        if not nested_ok and item.get_closest_marker("nested"):
            item.add_marker(skip_nested)
        if not mem_ok and item.get_closest_marker("mem"):
            item.add_marker(skip_mem)
        if not oed_ok and item.get_closest_marker("oed"):
            item.add_marker(skip_oed)
        if not mp_ok and item.get_closest_marker("mp"):
            item.add_marker(skip_mp)
