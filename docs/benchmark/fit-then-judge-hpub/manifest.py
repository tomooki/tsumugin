"""P0 §3.2.1-4/7/11: 凍結時に commit する `H-pub` の public 候補 manifest と、全事例に共通の汎用装置パラメータを書く。

入力は `candidates.py --stage cif --include-noref --private-out` の私的な候補一覧 (リポジトリの外) と、その ledger。
public に出すのは salt 付きの ID のハッシュ・件数・除外理由の種類ごとの件数・汎用装置パラメータ (S-dev の生成器で宣言した
実験室 Bragg-Brentano Cu Kα1/Kα2 の値そのまま) とその sha256 だけ。salt は無ければ作ってリポジトリの外に置き、表示しない。

    python manifest.py --private-candidates <json> --ledger <jsonl> --salt-file <txt> --out <manifest.json> --instprm <out.instprm>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from tsumugin.prereg_eval.hpub_draw import public_manifest
from tsumugin.prereg_eval.synth_gsas import INSTRUMENT_DEFS, _instprm_text


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _salt(path: Path) -> str:
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def _latest_cif_counts(ledger: Path) -> dict[str, int]:
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    cif = [r for r in rows if r.get("stage") == "cif" and r.get("include_noref") and not r.get("relaxed")]
    if not cif:
        raise SystemExit("ledger に参照なし込みの cif 段の記録が無い")
    return {k: int(v) for k, v in cif[-1]["counts"].items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-candidates", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--salt-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--instprm", required=True)
    args = ap.parse_args()

    cand_path = Path(args.private_candidates)
    cands = json.loads(cand_path.read_text(encoding="utf-8"))
    ref_ids = [c["rruff_id"] for c in cands["ref"]]
    noref_ids = [c["rruff_id"] for c in cands["noref"]]
    salt = _salt(Path(args.salt_file))

    lab = INSTRUMENT_DEFS["lab_bb"]
    instprm = _instprm_text(lab, sh_l=lab["sh_l"], ka2_ratio=lab["ka2_ratio"], zero=0.0)
    Path(args.instprm).write_text(instprm, encoding="utf-8", newline="\n")

    m = public_manifest(salt, ref_ids, noref_ids, _latest_cif_counts(Path(args.ledger)))
    m["generic_instrument"] = {"source": "prereg_eval.synth_gsas.INSTRUMENT_DEFS['lab_bb'] (zero=0)",
                               "file": Path(args.instprm).name, "sha256": _sha(instprm.encode("utf-8"))}
    m["script_sha256"] = _sha(Path(__file__).read_bytes())
    Path(args.out).write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    with Path(args.ledger).open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "time": datetime.now(timezone.utc).isoformat(), "stage": "manifest",
            "script_sha256": m["script_sha256"], "candidates_sha256": _sha(cand_path.read_bytes()),
            "salt_sha256": _sha(salt.encode("utf-8")), "n_ref": len(ref_ids), "n_noref": len(noref_ids),
            "k_ref": m["k_ref"], "k_noref": m["k_noref"],
        }) + "\n")
    print(f"n_ref={len(ref_ids)} n_noref={len(noref_ids)} k_ref={m['k_ref']} k_noref={m['k_noref']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
