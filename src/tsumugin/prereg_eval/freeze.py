"""P0 §0: 凍結 manifest の材料 — 凍結する部品の版の文字列と、それを定義するファイルの sha256。

版の文字列は「何を変えたら上げるか」を人が守る印で、**ファイルの sha256 が機械の正**。版を上げ忘れても、
中身が変われば sha256 が変わる。一覧のファイルが無ければ止める (改名・移動で黙って凍結から外れない)。

P0 §0 の項目のうち、ここで扱うのはコードと設定 (テンプレート・D・検査器・評価スクリプト・プローブ・合成の生成器)。
準 hold-out の事例表・`H-pub` の候補一覧・drand の round は凍結の作業で別に足す。
"""

from __future__ import annotations

import dataclasses
import hashlib
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

    return {
        "template": TEMPLATE_VERSION,
        "policy": DEFAULT_POLICY,
        "checker": f"{CLAIMS_VERSION}|{WITNESS_VERSION}|{CHEMISTRY_VERSION}",
        "bvparm_sha256": BVPARM_SHA256,  # 検査器の表 (リポジトリの外) — 中身は sha256 で固定
        "pass1_config": {k: _plain(v) for k, v in dataclasses.asdict(Pass1Config()).items()},
        "probe_config": {k: _plain(v) for k, v in dataclasses.asdict(ProbeConfig()).items()},
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
    return {
        "p0_commit": p0_commit,
        "versions": frozen_versions(),
        "components": components,
        "environment": _environment(),
    }
