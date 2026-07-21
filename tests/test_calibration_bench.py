"""較正ベンチ (docs/benchmark/calibration/run_calibration_bench.py) の決定論スモークテスト。

Issue #72 前半 (仕様 §12-5)。ベンチ本体は ``docs/`` 配下のスクリプトで ``tsumugin`` パッケージには
含まれないため、``importlib`` でファイルパスから動的に読み込む。縮小版 (N=8) で以下を検証する:

- 決定論: 同一 seed で 2 回実行するとビット同一 (NFR-102)。
- 較正後 ECE が較正前 ECE を超えない (bic / nested 双方)。
- reliability レポートの基本構造 (4 系列・backend・probability_semantics・n_samples)。
- bic と nested で probability_semantics (確率の意味) が異なる。

GSAS-II 不要・``SimulatedBackend`` (numpy コア) のみで完結し、GSAS マーカ非依存の高速ティアで動く。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_BENCH_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs" / "benchmark" / "calibration" / "run_calibration_bench.py"
)

_N_PROBLEMS = 8
_SEED = 0
_N_BINS = 10


def _load_bench_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("calibration_bench", _BENCH_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses は `from __future__ import annotations` 下で ClassVar/InitVar 判定のため
    # ``sys.modules[cls.__module__]`` を参照する。動的ロードしたモジュールを事前に登録しておかない
    # と `sys.modules.get(...)` が None を返し AttributeError になる (標準的な回避策)。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bench() -> types.ModuleType:
    return _load_bench_module()


@pytest.fixture(scope="module")
def bench_result_pair(bench: types.ModuleType):
    """同一 seed で 2 回実行した結果の組 (決定論検証と構造検証の双方で使い回してコストを抑える)。"""
    result_a = bench.run_bench(n_problems=_N_PROBLEMS, seed=_SEED, n_bins=_N_BINS)
    result_b = bench.run_bench(n_problems=_N_PROBLEMS, seed=_SEED, n_bins=_N_BINS)
    return result_a, result_b


def test_run_bench_deterministic(bench_result_pair):
    """同一 seed/n_problems の 2 回実行がビット同一 (NFR-102)。"""
    result_a, result_b = bench_result_pair
    assert result_a.reports == result_b.reports
    assert result_a.temperature_bic == result_b.temperature_bic
    assert result_a.temperature_nested == result_b.temperature_nested
    assert result_a.minor_scale_fractions == result_b.minor_scale_fractions


def test_run_bench_has_four_series_with_full_sample_count(bench_result_pair):
    result, _ = bench_result_pair
    assert set(result.reports.keys()) == {
        "bic_raw", "bic_calibrated", "nested_raw", "nested_calibrated",
    }
    for name, report in result.reports.items():
        assert report.n_samples == _N_PROBLEMS, name
        assert report.probability_semantics != "", name
        assert report.ece >= 0.0, name


def test_bic_calibration_does_not_worsen_ece(bench_result_pair):
    result, _ = bench_result_pair
    assert result.reports["bic_calibrated"].ece <= result.reports["bic_raw"].ece + 1e-9


def test_nested_calibration_does_not_worsen_ece(bench_result_pair):
    result, _ = bench_result_pair
    assert result.reports["nested_calibrated"].ece <= result.reports["nested_raw"].ece + 1e-9


def test_probability_semantics_differ_between_bic_and_nested(bench_result_pair):
    result, _ = bench_result_pair
    bic_semantics = result.reports["bic_raw"].probability_semantics
    nested_semantics = result.reports["nested_raw"].probability_semantics
    assert bic_semantics != nested_semantics
    assert "BIC" in bic_semantics
    assert "logZ" in nested_semantics


def test_backend_field_matches_series(bench_result_pair):
    result, _ = bench_result_pair
    assert result.reports["bic_raw"].backend == "bic"
    assert result.reports["bic_calibrated"].backend == "bic"
    assert result.reports["nested_raw"].backend == "nested"
    assert result.reports["nested_calibrated"].backend == "nested"


def test_temperatures_are_positive_finite(bench_result_pair):
    result, _ = bench_result_pair
    assert result.temperature_bic > 0.0
    assert result.temperature_nested > 0.0
