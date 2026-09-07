"""M8 Agentic 閉ループ: 次手を表す AnalysisAction 群 (安全/非安全を型で区別)。

各 Action は解析入力 (`AnalysisInput`: ヒストグラム/相/背景係数/追加段階) を純粋に変換する
`apply` を持つ。**規則が実行してよい `SafeAction`** (背景増項・パラメータ追加解放・停止) と、
**③ (Claude/人間) 専用の `ModelAction`** (リミット・相追加削除・構造改訂・混合占有割当) を基底で
型分けする (architecture.md §3.1, §4)。GSAS 非依存の純データ層のため単体テスト可能。

信頼性: 🔵 architecture.md §3.1 の Action 表と 1:1。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Mapping

from tsumugin.autorietveld import HistogramSpec, PhaseSpec, RefinementStage


@dataclass(frozen=True)
class AnalysisInput:
    """Action が変換する解析入力の不変コンテナ。

    :param histograms: 観測ヒストグラム仕様
    :param phases: 相仕様
    :param background_coeffs: 背景 (Chebyshev) 係数数 (build_recipe へ渡す)
    :param extra_stages: recipe 末尾に追加する解放段階 (ReleaseParams が累積)
    """

    histograms: tuple[HistogramSpec, ...]
    phases: tuple[PhaseSpec, ...]
    background_coeffs: int = 6
    extra_stages: tuple[RefinementStage, ...] = ()


@dataclass(frozen=True)
class AnalysisAction:
    """次手の基底。`apply(inp) -> inp` の純変換と `is_safe` を持つ。"""

    @property
    def is_safe(self) -> bool:
        """規則ポリシーが実行してよい安全手か。"""
        return isinstance(self, SafeAction)

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        """解析入力を純粋に変換して返す (基底は恒等)。"""
        return inp


@dataclass(frozen=True)
class SafeAction(AnalysisAction):
    """規則が実行可能・自己検証可・パラメトリックな手 (§4.1)。"""


@dataclass(frozen=True)
class ModelAction(AnalysisAction):
    """③ (Claude/人間) 専用の構造/相/事前知識に踏み込む手 (§4.2)。規則は提案のみ。"""


# ---------------- SafeAction ----------------


@dataclass(frozen=True)
class AdjustBackground(SafeAction):
    """背景係数を段階的に増項する (3→6→9…)。背景はプロジェクト全域 (build_recipe 準拠)。

    :param n_coeffs: 設定する背景係数数
    """

    n_coeffs: int

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        return dataclasses.replace(inp, background_coeffs=self.n_coeffs)


@dataclass(frozen=True)
class ReleaseParams(SafeAction):
    """recipe の次段階を追加解放する (停滞打破)。

    :param label: 追加段階のラベル
    :param flags: RefinementStage の解放フラグ (recipe 語彙準拠)
    """

    label: str
    flags: Mapping[str, object]

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        stage = RefinementStage(label=self.label, flags=dict(self.flags), note="ReleaseParams")
        return dataclasses.replace(inp, extra_stages=(*inp.extra_stages, stage))


@dataclass(frozen=True)
class Stop(SafeAction):
    """ループ停止 (目標到達/停滞/上限)。apply は恒等。

    :param reason: 停止理由
    """

    reason: str


@dataclass(frozen=True)
class RestrictUiso(SafeAction):
    """Uiso 解放対象を限定する (発散防止, REQ-105)。free_uiso_labels を設定する純変換。

    軽元素 framework や占有率 0 のゴースト原子の Uiso が発散/負値化するのを、重原子/可動イオン/
    水など安定な原子のみに Uiso 解放を絞ることで防ぐ (heavy-atom + 無秩序構造の定石)。

    :param labels: Uiso を解放してよい原子ラベル (これ以外は Uiso 固定)。**空タプルは
        「1 原子も解放しない」** = 相ごと ADP 凍結 (#189 の型分離により docstring どおりになった。
        以前は空を渡すと逆に全原子が解放されていた)
    :param phase: 対象相名 (None なら全相)
    """

    labels: tuple[str, ...]
    phase: str | None = None

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        phases = tuple(
            dataclasses.replace(p, free_uiso_labels=tuple(self.labels))
            if (self.phase is None or p.phase_name == self.phase)
            else p
            for p in inp.phases
        )
        return dataclasses.replace(inp, phases=phases)


@dataclass(frozen=True)
class SetAbsorption(SafeAction):
    """ヒストグラムの吸収を値固定 or 解放する (free/物理/0 の三択トライ, REQ-106)。

    弱吸収試料は吸収の自由精密化が負に振れやすい。物理値固定・0・自由精密化を別々に試し
    妥当性+Rwp で採否する (try→revert)。

    :param hist_id: 対象ヒストグラム索引 (0 始まり)
    :param value: 設定する吸収初期値 (物理値/0 等)
    :param refine: True なら "absorption" 解放段を extra_stages に追加、False なら固定
    """

    hist_id: int
    value: float = 0.0
    refine: bool = False

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        if not (0 <= self.hist_id < len(inp.histograms)):
            raise IndexError(f"hist_id={self.hist_id} が範囲外 (n={len(inp.histograms)})")
        hists = list(inp.histograms)
        hists[self.hist_id] = dataclasses.replace(hists[self.hist_id], absorption=self.value)
        extra = inp.extra_stages
        if self.refine:
            extra = (*extra, RefinementStage("abs", {"absorption": True}, note="SetAbsorption"))
        return dataclasses.replace(inp, histograms=tuple(hists), extra_stages=extra)


# ---------------- ModelAction ----------------


@dataclass(frozen=True)
class SetLimits(ModelAction):
    """ヒストグラムのデータ範囲を制限する (③/人間の判断)。

    ``low``/``high`` が ``None`` は「切り位置未定のプレースホルダ提案」(診断が出す候補)。
    実適用には ③ が具体値を入れる。プレースホルダのまま apply すると ValueError。

    :param hist_id: 対象ヒストグラム索引 (0 始まり)
    :param low: 下限 (2θ / TOF)。未定は None
    :param high: 上限。未定は None
    """

    hist_id: int
    low: float | None = None
    high: float | None = None

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        if not (0 <= self.hist_id < len(inp.histograms)):
            raise IndexError(f"hist_id={self.hist_id} が範囲外 (n={len(inp.histograms)})")
        if self.low is None or self.high is None:
            raise ValueError(
                "プレースホルダ SetLimits (low/high=None) は適用不能: ③ が切り位置を決めてから適用する"
            )
        hists = list(inp.histograms)
        hists[self.hist_id] = dataclasses.replace(
            hists[self.hist_id], two_theta_limits=(self.low, self.high)
        )
        return dataclasses.replace(inp, histograms=tuple(hists))


@dataclass(frozen=True)
class AddPhase(ModelAction):
    """未指数ピークに相を追加する。`spec` があれば適用可、`element_hint` のみは相同定要 (③)。

    :param spec: 追加する相 (③ が相同定して構築済み)
    :param element_hint: 元素ヒントのみ (適用不能。相同定への申し送り情報)
    """

    spec: PhaseSpec | None = None
    element_hint: tuple[str, ...] = ()

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        if self.spec is None:
            raise ValueError(
                "element_hint のみの AddPhase は適用不能: ③ が相同定して spec 化してから適用する"
            )
        return dataclasses.replace(inp, phases=(*inp.phases, self.spec))


@dataclass(frozen=True)
class RemovePhase(ModelAction):
    """寄与ゼロの相を除去する (③/人間の判断)。

    :param name: 除去する相名
    """

    name: str

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        if not any(p.phase_name == self.name for p in inp.phases):
            raise KeyError(f"相 {self.name!r} が存在しません")
        phases = tuple(p for p in inp.phases if p.phase_name != self.name)
        return dataclasses.replace(inp, phases=phases)


# PhaseSpec 上で改訂可能なフィールド (構造改訂は ③ が編集済みファイルを与える形で純変換化)
_REVISABLE_PHASE_FIELDS = frozenset(
    {"structure_path", "phase_name", "format_hint", "mixed_occupancy_groups", "temperature"}
)


@dataclass(frozen=True)
class ReviseStructure(ModelAction):
    """相の構造を改訂する (空間群/座標/占有 — 開放的な結晶学判断, ③ 専用)。

    edits は PhaseSpec のフィールド更新として表現する (例: ③ が編集した CIF の
    ``structure_path`` 差し替え)。原子レベルの編集はファイル側で行い、ここでは spec を差し替える。

    :param phase: 対象相名
    :param edits: PhaseSpec フィールドの更新辞書
    """

    phase: str
    edits: Mapping[str, object]

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        bad = set(self.edits) - _REVISABLE_PHASE_FIELDS
        if bad:
            raise ValueError(f"改訂不能なフィールド: {sorted(bad)}")
        if not any(p.phase_name == self.phase for p in inp.phases):
            raise KeyError(f"相 {self.phase!r} が存在しません")
        phases = tuple(
            dataclasses.replace(p, **dict(self.edits)) if p.phase_name == self.phase else p
            for p in inp.phases
        )
        return dataclasses.replace(inp, phases=phases)


@dataclass(frozen=True)
class SetMixedOccupancy(ModelAction):
    """混合占有サイトを指定する (サイト化学の割当 — 残差非依存, ③ 専用)。

    :param phase: 対象相名
    :param groups: 占有率和=1 を張る原子ラベル組の列
    """

    phase: str
    groups: tuple[tuple[str, ...], ...] = ()

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        if not any(p.phase_name == self.phase for p in inp.phases):
            raise KeyError(f"相 {self.phase!r} が存在しません")
        phases = tuple(
            dataclasses.replace(p, mixed_occupancy_groups=self.groups)
            if p.phase_name == self.phase
            else p
            for p in inp.phases
        )
        return dataclasses.replace(inp, phases=phases)
