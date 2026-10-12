"""精密化済み gpx の隣の出版状態 ``<stem>.claims.json`` (fit-then-judge P1-1A, REQ-FTJ-1A-502)。

.gpx は値の出版状態を持てないので sidecar に置く。**gpx の内容ハッシュ (sha256)** を記録して 1 対 1 に
結び、読み手 (`read_claims_sidecar`) はハッシュが今の gpx と一致するものだけを採る。gpx が上書きされた
(``keep_gpx`` での再実行) ときの古い sidecar は「状態不明」= 出版不可。

**上書きしない** (P2 非破壊): 同名が既にあり中身が違えば ``<stem>.claims.<ハッシュ先頭 12>.json`` に書く。
同じ状態をもう一度書くのは何もしない。書けないときは例外ではなく理由を返す (フィットを落とさない —
`autorietveld.engine._save_gpx_artifact` と同じ方針)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

__all__ = ["read_claims_sidecar", "sidecar_candidates", "write_claims_sidecar"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sidecar_candidates(gpx_path: str) -> list[Path]:
    """この gpx の sidecar になりうるファイル (既定名 + ハッシュ付きの名前)。"""
    gpx = Path(gpx_path)
    default = gpx.with_suffix(".claims.json")
    hashed = sorted(gpx.parent.glob(f"{gpx.stem}.claims.*.json"))
    return [default, *(p for p in hashed if p != default)]


def write_claims_sidecar(gpx_path: str, payload: Mapping[str, Any]) -> tuple[str, str]:
    """sidecar を書く。``(書いたパス, 書けなかった理由)`` — どちらか一方だけが空でない。"""
    if not gpx_path:
        return "", "精密化済み gpx が無い (保存していない) ので sidecar を置く場所が無い"
    gpx = Path(gpx_path)
    try:
        digest = _sha256(gpx)
    except OSError as exc:
        return "", f"gpx を読めない ({type(exc).__name__}: {exc})"
    body = {**dict(payload), "gpx_sha256": digest, "gpx_name": gpx.name}
    try:
        text = json.dumps(body, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=1)
    except (TypeError, ValueError) as exc:
        return "", f"出版状態を JSON にできない ({type(exc).__name__}: {exc})"
    for target in (gpx.with_suffix(".claims.json"), gpx.parent / f"{gpx.stem}.claims.{digest[:12]}.json"):
        try:
            if target.exists():
                if target.read_text(encoding="utf-8") == text:
                    return str(target), ""  # 同じ状態 — 書き直さない
                continue  # 中身が違う — 上書きしない
            with target.open("x", encoding="utf-8") as fh:  # 競合しても上書きしない
                fh.write(text)
            return str(target), ""
        except FileExistsError:
            continue
        except OSError as exc:
            return "", f"sidecar を書けない ({type(exc).__name__}: {exc})"
    return "", "同名の sidecar が既にあり、上書きしない"


def read_claims_sidecar(gpx_path: str) -> dict[str, Any] | None:
    """今の gpx の内容と一致する sidecar の中身。無い・壊れている・一致しない → None (状態不明)。"""
    if not gpx_path:
        return None
    gpx = Path(gpx_path)
    try:
        digest = _sha256(gpx)
    except OSError:
        return None
    for candidate in sidecar_candidates(gpx_path):
        try:
            body = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(body, dict) and body.get("gpx_sha256") == digest:
            return body
    return None
