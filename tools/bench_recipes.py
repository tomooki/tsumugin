"""並列ベンチマークハーネス — レシピ変種 × 実データを同時実行して比較表を出す (Phase 0-1)。

**なぜ最初に作るか** (architecture.md D7): 改善のたびに 6 データ × 複数レシピを回す必要があり、
1 件ずつ直列に回すと待ちが全作業を律速する (実測: T3 単発 329 秒、T4 は 2.9 時間)。別プロセス
並列 + 比較表出力を先に用意すれば、以降すべての検証が同じ土俵に乗る。

**各改善は単独で測る** — 合成すると原因が切り分けられない。U,V,W の件を特定できたのは
1 変数ずつ測ったからである。

使い方::

    uv run python tools/bench_recipes.py --datasets T1 T3 --recipes default serious
    uv run python tools/bench_recipes.py --all --jobs 4 --out docs/benchmark/stable-auto-rietveld/

GSAS-II と実データが要る (`@pytest.mark.gsas` 相当)。データ未配置は自動 skip。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools"))

from bench_specs import (  # noqa: E402 — sys.path 調整後
    CAMPAIGN_DATASETS,
    DATASETS,
    RECIPES,
)

#: 基準値/チュートリアル値は `bench_specs.DATASETS` が持つ (二重管理をやめた)。
BASELINE: dict[str, float] = {
    k: v.baseline_rwp for k, v in DATASETS.items() if v.baseline_rwp is not None
}
TUTORIAL: dict[str, float] = {
    k: v.tutorial_rwp for k, v in DATASETS.items() if v.tutorial_rwp is not None
}

#: 日常ベンチマークから外すデータセット。**T4 の serious は 1 回 ~3 時間**かかり、反復の
#: フィードバックループを壊す。`--all` は既定でこれを除き、節目でだけ `--with-slow` を付ける。
SLOW_DATASETS: tuple[str, ...] = tuple(k for k, v in DATASETS.items() if v.slow)


@dataclass
class BenchResult:
    dataset: str
    recipe: str
    rwp: "float | None"
    gof: "float | None"
    n_stages: int
    n_reverted: int
    seconds: float
    status: str  # ok | skipped | failed
    detail: str = ""

    @property
    def delta_vs_baseline(self) -> "float | None":
        base = BASELINE.get(self.dataset)
        if base is None or self.rwp is None:
            return None
        return self.rwp - base


def _available(name: str) -> bool:
    return DATASETS[name].available


def _child_script() -> str:
    """子プロセスで実行する 1 件ぶんのランナー (stdout に JSON 1 行を出す)。"""
    return str(Path(__file__).with_name("_bench_one.py"))


def run_one(dataset: str, recipe: str, timeout_s: float,
            out_dir: "Path | None" = None) -> BenchResult:
    """1 (データセット, レシピ) を**別プロセス**で実行する。

    別プロセスにする理由: GSAS-II は大量のグローバル状態を持ち、同一プロセスで連続実行すると
    前の精密化の状態が漏れる懸念がある。プロセス分離なら並列化と隔離が同時に得られる。
    """
    if not _available(dataset):
        return BenchResult(dataset, recipe, None, None, 0, 0, 0.0, "skipped", "データ未配置")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, _child_script(), dataset, recipe]
            + ([str(out_dir)] if out_dir is not None else []),
            capture_output=True, text=True, timeout=timeout_s, cwd=str(_REPO),
            # ⚠ **親側の復号も UTF-8 で明示する**。`text=True` だけだと親は
            #   `locale.getpreferredencoding()` (Windows では cp932) で復号し、子が出す
            #   日本語の段 note で `UnicodeDecodeError` を起こす。この例外は読み取り
            #   スレッドの中で死ぬので **`proc.stdout` が黙って None になる**だけで、
            #   returncode は 0 のまま = 「実行は成功したのに出力が無い」に見える。
            #   `PYTHONIOENCODING` は**子の出力**を UTF-8 にするだけで親の復号は直さない。
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return BenchResult(dataset, recipe, None, None, 0, 0, time.time() - t0,
                           "failed", f"timeout ({timeout_s:.0f}s)")
    elapsed = time.time() - t0
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            return BenchResult(
                dataset, recipe, payload.get("rwp"), payload.get("gof"),
                int(payload.get("n_stages", 0)), int(payload.get("n_reverted", 0)),
                elapsed, "ok",
                f"validity={payload.get('validity', '?')}",
            )
    tail = (proc.stderr or proc.stdout).strip().splitlines()
    return BenchResult(dataset, recipe, None, None, 0, 0, elapsed, "failed",
                       tail[-1][:200] if tail else "no output")


def format_table(results: list[BenchResult]) -> str:
    """比較表 (Markdown)。**行 = 候補 / 列 = データ**に転置してある。

    候補が 2 本のうちは列に並べられたが、10 案では横に伸びて読めない。基準値との差は
    ✅/⚠ で必ず併記する — 回帰を見落とさないため。
    """
    recipes = sorted(
        {r.recipe for r in results},
        key=lambda x: RECIPES.index(x) if x in RECIPES else 99,
    )
    datasets = sorted({r.dataset for r in results}, key=lambda d: list(DATASETS).index(d))
    by = {(r.dataset, r.recipe): r for r in results}

    lines = [
        "| 候補 | 軸 | " + " | ".join(datasets) + " | 計 (分) |",
        "|---|---|" + "---|" * (len(datasets) + 1),
    ]
    for rec in recipes:
        cells, total = [], 0.0
        for d in datasets:
            r = by.get((d, rec))
            if r is None or r.status != "ok" or r.rwp is None:
                cells.append(f"— ({r.status})" if r else "—")
                continue
            total += r.seconds
            delta = r.delta_vs_baseline
            mark = ""
            if delta is not None:
                mark = " ✅" if delta <= -0.05 else (" ⚠" if delta > 0.05 else "")
            cells.append(f"{r.rwp:.2f}{mark}")
        axis = ""
        try:
            from bench_specs import RECIPE_REGISTRY

            axis = RECIPE_REGISTRY[rec].axis
        except Exception:  # noqa: BLE001 — 未登録の名前は空欄
            axis = ""
        lines.append(f"| {rec} | {axis} | " + " | ".join(cells) + f" | {total / 60:.1f} |")

    lines.append("")
    lines.append("| データ | 基準 | チュートリアル |")
    lines.append("|---|---|---|")
    for d in datasets:
        base = BASELINE.get(d)
        tut = TUTORIAL.get(d)
        lines.append(
            f"| {d} | {'' if base is None else f'{base:.2f}%'} | "
            f"{'' if tut is None else f'{tut:.2f}%'} |"
        )
    return "\n".join(lines)


def main(argv: "list[str] | None" = None) -> int:
    # Windows の既定コンソールは cp932 で、表の記号 (✅/⚠/—) が UnicodeEncodeError になる。
    # 測定が終わってから出力で落ちるのが最悪なので、最初に UTF-8 へ寄せる。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datasets", nargs="*", default=None, choices=list(DATASETS))
    ap.add_argument("--recipes", nargs="*", default=["default"], choices=list(RECIPES))
    ap.add_argument("--all", action="store_true",
                    help=f"全データ × 全レシピ (既定で {SLOW_DATASETS} を除く)")
    ap.add_argument("--with-slow", action="store_true",
                    help=f"低速データ {SLOW_DATASETS} も含める (節目のみ)")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    ap.add_argument("--timeout", type=float, default=4 * 3600, help="1 件あたりの上限秒")
    ap.add_argument("--out", type=Path, default=None, help="Markdown 出力先ディレクトリ")
    ap.add_argument("--label", default="", help="表に付ける見出し (何を測ったか)")
    args = ap.parse_args(argv)

    if args.all:
        # キャンペーンの対象は `bench_specs.CAMPAIGN_DATASETS` が唯一の定義 (T4 除外の理由も
        # そこに書いてある)。`--with-slow` のときだけ低速データを足す。
        datasets = list(CAMPAIGN_DATASETS)
        if args.with_slow:
            datasets += [d for d in DATASETS if d not in datasets]
    else:
        datasets = args.datasets or ["T1"]
    if args.all and not args.with_slow:
        print(f"# 低速データ {SLOW_DATASETS} を除外 (--with-slow で含める)", flush=True)
    recipes = list(RECIPES) if args.all else args.recipes
    jobs = [(d, r) for d in datasets for r in recipes]

    print(f"# {len(jobs)} 件を最大 {args.jobs} 並列で実行", flush=True)
    results: list[BenchResult] = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(run_one, d, r, args.timeout, args.out): (d, r) for d, r in jobs
        }
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            rwp = f"{res.rwp:.3f}%" if res.rwp is not None else "—"
            print(f"  [{res.status:7s}] {res.dataset:8s} {res.recipe:8s} "
                  f"Rwp={rwp:>9s} ({res.seconds / 60:.1f}m) {res.detail}", flush=True)

    table = format_table(results)
    print("\n" + table)

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d-%H%M")
        path = args.out / f"{stamp}.md"
        body = [f"# ベンチマーク {stamp}", ""]
        if args.label:
            body += [f"**測定対象**: {args.label}", ""]
        body += [table, "", "## 生データ", "", "```json",
                 json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), "```"]
        path.write_text("\n".join(body), encoding="utf-8")
        print(f"\n→ {path}")
    return 0 if all(r.status != "failed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
