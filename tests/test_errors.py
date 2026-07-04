"""errors.py の例外階層テスト (TASK-0047: Nested/OED Unavailable)。"""

from __future__ import annotations

import pytest

from tsumugin.errors import TsumuginError


# ---------------------------------------------------------------------------
# TASK-0047: NestedUnavailableError / OEDUnavailableError (TsumuginError 派生)
# ---------------------------------------------------------------------------


def test_nested_unavailable_error_hierarchy_and_raise():
    # 【TC-502-01】: NestedUnavailableError が TsumuginError 派生で raise/except できる 🔵 REQ-005/EDGE-001
    from tsumugin.errors import NestedUnavailableError

    assert issubclass(NestedUnavailableError, TsumuginError)
    with pytest.raises(TsumuginError):
        raise NestedUnavailableError("nested extra (dynesty/ultranest) 未導入")
    with pytest.raises(NestedUnavailableError):
        raise NestedUnavailableError("nested extra (dynesty/ultranest) 未導入")


def test_oed_unavailable_error_hierarchy_and_raise():
    # 【TC-512-04】: OEDUnavailableError が TsumuginError 派生で raise/except できる 🔵 REQ-036/EDGE-011
    from tsumugin.errors import OEDUnavailableError

    assert issubclass(OEDUnavailableError, TsumuginError)
    with pytest.raises(TsumuginError):
        raise OEDUnavailableError("oed extra (pyboed) 未導入")
    with pytest.raises(OEDUnavailableError):
        raise OEDUnavailableError("oed extra (pyboed) 未導入")


def test_core_import_without_optional_extras():
    # 【TC-514-04】: import tsumugin / import tsumugin.errors がコア (numpy) のみで成功する 🔵 REQ-403
    import tsumugin
    import tsumugin.errors as errors_mod

    # 両例外がコア経路 (extra なし) で解決できる
    assert hasattr(errors_mod, "NestedUnavailableError")
    assert hasattr(errors_mod, "OEDUnavailableError")
    assert tsumugin is not None
