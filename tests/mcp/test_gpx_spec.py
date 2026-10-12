"""`mcp._gpx_spec.gpx_args` — ② の保存指定の検査・正規化 (単体)。

ツール経由の振る舞い (4 ツールが精密化前に検査すること) は `test_gpx_exposure.py` が縛る。
ここで縛るのはヘルパ自身の契約 — **何を既定として通し、何を型違いとして止めるか**。
"""

from __future__ import annotations

import pytest

from tsumugin.mcp._gpx_spec import gpx_args


@pytest.mark.parametrize("save", [True, False])
def test_explicit_booleans_pass_through(save):
    assert gpx_args("/root", save) == ("/root", save)


def test_null_save_gpx_is_the_default_not_an_opt_out():
    """★null は既定 (保存する)。``bool(None)`` に任せると opt-out に倒れる。"""
    assert gpx_args(None, None) == (None, True)


@pytest.mark.parametrize("gpx_dir", [None, "", "relative/dir", "C:/abs"])
def test_any_string_or_null_gpx_dir_passes(gpx_dir):
    """空文字は既定の解決 (env → データ隣接) に委ねる意味で `gpxstore` がそう扱う — ここでは止めない。"""
    assert gpx_args(gpx_dir, True) == (gpx_dir, True)


@pytest.mark.parametrize("save", ["false", "true", 0, 1, [], {}])
def test_non_boolean_save_gpx_is_a_type_error(save):
    """★``"false"`` は truthy (保存する)・``0`` は falsy (止める) — どちらも ③ の意図と無関係に決まる。"""
    with pytest.raises(TypeError, match="save_gpx"):
        gpx_args(None, save)


def test_numpy_bool_is_not_a_json_boolean():
    """② の入力は JSON なので bool は Python の ``bool`` だけ (numpy の真偽値は来ない前提を固定)。"""
    np = pytest.importorskip("numpy")
    with pytest.raises(TypeError, match="save_gpx"):
        gpx_args(None, np.bool_(False))


@pytest.mark.parametrize("gpx_dir", [123, 1.5, ["/a"], {"path": "/a"}, True])
def test_non_string_gpx_dir_is_a_type_error(gpx_dir):
    with pytest.raises(TypeError, match="gpx_dir"):
        gpx_args(gpx_dir, True)
