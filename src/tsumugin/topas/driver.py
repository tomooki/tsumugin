"""tc.exe ドライバ (M12 T5) — INP を書き、TOPAS を起動し、出力を回収する。

このモジュールの主目的は **T0 実測で判明した 2 つの罠を構造的に潰すこと**である。

1. **tc.exe は INP の構文エラーで異常終了しても終了コード 0 を返す。**
   これは GSAS-II の ``G2Project.refine`` が ``GSASIIstrMain.Refine`` の失敗戻り値を捨てる
   問題 (CLAUDE.md) と同じクラスの罠で、放置すると「無言で何も精密化していない段」が
   ``rwp`` にも ``reverted`` にも現れないまま完走する。したがって成否は
   **stdout の異常終了マーカー + 出力ファイルの生成有無**の二重の網で判定する。
2. **TOPAS は空間群生成で ``sgcom6.exe`` を子プロセス起動し、これは PATH からしか引かれない。**
   tc.exe を絶対パスで叩いても、PATH にインストールディレクトリが無いと
   ``Cannot open file c:\\topas7\\sg\\<sg>.sg`` で異常終了する。よって起動時に
   ``topas_home()`` を PATH の先頭へ足す。

失敗は :class:`~tsumugin.errors.TopasRunError` で送出し、**エンジン層がこれを chi2=inf へ
縮退させてガードレールに処理させる** (不変条件「バックエンドの失敗は例外でなく chi2=inf に変換」)。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..errors import TopasRunError
from .availability import require_tc_exe, topas_home

__all__ = ["TopasRun", "run_tc", "thread_count"]

_FAILURE_MARKERS: tuple[str, ...] = (
    "Abnormal program termination",
    "*** Error",
    "Cannot open file",
    "Cannot locate",
)
"""stdout に現れたら失敗とみなす文字列 (実測)。"""

_DIAGNOSTIC_MARKERS: tuple[str, ...] = ("Invalid d spacing", "Negative FWHM")
"""失敗が**すでに確定したとき**にだけ拾う診断行 (実測)。

