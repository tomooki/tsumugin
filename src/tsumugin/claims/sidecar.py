"""精密化済み gpx の隣の出版状態 ``<stem>.claims.json`` (fit-then-judge P1-1A, REQ-FTJ-1A-502)。

.gpx は値の出版状態を持てないので sidecar に置く。**gpx の内容ハッシュ (sha256)** を記録して 1 対 1 に
結び、読み手 (`read_claims_sidecar`) はハッシュが今の gpx と一致するものだけを採る。gpx が上書きされた
(``keep_gpx`` での再実行) ときの古い sidecar は「状態不明」= 出版不可。

**上書きしない** (P2 非破壊): 同名が既にあり中身が違えば ``<stem>.claims.<ハッシュ先頭 12>.json`` に書く。
同じ状態をもう一度書くのは何もしない。書けないときは例外ではなく理由を返す (フィットを落とさない —
`autorietveld.engine._save_gpx_artifact` と同じ方針)。
"""

from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "find_claims_sidecar", "read_claims_sidecar", "sidecar_candidates", "write_claims_sidecar",
]


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
    # stem に glob の特殊文字 (``[`` 等) があっても取りこぼさない
    pattern = str(gpx.parent / f"{glob.escape(gpx.stem)}.claims.*.json")
    hashed = sorted(Path(p) for p in glob.glob(pattern))
    return [default, *(p for p in hashed if p != default)]


def write_claims_sidecar(gpx_path: str, payload: Mapping[str, Any]) -> tuple[str, str]:
    """sidecar を書く。``(書いたパス, 書けなかった理由)`` — どちらか一方だけが空でない。"""
    if not gpx_path:
        return "", "精密化済み gpx が無い (保存していない) ので sidecar を置く場所が無い"
    gpx = Path(gpx_path)
    try:
        digest = _sha256(gpx)
    except (OSError, ValueError) as exc:  # ValueError: パスに NUL など
        return "", f"gpx を読めない ({type(exc).__name__}: {exc})"
    body = {**dict(payload), "gpx_sha256": digest, "gpx_name": gpx.name}
    try:
        state = json.dumps(body, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=1)
    except (TypeError, ValueError) as exc:
        return "", f"出版状態を JSON にできない ({type(exc).__name__}: {exc})"
    body_digest = hashlib.sha256(state.encode("utf-8")).hexdigest()[:8]
    named = gpx.parent / f"{gpx.stem}.claims.{digest[:12]}.{body_digest}.json"
    # 同じ状態をもう一度書くときは何もしない。状態のハッシュを名前に持つファイルは名前で、名前に持たない
    #   2 つ (既定名・gpx のハッシュの名前) だけ中身で比べる (全部を読み直さない)
    if named.exists():
        return str(named), ""
    existing = sidecar_candidates(gpx_path)
    for legacy in (gpx.with_suffix(".claims.json"), gpx.parent / f"{gpx.stem}.claims.{digest[:12]}.json"):
        try:
            prev = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(prev, dict):
            prev.pop("sequence", None)
            if json.dumps(prev, ensure_ascii=False, sort_keys=True, indent=1) == state:
                return str(legacy), ""
    # 【書いた順を中身に持たせる】: 読み手は同じ gpx の sidecar のうち**最後に書いたもの**を採る。mtime はコピーや
    #   復元で入れ替わるので使わない。時刻ではなく連番にして中身を決定論に保つ。連番は**既存の最大 + 1**
    #   (ファイルの数にすると、消したあとに既存の番号と重なる)。連番を持たない旧版だけならファイルの数。
    #   ⚠ そのために既存の sidecar を読む (1 つの gpx あたり数個なので許容)
    seqs = []
    for c in existing:
        try:
            prev_seq = json.loads(c.read_text(encoding="utf-8")).get("sequence")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(prev_seq, int):
            seqs.append(prev_seq)
    text = json.dumps(
        {**body, "sequence": (max(seqs) + 1) if seqs else sum(1 for c in existing if c.exists())},
        ensure_ascii=False, allow_nan=False, sort_keys=True, indent=1,
    )
    # 【名前は gpx と状態の両方のハッシュで】: gpx のハッシュだけだと、同じ gpx を 3 回以上違う入力で評価したとき
    #   3 回目以降を書けず、読み手が古い状態を返していた。
    for target in (
        gpx.with_suffix(".claims.json"),
        gpx.parent / f"{gpx.stem}.claims.{digest[:12]}.json",
        named,
    ):
        try:
            if target.exists():
                continue  # 中身が違う (同じなら上で返した) — 上書きしない
            with target.open("x", encoding="utf-8") as fh:  # 競合しても上書きしない
                fh.write(text)
            return str(target), ""
        except FileExistsError:
            continue
        except OSError as exc:
            return "", f"sidecar を書けない ({type(exc).__name__}: {exc})"
    return "", "同名の sidecar が既にあり、上書きしない"


def find_claims_sidecar(gpx_path: str) -> tuple[str, dict[str, Any]] | None:
    """今の gpx の内容と一致する sidecar の ``(パス, 中身)``。無い・壊れている・一致しない → None。"""
    if not gpx_path:
        return None
    gpx = Path(gpx_path)
    try:
        digest = _sha256(gpx)
    except (OSError, ValueError):  # ValueError: パスに NUL など — 状態不明として扱う
        return None
    # 同じ gpx に一致する sidecar が複数ある (同じ gpx を相の指定や収束確認を変えて評価し直した)
    #   ときは**最も新しい**ものを採る — 既定名 (= 最初に書いた方) を採ると古い状態を返す。
    matches: list[tuple[float, int, str, dict[str, Any]]] = []
    for order, candidate in enumerate(sidecar_candidates(gpx_path)):
        try:
            body = json.loads(candidate.read_text(encoding="utf-8"))
            mtime = candidate.stat().st_mtime
        except (OSError, ValueError):
            continue
        if isinstance(body, dict) and body.get("gpx_sha256") == digest:
            # 書いた順 (中身の連番) を優先し、連番の無い旧版だけ mtime の順に戻る (旧版は連番 -1 扱い)
            seq = body.get("sequence")
            rank = (int(seq), 0.0) if isinstance(seq, int) else (-1, mtime)
            matches.append((rank, order, str(candidate), body))
    if not matches:
        return None
    _, _, path, body = max(matches, key=lambda m: (m[0], m[1]))
    return path, body


def read_claims_sidecar(gpx_path: str) -> dict[str, Any] | None:
    """今の gpx の内容と一致する sidecar の中身 (`find_claims_sidecar` の中身だけ)。"""
    found = find_claims_sidecar(gpx_path)
    return found[1] if found else None
