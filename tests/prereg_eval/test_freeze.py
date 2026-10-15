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
