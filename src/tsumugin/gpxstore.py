"""精密化成果物 (.gpx / TOPAS プロジェクト) の保存先解決・命名・索引 (stdlib-only leaf)。

**規定 (2026-08-20)**: **全解析で成果物を保存する**。単発の `run_auto_rietveld` だけでなく、
系列解析 (`insitu` 逐次 / `insitu.anchor` 双方向)・棄却された相追加トライアル・マルチスタートの
各開始点・レシピ探索の各候補・モデル比較の各バリアントまで、**実際に GSAS/TOPAS を回した単位
ごとに 1 つ**残す。理由は「保存しなかった精密化は検算できない」— Rwp と ledger だけでは
無言失敗 (段が no-op) も相分率 ~0 の棄却理由も追えず、MEM (`mem_density`) や
`mem_rietveld_iterate` は精密化済み gpx そのものを入力に要求する。

置き場所の既定は**観測データ隣接** ``<data_dir>/tsumugin_gpx/<run_id>/``。上書きは環境変数
``TSUMUGIN_GPX_DIR`` (``none`` で保存無効化)、さらに強い上書きは呼び出し側の明示指定
(``gpx_dir`` 引数)。**明示指定は env の ``none`` にも勝つ** — 頼まれた保存を環境変数で黙って
捨てない。

本モジュールは**置き場所と名前だけ**を決める。精密化の物理には一切影響しない
(NFR-102: 保存先が変わっても結果はビット同一)。文脈 (`GpxContext`) は成果物に人が読める名前を
付けるためだけの側路であり、無くても保存は行われる (名前がデータ名になるだけ)。
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import math
import os
import re
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field

#: 保存先の根を上書きする環境変数。``none`` (大文字小文字問わず) で保存を無効化する。
ENV_VAR = "TSUMUGIN_GPX_DIR"

#: ``TSUMUGIN_GPX_DIR`` に与えると保存を無効化する値 (`topas.availability` の ``=none`` と同流儀)。
DISABLED = "none"

#: データ隣接に作るディレクトリ名。
DEFAULT_DIR_NAME = "tsumugin_gpx"

#: 索引ファイル名 (JSON Lines・追記専用)。
MANIFEST_NAME = "manifest.jsonl"

#: ラベルの最大長 (Windows の 260 文字パス制限に対する余裕を残す)。
MAX_LABEL = 60

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_label(text: str) -> str:
    """任意の文字列 (相名/候補名/区間名) をパス安全なファイル名断片へ畳む。

    相名は CIF/Materials Project 由来で ``/`` や空白を含みうる。パス区切りを含む文字列で
    ファイル名を組むと**別ディレクトリへ書く**ため、英数と ``._-`` 以外は ``-`` に潰す。
    空になったら ``unnamed`` (名無しのファイルを作らない)。
    """
    cleaned = _UNSAFE.sub("-", str(text)).strip("-.")
    if not cleaned:
        return "unnamed"
    return cleaned[:MAX_LABEL]


@dataclass(frozen=True)
class GpxContext:
    """成果物の**置き場所と名前**だけを運ぶ文脈 (物理には影響しない)。

    :param run_dir: 解決済みの run ディレクトリ。空文字なら `plan_artifact` 時に解決する
    :param role: 役割 (``single``/``frame``/``trial``/``forward``/``backward``/``anchor``/
        ``multistart``/``candidate``/``model``)。ファイル名に出る
    :param index: フレーム番号や開始点番号 (ファイル名の ``f0180`` 部)
    :param label: 候補相名・区間名・レシピ名など (ファイル名の末尾)
    :param enabled: False なら保存しない (opt-out)
    """

    run_dir: str = ""
    role: str = "single"
    index: int | None = None
    label: str = ""
    enabled: bool = True

    def child(self, *, role: str, index: int | None = None, label: str = "") -> "GpxContext":
        """同じ run ディレクトリで役割/番号/ラベルだけ差し替えた文脈を返す (非破壊)。"""
        return GpxContext(
            run_dir=self.run_dir, role=role, index=index, label=label, enabled=self.enabled
        )

    def stem(self, *, data_stem: str) -> str:
        """この文脈での成果物ファイル名 (拡張子なし) を返す。

        役割が既定 (``single``) かつ番号もラベルも無いときだけデータ名を使う — 単発解析で
        ``f0000_single.gpx`` のような無情報な名前にしないため。
        """
        parts: list[str] = []
        if self.index is not None:
            parts.append(f"f{int(self.index):04d}")
        if self.role and self.role != "single":
            parts.append(sanitize_label(self.role))
        if self.label:
            parts.append(sanitize_label(self.label))
        if not parts:
            return sanitize_label(data_stem)
        return "_".join(parts)


@dataclass(frozen=True)
class ArtifactPlan:
    """1 成果物の保存計画。

    :param path: 保存先パス。**None は「保存しない」** (無効化されている)
    :param run_dir: 属する run ディレクトリ (保存しないときは "")
    :param fallback_reason: データ隣接に書けず temp へ退避した理由 (退避していなければ "")
    """

    path: str | None
    run_dir: str
    fallback_reason: str = ""


@dataclass(frozen=True)
class ManifestEntry:
    """索引 1 行 (= 成果物 1 つ)。

    「全部保存する」は「後から**探せる**」までが要件なので、ファイル名だけでなく
    どのデータ・どの相集合・どの適合度の精密化かを 1 行で残す。
    """

    path: str
    role: str
    label: str
    index: int | None
    data_paths: tuple[str, ...]
    phases: tuple[str, ...]
    rwp: float | None
    gof: float | None
    backend: str = "gsasii"
    extra: Mapping[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        """JSON Lines 1 行分の dict (非有限値は null へ; ``allow_nan=False`` 安全)。"""
        out: dict[str, object] = {
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "path": self.path,
            "role": self.role,
            "label": self.label,
            "index": self.index,
            "data_paths": list(self.data_paths),
            "phases": list(self.phases),
            "rwp": _finite(self.rwp),
            "gof": _finite(self.gof),
            "backend": self.backend,
        }
        out.update(dict(self.extra))
        return out


def _finite(value: float | None) -> float | None:
    """有限な float だけを通す (inf/NaN は null)。"""
    if value is None:
        return None
    v = float(value)
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------------------
# 保存先の解決
# ---------------------------------------------------------------------------


def _root_dir(data_path: str, explicit_dir: str | None) -> str | None:
    """成果物の根ディレクトリを決める。None = 保存無効。"""
    if explicit_dir:
        return os.path.abspath(explicit_dir)
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        if env.lower() == DISABLED:
            return None
        return os.path.abspath(env)
    parent = os.path.dirname(os.path.abspath(str(data_path))) or os.getcwd()
    return os.path.join(parent, DEFAULT_DIR_NAME)


def resolve_run_dir(
    data_path: str,
    *,
    explicit_dir: str | None = None,
    run_id: str | None = None,
    now: str | None = None,
    report_fallback: bool = False,
):
    """1 回の解析 (系列なら系列全体) の run ディレクトリを作って返す。

    :param data_path: 観測データのパス (既定の根をこの隣に作る)
    :param explicit_dir: 呼び出し側の明示指定 (env より強い)
    :param run_id: run ディレクトリ名の明示指定 (既定は ``run-<日時>``)
    :param now: 日時文字列の注入 (テスト用)
    :param report_fallback: True なら ``(run_dir, 退避理由)`` のタプルを返す
    :returns: run ディレクトリのパス。**None は保存無効** (``TSUMUGIN_GPX_DIR=none``)
    """
    root = _root_dir(data_path, explicit_dir)
    if root is None:
        return (None, "") if report_fallback else None

    stamp = now or time.strftime("%Y%m%d-%H%M%S")
    base = run_id or f"run-{stamp}"
    reason = ""
    try:
        path = _make_unique_dir(root, base)
    except OSError as exc:
        # 【黙って諦めない】: データが読み取り専用の共有ディスクにあるだけで 750 フレームの
        #   系列を落とすのは受け入れられない。一方「規定で保存する」と言った以上、保存しない
        #   のも裏切りなので temp へ退避し、理由を呼び出し側 (ledger/警告) へ返す。
        reason = f"{type(exc).__name__}: {exc} ({root} へ書けないため一時領域へ退避)"
        path = tempfile.mkdtemp(prefix="tsumugin-gpx-")
    return (path, reason) if report_fallback else path


def _make_unique_dir(root: str, base: str) -> str:
    """``<root>/<base>`` を作る。既にあれば ``-2``, ``-3`` … と衝突を避ける (P2: 上書きしない)。"""
    for n in range(1, 1000):
        name = base if n == 1 else f"{base}-{n}"
        path = os.path.join(root, name)
        try:
            os.makedirs(path, exist_ok=False)
            return path
        except FileExistsError:
            continue
    raise OSError(f"run ディレクトリ名が枯渇しました: {root}/{base}")


def _unique_file(run_dir: str, stem: str, ext: str) -> str:
    """``<run_dir>/<stem><ext>`` を返す。既存なら ``-2``… (P2: 保存済み成果物を消さない)。"""
    for n in range(1, 1000):
        name = f"{stem}{ext}" if n == 1 else f"{stem}-{n}{ext}"
        path = os.path.join(run_dir, name)
        if not os.path.exists(path):
            return path
    raise OSError(f"成果物名が枯渇しました: {run_dir}/{stem}{ext}")


def plan_artifact(
    data_paths: Sequence[str],
    context: GpxContext | None,
    *,
    ext: str = ".gpx",
    explicit_dir: str | None = None,
    now: str | None = None,
) -> ArtifactPlan:
    """成果物 1 つの保存先を決める (ディレクトリは作るがファイルは作らない)。

    :param data_paths: 観測データのパス列 (先頭が既定の置き場所とファイル名の元になる)
    :param context: 文脈。None なら ambient (`gpx_context`) を見て、それも無ければ既定で
        新しい run ディレクトリを作る
    :param ext: 拡張子。TOPAS のプロジェクト**ディレクトリ**は ``""``
    :param explicit_dir: 呼び出し側の明示 run 根 (env より強い)
    :param now: 日時文字列の注入 (テスト用)
    """
    ctx = context if context is not None else active_context()
    if ctx is not None and not ctx.enabled:
        return ArtifactPlan(path=None, run_dir="")

    first = str(data_paths[0]) if data_paths else ""
    reason = ""
    run_dir = ctx.run_dir if (ctx is not None and ctx.run_dir) else ""
    if not run_dir:
        run_dir, reason = resolve_run_dir(
            first, explicit_dir=explicit_dir, now=now, report_fallback=True
        )
        if run_dir is None:
            return ArtifactPlan(path=None, run_dir="")
    else:
        os.makedirs(run_dir, exist_ok=True)

    stem_source = os.path.splitext(os.path.basename(first))[0] if first else "refined"
    ctx = ctx if ctx is not None else GpxContext()
    return ArtifactPlan(
        path=_unique_file(run_dir, ctx.stem(data_stem=stem_source), ext),
        run_dir=run_dir,
        fallback_reason=reason,
    )


def plan_output(
    data_paths: Sequence[str],
    *,
    keep: str | None = None,
    gpx_dir: str | None = None,
    save: bool = True,
    ext: str = ".gpx",
    context: GpxContext | None = None,
    now: str | None = None,
) -> ArtifactPlan:
    """**両エンジン共通の保存方針** — 明示パス > 無効化 > 既定保存。

    優先順位 (上が強い):

    1. ``save=False`` … 保存しない (呼び出し側の明示 opt-out)
    2. ``keep`` … そのパスへ保存する (既存呼び出しの非回帰。索引は書かない —
       置き場所の取り決めが呼び出し側にあるため ``run_dir`` を名乗らない)
    3. ``gpx_dir`` / ambient 文脈 / ``TSUMUGIN_GPX_DIR`` / データ隣接 … 既定で保存する

    :param data_paths: 観測データのパス列 (先頭が既定の置き場所と名前の元)
    :param keep: 明示パス (``run_auto_rietveld(keep_gpx=)`` / ``run_topas_rietveld(keep_project=)``)
    :param gpx_dir: run ディレクトリの根の明示指定 (env より強い)
    :param save: False で保存無効
    :param ext: ``.gpx`` / TOPAS プロジェクトディレクトリは ``""``
    :param context: 文脈 (None なら ambient を見る)
    """
    if not save:
        return ArtifactPlan(path=None, run_dir="")
    if keep:
        return ArtifactPlan(path=str(keep), run_dir="")
    return plan_artifact(data_paths, context, ext=ext, explicit_dir=gpx_dir, now=now)


def series_context(
    data_path: str, *, gpx_dir: str | None = None, save: bool = True, now: str | None = None
) -> "tuple[GpxContext, str]":
    """**系列解析**が全フレームで共有する文脈を作る (run ディレクトリは 1 つ)。

    フレームごとに run ディレクトリが分かれると 754 個できて探せないので、系列の入口で
    1 度だけ解決する。``save=False`` / ``TSUMUGIN_GPX_DIR=none`` では ``enabled=False`` の
    文脈を返す (None ではなく) — 下流が「保存しない」を一貫して読めるようにするため。

    :returns: ``(文脈, 退避理由)``。退避理由が非空なら呼び出し側が ledger/警告に載せること
    """
    if not save:
        return GpxContext(enabled=False), ""
    run_dir, reason = resolve_run_dir(
        data_path, explicit_dir=gpx_dir, now=now, report_fallback=True
    )
    if run_dir is None:
        return GpxContext(enabled=False), ""
    return GpxContext(run_dir=run_dir), reason


def group_context(
    data_path: str, *, gpx_dir: str | None = None, save: bool = True
) -> "tuple[GpxContext, str]":
    """**1 回の解析の中で N 回精密化する経路** (探索/マルチスタート/モデル比較) の親文脈。

    ambient 文脈が既にあれば**それを使う** (系列の中で探索を回したときに run ディレクトリが
    増殖しないため)。無ければ `series_context` で新しく 1 つ作る。

    :returns: ``(親文脈, 退避理由)``
    """
    current = active_context()
    if current is not None:
        return current, ""
    return series_context(data_path, gpx_dir=gpx_dir, save=save)


# ---------------------------------------------------------------------------
# 索引 (manifest.jsonl) — 追記専用 (P2)
# ---------------------------------------------------------------------------


def record_artifact(run_dir: str, entry: ManifestEntry) -> None:
    """索引に 1 行追記する (追記専用・失敗しても解析は止めない)。

    索引は**便宜**であり真実の源ではない (真実は ledger と結果オブジェクト)。書けなくても
    精密化そのものは成立しているので、ここで例外を飛ばして解析を落とさない。
    """
    if not run_dir:
        return
    try:
        os.makedirs(run_dir, exist_ok=True)
        line = json.dumps(entry.to_json(), ensure_ascii=False, allow_nan=False)
        with open(os.path.join(run_dir, MANIFEST_NAME), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except (OSError, TypeError, ValueError):
        return


def read_manifest(run_dir: str) -> list[dict]:
    """索引を読む (無ければ空リスト・壊れた行は飛ばす)。"""
    path = os.path.join(str(run_dir), MANIFEST_NAME)
    if not os.path.isfile(path):
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


# ---------------------------------------------------------------------------
# ambient 文脈 (命名の側路)
# ---------------------------------------------------------------------------

_ACTIVE: contextvars.ContextVar["GpxContext | None"] = contextvars.ContextVar(
    "tsumugin_gpx_context", default=None
)


def active_context() -> GpxContext | None:
    """現在の ambient 文脈 (無ければ None)。"""
    return _ACTIVE.get()


@contextlib.contextmanager
def gpx_context(context: GpxContext | None) -> Iterator[GpxContext | None]:
    """ambient 文脈を差し替える (``with`` を抜けたら元に戻る)。

    **なぜ側路なのか**: 系列エンジンは ``Runner`` プロトコル (frame, phases, initial_cells[,
    initial_fractions]) で任意の runner を呼ぶ。ここへ「成果物の名前」を渡すために第 5 引数を
    足すと、素の 3 引数 runner が黙って壊れる (FR-318 で同じ罠を避けた経緯: 目標組成は
    ``FrameSpec`` に載せた)。名前は**物理でない**ので入力仕様には載せず、ambient 文脈で運ぶ。
    文脈を読まない runner (テスト用スタブ・カスタム実装) は素通りするだけで壊れない。
    """
    token = _ACTIVE.set(context)
    try:
        yield context
    finally:
        _ACTIVE.reset(token)


def child_context(*, role: str, index: int | None = None, label: str = "") -> GpxContext | None:
    """ambient 文脈から派生した子文脈 (ambient が無ければ None)。"""
    parent = active_context()
    if parent is None:
        return None
    return parent.child(role=role, index=index, label=label)


__all__ = [
    "ArtifactPlan",
    "DEFAULT_DIR_NAME",
    "DISABLED",
    "ENV_VAR",
    "GpxContext",
    "MANIFEST_NAME",
    "ManifestEntry",
    "active_context",
    "child_context",
    "gpx_context",
    "group_context",
    "plan_artifact",
    "plan_output",
    "read_manifest",
    "record_artifact",
    "resolve_run_dir",
    "sanitize_label",
    "series_context",
]