TOPAS は根本原因を ``Abnormal program termination`` の直前に 1 行で書くことがあるが、
その文言自体は失敗の判定材料にしない — 警告として出て完走する可能性を排除できないため
(判定を広げると「動いていたものが落ちる」側の誤りになる)。"""

_DEFAULT_TIMEOUT = 1800.0


@dataclass(frozen=True)
class TopasRun:
    """1 回の tc.exe 実行の結果。"""

    stdout: str
    out_text: str
    """``<basename>.out`` の内容 (精密化後の INP)。"""
    results_text: str
    """``results.txt`` の内容 (Out() が吐いたタブ区切りレコード)。無ければ空文字。"""
    workdir: str
    basename: str


def _failure_reason(stdout: str) -> "str | None":
    """stdout の失敗マーカー行を**すべて**集約して返す (無ければ None)。

    最初の 1 行だけでは診断に足りない: TOPAS は根本原因 (``*** Error loading …``) と
    結果 (``Abnormal program termination``) を別々の行に出すため、両方を残す。
    """
    hits: list[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped in hits:
            continue
        if any(marker in stripped for marker in _FAILURE_MARKERS):
            hits.append(stripped)
    if not hits:
        return None
    # 失敗が確定してから診断行を足す (原因の文言を落とすと Rwp からは辿れない)。
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped and stripped not in hits and any(
            marker in stripped for marker in _DIAGNOSTIC_MARKERS
        ):
            hits.append(stripped)
    return " | ".join(hits)


def thread_count(raw: "str | None") -> str:
    """``TSUMUGIN_TOPAS_THREADS`` を検証して ``OMP_NUM_THREADS`` の値へ (既定 "1")。

    **``autorietveld.backends.describe_backends`` と共有する** — ② が報告するスレッド数と
    実際に tc.exe を起動する値が別実装だと、報告が嘘になる。

    **空/非数値/0 以下は既定へ戻す** — 素通しすると OpenMP の実装依存挙動になり、
    「再現性を取っているつもりで取れていない」が結果に現れない (② の「空/不正入力を
    正常と答えない」と同じ規律)。
    """
    if raw is None or not raw.strip():
        return "1"
    try:
        count = int(raw.strip())
    except ValueError:
        return "1"
    return str(count) if count >= 1 else "1"


def run_tc(
    inp_text: str,
    *,
    workdir: "str | Path",
    basename: str = "refine",
    results_name: str = "results.txt",
    timeout: float = _DEFAULT_TIMEOUT,
) -> TopasRun:
    """INP を書き出して tc.exe を実行し、出力を回収する。

    :param inp_text: INP の全文 (`topas.inp.TopasDocument.render()` の出力)
    :param workdir: 作業ディレクトリ。**データファイルもここに置く** (INP のパスは
        ここからの相対で解決される)。cwd をここにして実行する。
    :param basename: 拡張子なしのベース名。tc はこれを引数に取り ``<basename>.out`` を書く。
    :raises TopasUnavailableError: tc.exe が解決できないとき
    :raises TopasRunError: 異常終了・タイムアウト・出力欠落
    """
    exe = require_tc_exe()
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    inp_path = work / f"{basename}.inp"
    inp_path.write_text(inp_text, encoding="utf-8")

    out_path = work / f"{basename}.out"
    results_path = work / results_name
    # 前回の残骸を成功と誤読しないよう、実行前に消しておく。
    for stale in (out_path, results_path):
        if stale.exists():
            stale.unlink()

    env = os.environ.copy()
    home = topas_home()
    if home is not None:
        # 【sgcom6 対策】: 空間群生成の子プロセスは PATH からしか引かれない。
        env["PATH"] = f"{home}{os.pathsep}{env.get('PATH', '')}"
    # 【再現性 (NFR-102)】: **tc.exe はスレッド数で結果が変わる**。悪条件な最小二乗では
    #   総和順序がスレッド割り当てで変わり、同じ入力の T4 が 43.49 / 67.62 / 43.49 /
    #   29.29% に散らばった (分岐点は X 線 Lorentzian 段の受理/revert)。1 スレッドなら
    #   ビット同一になる (実測)。**Rwp が実行ごとに変わると段の受理判定も BIC 比較も
    #   ベンチマークも意味を失う**ので既定は再現性を取る。速度が要る場面のために
    #   ``TSUMUGIN_TOPAS_THREADS`` で外せる (再現性を捨てる、という明示的な選択)。
    env["OMP_NUM_THREADS"] = thread_count(env.get("TSUMUGIN_TOPAS_THREADS"))

    try:
        proc = subprocess.run(
            [str(exe), basename],
            cwd=str(work),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TopasRunError(
            f"tc.exe がタイムアウトしました ({timeout} 秒): {basename}"
        ) from exc

    stdout = (proc.stdout or "") + (proc.stderr or "")

    # 【二重の網】: 終了コードは信用できない (異常終了でも 0)。
    reason = _failure_reason(stdout)
    if reason is not None:
        raise TopasRunError(f"tc.exe が異常終了しました: {reason}")
    if proc.returncode != 0:
        raise TopasRunError(f"tc.exe が終了コード {proc.returncode} で失敗しました")
    if not out_path.is_file():
        raise TopasRunError(
            f"tc.exe が出力 ({out_path.name}) を生成しませんでした "
            f"(異常終了マーカーは検出されず)。stdout 末尾: {stdout.strip()[-300:]}"
        )

    return TopasRun(
        stdout=stdout,
        out_text=out_path.read_text(encoding="utf-8", errors="replace"),
        results_text=(
            results_path.read_text(encoding="utf-8", errors="replace")
            if results_path.is_file()
            else ""
        ),
        workdir=str(work),
        basename=basename,
    )
