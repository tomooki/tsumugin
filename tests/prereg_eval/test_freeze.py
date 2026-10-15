"""P0 §0: 凍結 manifest — 凍結する部品の版と、それを定義するファイルの sha256。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tsumugin.prereg_eval.freeze import FROZEN_COMPONENTS, component_files, freeze_manifest, frozen_versions

ROOT = Path(__file__).resolve().parents[2]


def test_every_listed_file_exists():
    # 改名・移動で黙って凍結から外れないように (一覧に有るのに無いファイルは止める)
    for name in FROZEN_COMPONENTS:
        files = component_files(ROOT, name)
        assert files, name
        for f in files:
            assert f.is_file(), (name, f)


def test_versions_are_the_constants_in_the_code():
    from tsumugin.claims.build import CLAIMS_VERSION
    from tsumugin.claims.chemistry import CHEMISTRY_VERSION
    from tsumugin.claims.requests import DEFAULT_POLICY
    from tsumugin.claims.witness import WITNESS_VERSION
    from tsumugin.template.compile import TEMPLATE_VERSION

    v = frozen_versions()
    assert v["template"] == TEMPLATE_VERSION and v["policy"] == DEFAULT_POLICY
    assert v["checker"] == f"{CLAIMS_VERSION}|{WITNESS_VERSION}|{CHEMISTRY_VERSION}"
    from tsumugin.claims.chemistry import BVPARM_SHA256

    assert v["bvparm_sha256"] == BVPARM_SHA256 and len(v["bvparm_sha256"]) == 64
    assert set(v["pass1_config"]) >= {"alpha", "background_ladder"} and "cell_frac" in v["probe_config"]


def test_manifest_hashes_each_file_and_records_the_p0_version():
    m = freeze_manifest(ROOT, p0_commit="abc123")
    assert m["p0_commit"] == "abc123"
    entry = m["components"]["evaluation"]
    some = next(iter(entry["files"]))
    assert entry["files"][some] == hashlib.sha256((ROOT / some).read_bytes()).hexdigest()
    assert set(m["components"]) == set(FROZEN_COMPONENTS)
    assert {"python", "numpy"} <= set(m["environment"])


def test_required_components_from_p0_are_all_there():
    # P0 §0 の表: テンプレート・D・検査器・評価スクリプト (と、それらの設定・合成の生成器)
    assert {"template", "policy", "checker", "evaluation", "probe", "synthetic_generator"} <= set(FROZEN_COMPONENTS)


def test_missing_file_is_an_error_not_a_skip(tmp_path):
    with pytest.raises(FileNotFoundError):
        freeze_manifest(tmp_path, p0_commit="x")


def test_freeze_covers_the_quasi_case_table_and_the_hpub_candidate_manifest():
    # P0 §0: 準 hold-out の事例表・H-pub の候補一覧 (salt 付きハッシュ)・共通の汎用装置パラメータ
    files = {f.relative_to(ROOT).as_posix() for f in component_files(ROOT, "quasi_case_table")}
    assert "docs/benchmark/fit-then-judge-quasi/case_table.json" in files
    files = {f.relative_to(ROOT).as_posix() for f in component_files(ROOT, "hpub_candidates")}
    assert {"docs/benchmark/fit-then-judge-hpub/candidates_manifest.json",
            "docs/benchmark/fit-then-judge-hpub/hpub_generic_lab.instprm"} <= files


def test_versions_carry_the_permutation_list_and_the_posthoc_threshold():
    from tsumugin.prereg_eval.adapter import POSTHOC_MAX_SHIFT_ESD
    from tsumugin.prereg_eval.arms import PERMUTATIONS

    v = frozen_versions()
    assert v["permutations"] == list(PERMUTATIONS) and len(v["permutations"]) >= 4
    assert v["posthoc_max_shift_esd"] == POSTHOC_MAX_SHIFT_ESD


def test_manifest_records_the_hpub_counts_and_the_drand_rule_with_round_left_open():
    m = freeze_manifest(ROOT, p0_commit="abc123")
    h = m["hpub"]
    assert {"n_ref", "k_ref", "n_noref", "k_noref"} <= set(h) and h["k_ref"] + h["k_noref"] <= 30
    d = m["drand"]
    assert d["round"] is None  # push の 24 時間後以降の最初の round を後で記録する
    assert set(d["labels"]) == {"h-pub", "h-pub-noref", "s-eval"}
    assert len(d["s_eval_population_snapshot_sha256"]) == 64
