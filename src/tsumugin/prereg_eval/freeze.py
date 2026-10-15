"""P0 §0: 凍結 manifest の材料 — 凍結する部品の版の文字列と、それを定義するファイルの sha256。

版の文字列は「何を変えたら上げるか」を人が守る印で、**ファイルの sha256 が機械の正**。版を上げ忘れても、
中身が変われば sha256 が変わる。一覧のファイルが無ければ止める (改名・移動で黙って凍結から外れない)。

P0 §0 の項目: コードと設定 (テンプレート・D・検査器・評価スクリプト・プローブ・合成の生成器)・準 hold-out の事例表・
`H-pub` の候補 manifest (salt 付きハッシュ) と共通の汎用装置パラメータ・置換アームの段順・収束の事後検査の閾値・
drand の規則。drand の **round** は凍結 commit を push した 24 時間後以降に決まるので、ここでは空 (None) にして後で記録する。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import platform
from pathlib import Path

__all__ = ["FROZEN_COMPONENTS", "component_files", "freeze_manifest", "frozen_versions"]

#: 部品 → リポジトリの根からの glob の列
FROZEN_COMPONENTS: dict[str, tuple[str, ...]] = {
    "template": ("src/tsumugin/template/*.py",),
    "policy": ("src/tsumugin/claims/requests.py",),
    "checker": (
        "src/tsumugin/claims/build.py",
        "src/tsumugin/claims/model.py",
        "src/tsumugin/claims/witness.py",
        "src/tsumugin/claims/chemistry.py",
        "src/tsumugin/claims/publication.py",
    ),
    "evaluation": ("src/tsumugin/prereg_eval/*.py", "src/tsumugin/evidence/fitstats.py"),
    "probe": ("src/tsumugin/autorietveld/probe.py", "src/tsumugin/autorietveld/agreement.py"),
    "synthetic_generator": (
        "docs/benchmark/fit-then-judge-synthetic/cases.py",
        "docs/benchmark/fit-then-judge-synthetic/generate.py",
    ),
    "hpub_candidates": (
        "docs/benchmark/fit-then-judge-hpub/candidates.py",
        "docs/benchmark/fit-then-judge-hpub/manifest.py",
        "docs/benchmark/fit-then-judge-hpub/candidates_manifest.json",
        "docs/benchmark/fit-then-judge-hpub/hpub_generic_lab.instprm",
        "src/tsumugin/prereg_eval/hpub.py",
        "src/tsumugin/prereg_eval/hpub_draw.py",
    ),
    "quasi_case_table": (
        "docs/benchmark/fit-then-judge-quasi/case_table.py",
        "docs/benchmark/fit-then-judge-quasi/case_table.json",
        "src/tsumugin/prereg_eval/mapping.py",
    ),
}

_HPUB_MANIFEST = "docs/benchmark/fit-then-judge-hpub/candidates_manifest.json"

#: P0 §3.2.1-3 / §6.3: 種の作り方。round は push の 24 時間後以降の最初の drand round (凍結後に記録)
DRAND_RULE = {
    "round": None,
    "when": "凍結 commit を GitHub に push した時刻 (サーバー側) の 24 時間後以降で最初の drand (League of Entropy) の round",
    "seed": "int(sha256('<r>:<label>')[:8], 16)",
    "labels": ["h-pub", "h-pub-noref", "s-eval"],
    "order": "凍結 → H-pub の抽出 → S-eval の生成 (P0 §6.3)",
}


def component_files(root: Path, name: str) -> list[Path]:
    out: list[Path] = []
    for pattern in FROZEN_COMPONENTS[name]:
        hits = sorted(root.glob(pattern))
        if not hits:
            raise FileNotFoundError(f"{name}: {pattern} に当たるファイルが無い ({root})")
        out.extend(hits)
    return out


def frozen_versions() -> dict[str, object]:
    """凍結する版の文字列と、調整した設定の値。"""
    from ..autorietveld.probe import ProbeConfig
    from ..claims.build import CLAIMS_VERSION
    from ..claims.chemistry import BVPARM_SHA256, CHEMISTRY_VERSION
    from ..claims.requests import DEFAULT_POLICY
    from ..claims.witness import WITNESS_VERSION
    from ..template.compile import TEMPLATE_VERSION
    from ..template.pass1 import Pass1Config
    from .adapter import POSTHOC_MAX_SHIFT_ESD
    from .arms import PERMUTATIONS

    return {
        "template": TEMPLATE_VERSION,
        "policy": DEFAULT_POLICY,
        "checker": f"{CLAIMS_VERSION}|{WITNESS_VERSION}|{CHEMISTRY_VERSION}",
        "bvparm_sha256": BVPARM_SHA256,  # 検査器の表 (リポジトリの外) — 中身は sha256 で固定
        "pass1_config": {k: _plain(v) for k, v in dataclasses.asdict(Pass1Config()).items()},
        "probe_config": {k: _plain(v) for k, v in dataclasses.asdict(ProbeConfig()).items()},
        "permutations": list(PERMUTATIONS),
        "posthoc_max_shift_esd": POSTHOC_MAX_SHIFT_ESD,
    }


def _plain(v: object) -> object:
    return list(v) if isinstance(v, tuple) else v


def _environment() -> dict[str, str]:
    import numpy

    env = {"python": platform.python_version(), "numpy": numpy.__version__, "platform": platform.platform()}
    try:
        from GSASII import GSASIIpath

        env["gsas2"] = str(GSASIIpath.GetVersionNumber())
    except Exception:  # noqa: BLE001 — GSAS の無い環境でも manifest は作れる (版は unknown と書く)
        env["gsas2"] = "unknown"
    return env


def freeze_manifest(root: Path, *, p0_commit: str) -> dict[str, object]:
    """部品ごとのファイルの sha256・版・環境の指紋・従う P0 の版 (commit)。"""
    components: dict[str, object] = {}
    for name in FROZEN_COMPONENTS:
        files = component_files(Path(root), name)
        components[name] = {
            "files": {f.relative_to(root).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
        }
    from .hpub import SNAPSHOT_SHA256

    hpub = json.loads((Path(root) / _HPUB_MANIFEST).read_text(encoding="utf-8"))
    return {
        "p0_commit": p0_commit,
        "versions": frozen_versions(),
        "components": components,
        # 候補の確定数 (G5)。ハッシュの一覧そのものは components の sha256 で固定される
        "hpub": {k: hpub[k] for k in ("k_ref", "k_noref")} | {"n_ref": hpub["ref"]["n"], "n_noref": hpub["noref"]["n"]},
        "drand": {**DRAND_RULE, "s_eval_population_snapshot_sha256": SNAPSHOT_SHA256["cod_dl/cod_all.csv"]},
        "environment": _environment(),
    }
