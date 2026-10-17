"""P1.5 の凍結 manifest を書く (P0 §0)。凍結 commit にだけ使う。

部品の sha256 (改行を LF に揃えた中身)・版・置換の一覧・事後検査の閾値・H-pub の候補の確定数・drand の規則・環境の指紋と、
従う P0 の版 (commit) を 1 つの JSON にする。drand の ``round`` は凍結 commit を push した 24 時間後以降に決まるので
空のまま書き、抽出の作業で別に記録する (この JSON を書き換えない — 後から足すのは抽出 manifest の側)。

    python make_freeze.py --p0-commit <P0 を含む commit> --out freeze_manifest.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from tsumugin.prereg_eval.freeze import freeze_manifest

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--p0-commit", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    m = freeze_manifest(ROOT, p0_commit=args.p0_commit)
    m["generated_at"] = datetime.now(timezone.utc).isoformat()
    Path(args.out).write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                              encoding="utf-8", newline="\n")
    n = sum(len(c["files"]) for c in m["components"].values())
    print(f"components={len(m['components'])} files={n} p0={args.p0_commit} gsas2={m['environment'].get('gsas2')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
