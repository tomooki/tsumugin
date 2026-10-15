"""`H-pub` の候補一覧を作る (fit-then-judge P0 §3.2.1-2。凍結版に含める)。

    uv run python docs/benchmark/fit-then-judge-hpub/candidates.py --snapshot <dir> --stage metadata

**表示するのは件数だけ** (種名・ID・セル・強度は出さない)。段階:

- ``metadata``: RRUFF のヘッダ (許された項目だけ) と COD のメタデータで絞る (パターンの形・STATUS・1 種 1 標本・
  組成の一致・常温常圧のメタデータ・除外・出発構造の有無・別出版物で AMCSD 由来でない参照の候補の有無)。CIF は取得しない。
- ``cif`` (2026-10-15 にユーザーが取得を承認): 候補の COD の CIF をミラーから取得 (キャッシュはリポジトリの外) し、
  CSV の ``svnrevision`` と CIF の ``#$Revision$`` の一致・CIF のタグの常温常圧・自由座標 3 以上 (出発構造)・
  H 以外の全自由座標の esd (参照構造) を検査して確定する。自由軸はサイト対称から (`topas.symmetry` の射影 =
  GSAS の ``GetCSxinel`` と同じ意味)。esd は**参照構造自身の自由軸**で見る (出発と同じ空間群なので同じ Wyckoff の組。
  原子の対応は §3.2.1-6 で後から作る)。

入力のスナップショットは sha256 を照合してから読む (P0 §3.2.1-1 の固定)。走らせるたびに私的な ledger
(``--ledger``、リポジトリの外) に、スクリプトの sha256・入力の sha256・段階ごとの件数を追記する (何度走らせたかを隠さない)。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "docs" / "benchmark" / "fit-then-judge-synthetic"))

from cases import SOURCES as SDEV_SOURCES  # noqa: E402

from tsumugin.prereg_eval.hpub import (  # noqa: E402
    STATUS_CONFIRMED,
    cif_tags,
    cod_revision,
    free_coordinate_count,
    has_all_free_esds,
    decode_raw,
    is_room_conditions,
    normalize_mineral,
    parse_raw_header,
    profile_shape_ok,
    publication_key,
    rruff_fractions,
)
from tsumugin.prereg_eval.synth import EXCLUDED_COMPOUNDS, _same_composition, composition_fractions  # noqa: E402

#: P0 §3.2.1-1 で固定したスナップショット
SNAPSHOT_SHA256 = {
    "rruff_dl/XY_RAW.zip": "948a133482bb3c99da80194cc2848933aee668129beb209150f7f850cd4b0587",
    "cod_dl/cod_all.csv": "95f08e5dc85aaef0b0f020e148b46b4ba85977074c8c34d1987db9cc7ab9ecac",
}

#: ゲート確認に使った種 (P0 §3.2.1-10。名前で除く)
GATE_SPECIES = ("fluorite", "anglesite", "quartz", "calcite", "corundum")

#: 開発に使った化合物 (公開の記録にあるもの。P0 §3.2.1-2 — 未公開データの化合物はここに書かない)
DEV_COMPOUNDS = (
    "Y3 Fe5 O12",  # T2 garnet (チュートリアル, p1-1a.md) の端成分
    "Y3 Al5 O12",
    "Cu Cr2 O4",  # M9 parametric sequential (チュートリアル)
    "Cu O",
    "Na Cl",  # P1-1A の検査器の対照
    "Ti0.5 Sn0.5 O2",
    *(s.formula for s in SDEV_SOURCES.values()),  # 合成 S-dev
)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _excluded_by_composition(comp: dict[str, float]) -> str | None:
    for formula, why in EXCLUDED_COMPOUNDS.items():
        ref = composition_fractions(formula)
        if ref and _same_composition(comp, ref):
            return "quasi-holdout or gate compound"
    for formula in DEV_COMPOUNDS:
        ref = composition_fractions(formula)
        if ref and _same_composition(comp, ref):
            return "development compound"
    return None


def _rruff_id_number(rid: str) -> int:
    m = re.search(r"(\d+)", rid)
    return int(m.group(1)) if m else 10**12


def _composition_match(a: dict[str, float], b: dict[str, float], relaxed: bool) -> bool:
    """既定は化学量論の一致。``relaxed`` は P0 G5 の緩め方 (元素の集合の一致) — 候補が 3K に届かないときに 1 回だけ使う。"""
    return set(a) == set(b) if relaxed else _same_composition(a, b)


def stage_metadata(
    snapshot: Path, *, relaxed: bool = False, include_noref: bool = False
) -> tuple[dict[str, int], dict[str, dict]]:
    """(段階ごとの件数, 種 → 内部記録)。内部記録は表示しない。"""
    counts: Counter[str] = Counter()
    species: dict[str, dict] = {}
    with zipfile.ZipFile(snapshot / "rruff_dl" / "XY_RAW.zip") as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            counts["rruff_files"] += 1
            h = parse_raw_header(decode_raw(z.read(info)))
            if not profile_shape_ok(h):
                counts["drop_profile_shape"] += 1
                continue
            if h.status not in STATUS_CONFIRMED:
                counts["drop_status"] += 1
                continue
            name = normalize_mineral(h.names.split(",")[0]) if h.names else ""
            if not name or not h.rruff_id:
                counts["drop_no_name_or_id"] += 1
                continue
            prev = species.get(name)
            if prev is None or _rruff_id_number(h.rruff_id) < _rruff_id_number(prev["rruff_id"]):
                species[name] = {"rruff_id": h.rruff_id, "ideal": h.ideal_chemistry}
    counts["species_after_rruff_filters"] = len(species)

    for name in list(species):
        rec = species[name]
        comp = rruff_fractions(rec["ideal"])
        if comp is None:
            counts["drop_uninterpretable_chemistry"] += 1
            del species[name]
            continue
        if name in GATE_SPECIES:
            counts["drop_gate_species"] += 1
            del species[name]
            continue
        why = _excluded_by_composition(comp)
        if why:
            counts[f"drop_{why.replace(' ', '_')}"] += 1
            del species[name]
            continue
        rec["comp"] = comp

    csv.field_size_limit(10**9)
    rows_by: dict[str, list[dict]] = {}
    with (snapshot / "cod_dl" / "cod_all.csv").open(encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(line for line in f if not line.startswith("#")):
            key = normalize_mineral((r.get("mineral") or "").strip())
            if key in species:
                rows_by.setdefault(key, []).append(r)

    for name in list(species):
        rec = species[name]
        rows = rows_by.get(name, [])
        ok = []
        for r in rows:
            comp = composition_fractions((r.get("formula") or "").strip("- ").strip())
            if comp is None or not _composition_match(comp, rec["comp"], relaxed):
                continue
            if not is_room_conditions(r, {}, r.get("title") or ""):
                continue
            ok.append(r)
        if not ok:
            counts["drop_no_cod_entry_matching"] += 1
            del species[name]
            continue
        ok.sort(key=lambda r: int(r["file"]))
        start = ok[0]
        start_pub = publication_key(start)
        refs = [
            r for r in ok[1:]
            if not r["file"].startswith("9")
            and (pk := publication_key(r)) is not None and pk != start_pub
            and (r.get("sgNumber") or "") == (start.get("sgNumber") or "")
        ]
        rec["has_ref_candidates"] = bool(refs)
        if not refs:
            counts["drop_no_independent_reference_candidate"] += 1
            if not include_noref:
                del species[name]
                continue
        rec["entries"] = [
            {"file": r["file"], "pub": publication_key(r), "sg": (r.get("sgNumber") or ""),
             "rev": (r.get("svnrevision") or "").strip(), "powder": (r.get("method") or "").strip().lower() == "powder diffraction",
             "title": r.get("title") or ""}
            for r in ok
        ]
    counts["species_after_metadata"] = sum(1 for r in species.values() if r.get("has_ref_candidates"))
    if include_noref:
        counts["noref_pool_after_metadata"] = sum(1 for r in species.values() if not r.get("has_ref_candidates"))
    return dict(counts), species


_MIRROR = "https://qiserver.ugr.es/cod/{id}.cif"


def _fetch(cod_id: str, cache: Path) -> str | None:
    import time
    import urllib.request

    path = cache / f"{cod_id}.cif"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(_MIRROR.format(id=cod_id), timeout=60) as r:  # noqa: S310 — 固定の COD ミラー
                path.write_bytes(r.read())
        except OSError:
            return None
        time.sleep(0.2)  # ミラーに負荷を掛けない
    return path.read_text(encoding="utf-8", errors="replace")


def _cif_usable(entry: dict, cache: Path, counts: Counter) -> str | None:
    """取得でき・版が CSV と一致し・CIF のタグが常温常圧なら CIF の本文。"""
    text = _fetch(entry["file"], cache)
    if text is None:
        counts["cif_unavailable"] += 1
        return None
    if cod_revision(text) != entry["rev"]:
        counts["cif_revision_mismatch"] += 1
        return None
    if not is_room_conditions({}, cif_tags(text), entry["title"]):
        counts["cif_not_room_conditions"] += 1
        return None
    return text


def stage_cif(
    species: dict[str, dict], cache: Path, *, include_noref: bool = False
) -> tuple[dict[str, int], dict[str, dict], dict[str, dict]]:
    """(件数, 参照あり, 参照なし)。参照なし (P0 v1.5 §3.2.1-11) は参照の条件**だけ**を満たさない種。"""
    counts: Counter[str] = Counter()
    final: dict[str, dict] = {}
    noref: dict[str, dict] = {}
    for name, rec in species.items():
        start = start_text = None
        for e in rec["entries"]:
            text = _cif_usable(e, cache, counts)
            if text is not None:
                start, start_text = e, text
                break
        if start is None:
            counts["drop_no_usable_start"] += 1
            continue
        n_free = free_coordinate_count(start_text)
        if n_free is None or n_free < 3:
            counts["drop_free_coordinates_lt3"] += 1
            continue
        if not rec.get("has_ref_candidates"):
            noref[name] = {"rruff_id": rec["rruff_id"], "start": start["file"]}
            continue
        refs = [e for e in rec["entries"] if e is not start and not e["file"].startswith("9")
                and e["pub"] is not None and e["pub"] != start["pub"] and e["sg"] == start["sg"]]
        refs.sort(key=lambda e: (e["powder"], int(e["file"])))
        ref = None
        for e in refs:
            text = _cif_usable(e, cache, counts)
            if text is not None and has_all_free_esds(text):
                ref = e
                break
        if ref is None:
            counts["drop_no_reference_with_esd"] += 1
            if include_noref:
                noref[name] = {"rruff_id": rec["rruff_id"], "start": start["file"]}
            continue
        final[name] = {"rruff_id": rec["rruff_id"], "start": start["file"], "reference": ref["file"]}
    counts["candidates"] = len(final)
    if include_noref:
        counts["noref_candidates"] = len(noref)
    return dict(counts), final, noref


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--stage", choices=("metadata", "cif"), default="metadata")
    ap.add_argument("--cif-cache", default="")
    ap.add_argument("--private-out", default="", help="候補の平文 ID の書き出し先 (リポジトリの外)")
    ap.add_argument("--ledger", default="")
    ap.add_argument("--relaxed", action="store_true", help="P0 G5 の緩め方 (元素の集合の一致) を使う")
    ap.add_argument("--include-noref", action="store_true",
                    help="P0 v1.5 §3.2.1-11 の参照なしの候補も作る (出発構造の CIF を多数取得する)")
    args = ap.parse_args()
    snapshot = Path(args.snapshot)
    shas = {rel: _sha(snapshot / rel) for rel in SNAPSHOT_SHA256}
    for rel, want in SNAPSHOT_SHA256.items():
        if shas[rel] != want:
            raise SystemExit(f"snapshot {rel} sha256 mismatch")
    counts, species = stage_metadata(snapshot, relaxed=args.relaxed, include_noref=args.include_noref)
    if args.stage == "cif":
        if not args.cif_cache:
            raise SystemExit("--cif-cache が要る (リポジトリの外)")
        cif_counts, final, noref = stage_cif(species, Path(args.cif_cache), include_noref=args.include_noref)
        counts.update({f"cif_{k}": v for k, v in cif_counts.items()})
        if args.private_out:
            order = lambda r: _rruff_id_number(r["rruff_id"])  # noqa: E731
            Path(args.private_out).write_text(json.dumps(
                {"ref": sorted(final.values(), key=order), "noref": sorted(noref.values(), key=order)}, indent=1),
                encoding="utf-8")
    for k in sorted(counts):
        print(f"{k}: {counts[k]}")
    if args.ledger:
        with Path(args.ledger).open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "time": datetime.now(timezone.utc).isoformat(), "stage": args.stage, "relaxed": args.relaxed,
                "include_noref": args.include_noref,
                "script_sha256": _sha(Path(__file__)), "inputs": shas, "counts": counts,
            }) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
