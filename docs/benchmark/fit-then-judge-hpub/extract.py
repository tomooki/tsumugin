"""P0 §3.2.1-3/4/5/11: 凍結の後の `H-pub` の抽出 (凍結版のスクリプトではない — 凍結 manifest の部品を変えないために
ここに置く。手続きは凍結した規則 `freeze_manifest.json` の ``drand`` と P0 に従う)。

1. 凍結 commit を push した時刻 (GitHub のサーバー側) の 24 時間後以降で**最初の** drand round を求め、その値 r を取る。
2. 参照あり (`H-pub-ref`) は候補が 3K 未満なら**全部** (抽出しない)。参照なし (`H-pub-noref`) は
   ``draw_order(候補, r, "h-pub-noref")`` の順に先頭から ``k_noref`` 件 (凍結 manifest の値)。
3. 取得できない・読めない・開発用の化合物に当たった事例は理由を記録して**置換の順で次の候補**へ。
4. 採用した事例のファイルはスナップショットから**取り出して sha256 を計算するだけ** (中身を開かない・表示しない)。
5. public の抽出 manifest には salt 付きのハッシュ・置換の理由の種類・ファイルの sha256・round を書く。平文の ID と
   ファイル名は私的 ledger (リポジトリの外) に置く。

    python extract.py --freeze <freeze_manifest.json> --push-time 2026-10-17T14:41:50Z --snapshot <dir>
        --private-candidates <json> --salt-file <txt> --ledger <jsonl> --out <extraction_manifest.json>
        [--private-exclude <json: 開発用の未公開データの化合物の ID の一覧>] [--drand-json <round の JSON>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: drand の公開ビーコン (League of Entropy の default chain)。chain hash は取得した info から記録する
DRAND_BASE = "https://api.drand.sh"
WAIT = timedelta(hours=24)


def first_round_at_or_after(t: float, *, genesis: float, period: float) -> int:
    """時刻 ``t`` (UNIX 秒) 以後で最初の round。round 1 は ``genesis``、以後 ``period`` 秒ごと。"""
    if t <= genesis:
        return 1
    return int(math.ceil((t - genesis) / period)) + 1


def select(order: Sequence[str], k: int, reject: Callable[[str], str | None]) -> tuple[list[str], list[tuple[str, str]]]:
    """置換の順に先頭から ``k`` 件採る。``reject(id)`` が理由を返した事例は飛ばして記録する。足りなければ足りないまま返す。"""
    adopted: list[str] = []
    replaced: list[tuple[str, str]] = []
    for entry in order:
        if len(adopted) >= k:
            break
        why = reject(entry)
        if why:
            replaced.append((entry, why))
        else:
            adopted.append(entry)
    return adopted, replaced


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 — 固定の公開ビーコン
        return json.loads(r.read().decode("utf-8"))


def _members_by_id(snapshot: Path) -> dict[str, list[str]]:
    """候補のスクリプトと同じ入口 (ヘッダの解析) で、ID → スナップショット内のファイル名。中身は表示しない。"""
    from tsumugin.prereg_eval.hpub import STATUS_CONFIRMED, decode_raw, parse_raw_header, profile_shape_ok

    out: dict[str, list[str]] = {}
    with zipfile.ZipFile(snapshot / "rruff_dl" / "XY_RAW.zip") as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            h = parse_raw_header(decode_raw(z.read(info)))
            if h.rruff_id and profile_shape_ok(h) and h.status in STATUS_CONFIRMED:
                out.setdefault(h.rruff_id, []).append(info.filename)
    for names in out.values():
        names.sort()
    return out


def main() -> int:
    from tsumugin.prereg_eval.hpub import SNAPSHOT_SHA256, salted_hash
    from tsumugin.prereg_eval.hpub_draw import ascending, draw_order

    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", required=True)
    ap.add_argument("--push-time", required=True, help="凍結 commit の push 時刻 (GitHub のサーバー側, ISO 8601 UTC)")
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--private-candidates", required=True)
    ap.add_argument("--salt-file", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--private-exclude", default="")
    ap.add_argument("--drand-json", default="", help="取得済みの round の JSON (無ければ取得する)")
    args = ap.parse_args()

    freeze = json.loads(Path(args.freeze).read_text(encoding="utf-8"))
    push = datetime.fromisoformat(args.push_time.replace("Z", "+00:00"))
    earliest = push + WAIT
    if datetime.now(timezone.utc) < earliest:
        raise SystemExit(f"まだ早い: {earliest.isoformat()} より後に走らせる")

    info = _fetch_json(f"{DRAND_BASE}/info")
    rnd = first_round_at_or_after(earliest.timestamp(), genesis=float(info["genesis_time"]), period=float(info["period"]))
    beacon = (json.loads(Path(args.drand_json).read_text(encoding="utf-8")) if args.drand_json
              else _fetch_json(f"{DRAND_BASE}/public/{rnd}"))
    if int(beacon["round"]) != rnd:
        raise SystemExit(f"round が違う: {beacon['round']} != {rnd}")
    r = str(beacon["randomness"])

    snapshot = Path(args.snapshot)
    for rel, want in SNAPSHOT_SHA256.items():
        h = hashlib.sha256()
        with (snapshot / rel).open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            raise SystemExit(f"snapshot {rel} sha256 mismatch")

    cands = json.loads(Path(args.private_candidates).read_text(encoding="utf-8"))
    ref_ids = [c["rruff_id"] for c in cands["ref"]]
    noref_ids = [c["rruff_id"] for c in cands["noref"]]
    salt = Path(args.salt_file).read_text(encoding="utf-8").strip()
    exclude = set(json.loads(Path(args.private_exclude).read_text(encoding="utf-8"))) if args.private_exclude else set()
    members = _members_by_id(snapshot)

    def reject(entry: str) -> str | None:
        if entry in exclude:
            return "development compound"
        if not members.get(entry):
            return "file not found in snapshot"
        return None

    k_ref, k_noref = int(freeze["hpub"]["k_ref"]), int(freeze["hpub"]["k_noref"])
    # 参照ありは候補が 3K 未満なので全部 (抽出しない) — 順は ID の昇順のまま
    ref_order = ascending(ref_ids) if k_ref == len(ref_ids) else draw_order(ref_ids, r, "h-pub")
    ref_adopted, ref_replaced = select(ref_order, k_ref, reject)
    noref_adopted, noref_replaced = select(draw_order(noref_ids, r, "h-pub-noref"), k_noref, reject)

    sha_of: dict[str, str] = {}
    with zipfile.ZipFile(snapshot / "rruff_dl" / "XY_RAW.zip") as z:
        for entry in ref_adopted + noref_adopted:
            # 1 種 1 標本: 同じ ID に複数ファイルがあればファイル名の昇順の先頭 (決定論)
            sha_of[entry] = hashlib.sha256(z.read(members[entry][0])).hexdigest()

    def public(adopted: list[str], replaced: list[tuple[str, str]]) -> dict:
        return {
            "adopted": [{"salted_id": salted_hash(salt, e), "file_sha256": sha_of[e]} for e in adopted],
            "replaced": [{"salted_id": salted_hash(salt, e), "reason": why} for e, why in replaced],
            "n_adopted": len(adopted),
        }

    manifest = {
        "freeze_p0_commit": freeze["p0_commit"],
        "push_time": push.isoformat(), "earliest": earliest.isoformat(),
        "drand": {"base": DRAND_BASE, "chain_hash": info.get("hash"), "round": rnd, "randomness": r,
                  "signature": beacon.get("signature")},
        "ref": {**public(ref_adopted, ref_replaced), "k": k_ref},
        "noref": {**public(noref_adopted, noref_replaced), "k": k_noref},
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
    }
    Path(args.out).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    with Path(args.ledger).open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "time": datetime.now(timezone.utc).isoformat(), "stage": "extract", "round": rnd,
            "ref": {"adopted": ref_adopted, "replaced": ref_replaced},
            "noref": {"adopted": noref_adopted, "replaced": noref_replaced},
            "files": {e: members[e][0] for e in ref_adopted + noref_adopted},
        }, ensure_ascii=False) + "\n")
    print(f"round={rnd} ref={len(ref_adopted)}/{k_ref} (replaced {len(ref_replaced)}) "
          f"noref={len(noref_adopted)}/{k_noref} (replaced {len(noref_replaced)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
