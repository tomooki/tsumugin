"""M9 高温 in situ 逐次 Rietveld の入出力データモデル (frozen dataclass, numpy-only)。

温度/時間系列の各フレームの精密化結果 (`FrameRietveldResult`)、系列全体の結果
(`SequentialRietveldResult`)、系列途中で自動同定・追加された相の記録 (`PhaseAppearance`)、
逐次エンジンの設定 (`SequentialConfig` / `PhaseIdConfig`) を提供する。GSAS-II / MP に非依存の
純データ層 (engine が GSAS を遅延 import で駆動し、この層を組み立てる)。

信頼性: 🔵 architecture.md §2–3。M7 `autorietveld.model` の系列版。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Mapping

from ..autorietveld.absorption import AbsorberLayer
from ..autorietveld.model import CellEsd

if TYPE_CHECKING:
    from ..autorietveld.residual_report import ResidualReport

# 相ごとの格子: (a, b, c, α, β, γ)
Cell = tuple[float, float, float, float, float, float]

#: 相分率系列の基準。``"scale"`` = HAP Scale の正規化値 (相対比較・診断用)、
#: ``"weight"`` = 重量 (質量) 分率 (**定量相分析の出版値**)。
FractionBasis = Literal["scale", "weight"]


class FractionBasisUnavailableError(ValueError):
    """要求した基準の相分率が系列に無いことを示す (**Scale への暗黙フォールバック禁止**)。

    ``fraction_series(basis="weight")`` が重量分率を持たないフレームに当たったときに送出する。
    **黙って Scale を返してはならない**: 呼び出し側は「重量分率を要求して受け取った」と信じた
    まま Scale の数字を出版する — それが Issue #96 レビュー第4巡 HIGH の実害そのものである
    (実測 K₂Mn[Fe(CN)₆]: Scale 由来の midpoint 9.515 h は、同じ fit の wt% では**転移なし**)。

    「転移なし」へ縮退するのも同様に禁止 — 本物の「転移なし」と区別が付かなくなる。

    ② (MCP) はこれを捕捉して ``{"error", "error_type"}`` dict へ縮退すること (③ は LLM なので
    例外は回復不能なハード失敗になる)。
    """


# 【0.0 埋めの意味論】: `fraction_series` は当該相を持たないフレームを 0.0 で埋める。これは
#   「その相は相集合に無い = 寄与 0」という**測定に基づく主張**であり妥当。一方、重量分率 dict
#   そのものが空のフレームは「重量分率を**算出していない**」であって「0 wt%」ではない
#   (`engine._publication_of` と同じ規律)。両者を混同すると測定していない値を出版してしまう。


@dataclass(frozen=True)
class FrameSpec:
    """系列 1 フレームの入力仕様 (観測データ 1 本 + 軸値)。

    :param data_path: 観測データファイル (.xrdml/.fxye/.xye/.gsa 等)
    :param axis_value: フレーム軸値 (温度 K または時間)。None なら index 軸
    :param data_format: GSAS-II importer 種別 ("XRDML"/"FXYE"/"GSAS"/"XYE")
    :param two_theta_limits: このフレームの精密化レンジ (None なら系列既定/全域)
    :param excluded_regions: 使用域内部で除外する 2θ 区間の列 (Issue #53)。寄生線/アーチファクト等を
        事前マスクなしに除外したい場合に用いる (`autorietveld.model.HistogramSpec.excluded_regions`
        と同義)。既定 () (除外なし; 後方互換)。
    :param label: 人間可読ラベル (既定はファイル名)
    :param absorber_layers: 固定吸収体レイヤー (operando セルの電解液層・窓材, Issue #54)。
        `make_gsas_runner` が構築する `HistogramSpec.absorber_layers` へそのまま引き継がれる。
        既定 () (補正なし; 後方互換)。
    """

    data_path: str
    axis_value: float | None = None
    data_format: str = "XRDML"
    two_theta_limits: tuple[float, float] | None = None
    excluded_regions: tuple[tuple[float, float], ...] = ()
    label: str = ""
    absorber_layers: tuple[AbsorberLayer, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "data_path": self.data_path,
            "axis_value": self.axis_value,
            "data_format": self.data_format,
            "two_theta_limits": list(self.two_theta_limits)
            if self.two_theta_limits is not None
            else None,
            "excluded_regions": [list(r) for r in self.excluded_regions]
            if self.excluded_regions
            else [],
            "label": self.label,
            "absorber_layers": [layer.to_dict() for layer in self.absorber_layers],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "FrameSpec":
        limits = d.get("two_theta_limits")
        return cls(
            data_path=str(d["data_path"]),
            axis_value=d.get("axis_value"),  # type: ignore[arg-type]
            data_format=str(d.get("data_format", "XRDML")),
            two_theta_limits=(float(limits[0]), float(limits[1])) if limits is not None else None,
            excluded_regions=tuple(
                (float(r[0]), float(r[1])) for r in (d.get("excluded_regions") or ())
            ),
            label=str(d.get("label", "")),
            absorber_layers=tuple(
                AbsorberLayer.from_dict(x) for x in (d.get("absorber_layers") or ())  # type: ignore[arg-type]
            ),
        )


@dataclass(frozen=True)
class PhaseIdConfig:
    """系列途中の新相自動同定の設定。

    :param elements: 相同定に許す元素系 (既知相の元素 + 想定元素)。空なら同定を行わない
    :param frac_min: 新相の採用に要する最小相分率 (受理基準①)。⚠ **basis は `phase_fractions`
        (= HAP Scale の Σ=1 正規化値) であり `phase_weight_fractions` (wt%) ではない**
        (`engine._accept_new_phase` が `AutoRietveldResult.phase_fractions` と比較する)。
        質量の重い相ほど Scale は wt% より小さく出るため、wt% の直感で決めた下限は
        **同じ精密化で別の答えを出す** (`autorietveld.engine._should_refine_cell` の警告と同型)
    :param rwp_eps: 新相採用に要する最小 Rwp 改善 (受理基準②, %ポイント)
    :param top_k: 各変化点で試す候補相の数 (Dara ランキング上位)
    :param hull_cutoff_ev: MP 安定性フィルタ (energy above hull, eV/atom)
    :param subtract_bg: 残差ピーク抽出前に背景減算 (SNIP) するか
    :param trigger_rwp_ratio: 相同定を試みる Rwp 相対ジャンプ閾値。現フレーム Rwp が
        (系列内最小 Rwp × 本比) を超えたら (変化点発火に加えて) 新相探索を試みる。短系列で変化点窓の
        warm-up 前でも新相出現を捉えるための頑健トリガ (採否は受理基準が担保)。
    :param refine_new_phase_cell: 新相の**異方的**格子を 異方セルプリアラインで補正するか (Issue #20)。
        MP(DFT)構造は格子が軸別にずれ (CaTeO3 delta で c +3.4%)、等方 strain では吸収できず Rietveld
        収束半径外で追えない。True で物質化 CIF を観測へ整合させた異方セルに置換してから精密化に渡す。
    :param wavelength: プリアラインの線源波長 (Å)。既定 Cu Kα1。放射光/中性子系列では実波長を指定。
    :param rerank_top_k: >0 で相同定の上位 K 候補を異方格子整合で再スコアする (Issue #20 hybrid)。
        等方整合が DFT の軸別誤差で正解相を top_k から落とすのを防ぐ。既定 5 (0 で無効)。
    :param min_rwp_gain: 新相受理に要する**相対** Rwp 改善 (0.01=1%)。転移域では旧相単独 fit が
        既に高 Rwp のため絶対差でなく相対改善で判定する。junk 候補は Rwp が下がらず (or 悪化) 弾かれる。
    :param require_validity: 受理に全相の物理妥当性 (`check_validity`) を要求するか。転移域では旧相
        (alpha) のセルが急変して妥当性 fail し**新相 delta を巻き添えで弾く**ため既定 False。代わりに
        新相セルの健全性 (軸長 >1Å = 非崩壊) のみを必須ガードにする (③ 受理閾値, 実データで確認)。
    :param require_full_element_system: 新相候補を**全元素系 (elements すべてを含む) 相**に限定するか
        (③ 化学ガード)。相転移は骨格元素を保存するため、元素部分集合の単純相 (元素 Ca・O₂・CaO 等) が
        少数相パターンに偶然マッチし上位化するのを防ぐ (実測: Ca-Te-O 三元限定で delta が frame90 #33→#1)。
        既定 True。副生成物 (二元分解相等) を許すなら False。
    :param snr_trigger: 残差 S/N トリガの閾値 (2相目追加判定)。既存相 fit の残差に、計数統計ノイズを
        超える未説明ピーク (S/N ≥ 本値) があれば新相探索を発火する。恣意的な Rwp 比でなくノイズ基準で
        「本物の未説明反射」を検出する (F 検定同型)。既定 20.0 (0 で無効)。**注意: この閾値は既知相の
        モデル品質に依存しデータセット固有** — 実測 CaTeO3 で純 alpha (新相なし) の残差でも profile/選択
        配向/水素の未モデル分で ~17σ のピークが出るため、8 では常時発火する。純 alpha 17σ vs delta 萌芽
        35σ の間の 20 に校正。理想的には well-fit 基準フレームの残差 S/N 比 or エージェント/人間が設定する
        (3 層の判断層)。GSAS 残差が無い runner (テストスタブ等) では無効化される。
    :param max_new_phases: 系列全体で追加する新相数の上限 (0 で無制限)。**通常は不要** — S/N トリガの
        moved 抑制 (空振り後は残差が動くまで再探索しない) が無駄試行を自己抑制するため。想定相数が厳密に
        既知で、かつ探索を確実に打ち切りたい場合のみのオプション escape hatch。
    :param bic_acceptance: 単一フレームの新相受理を **bic モデル選択** で判定するか (**既定 False**)。
        `bic = gof²·(n_obs−n_params) + n_params·ln(n_obs)`, n_params = base + per_phase·相数、trial_bic <
        base_bic で採用。**ベンチマーク結論 (Issue #23 層1)**: 粉末パターンは n_obs~数千と大きく、相追加の
        パラメータ罰 (~91) が chi2 改善スケール (~数百〜千) に対し微小なため、bic は forward-pass では
        `min_rwp_gain` より**寛容**で偽相 (大分率で Rwp を下げる Ca3TeO6 等) も採ってしまい過剰適合ガードに
        ならない。よって forward-pass は既定で相対 Rwp を用いる。bic の実効は**相集合が違う区間比較**
        (M10 anchor crossover, パラメータ罰がフレーム跨ぎで累積) にあり、そこでは既定 on。小 n_obs や
        原理的判定が要る時のみ本フラグを True。frac/セル/妥当性ガードは両方式で共通。
    :param bic_base_params: bic の非相パラメータ数 (背景/プロファイル/ゼロ等)。
    :param bic_per_phase_params: bic の 1 相あたりパラメータ数 (scale+格子+プロファイル概算)。
    :param warm_start_known_phases: 新相探索で現行相集合を `identify_pattern(known_phases=)` に渡し
        **先に残差から減算**してから新相を探すか (operando 一本化 B)。現行相を精密化格子付き
        `ReferencePhase` に変換 (`phasespec_to_reference`) して finder へ渡す。CIF 素の (DFT/物質化時)
        格子でなく現フレームの精密化格子で減算するため残差がクリーンになり、少数新相の検出感度が上がる
        (M11 の「減算前ピーク整合」の operando 版)。変換不能 (pymatgen 不在 / CIF 読込失敗 / スタブ
        finder の擬似パス) は空集合へ縮退し、静的同定 (identify-all-then-exclude) に安全フォールバック
        する。既定 True。カスタム finder はこの引数を無視してよい (後方互換の既定 ())。
    """

    elements: tuple[str, ...] = ()
    frac_min: float = 0.02
    rwp_eps: float = 1e-6
    top_k: int = 1
    hull_cutoff_ev: float | None = 0.1
    subtract_bg: bool = True
    trigger_rwp_ratio: float = 1.25
    refine_new_phase_cell: bool = True
    wavelength: float = 1.5406
    rerank_top_k: int = 5
    min_rwp_gain: float = 0.01
    require_validity: bool = False
    require_full_element_system: bool = True
    snr_trigger: float = 20.0
    max_new_phases: int = 0
    bic_acceptance: bool = False
    bic_base_params: int = 30
    bic_per_phase_params: int = 12
    warm_start_known_phases: bool = True

    @property
    def enabled(self) -> bool:
        return bool(self.elements)


@dataclass(frozen=True)
class SequentialConfig:
    """逐次精密化エンジンの設定。

    :param warm_start: 直前フレームの精密化格子を次フレームの初期格子に引き継ぐか
    :param two_theta_limits: 全フレーム共通の精密化レンジ (フレーム個別指定が優先)
    :param max_frames: 先頭から解析するフレーム上限 (None なら全部, デバッグ/検証短縮用)
    :param changepoint_window: 変化点検出のローリング窓 (sequential.changepoint と整合)
    :param phase_id: 新相自動同定設定 (None/無効なら相追加しない)
    :param backward_propagation: 新相の**globally-best セルで全フレームを再精密化**し onset を逆伝播で
        捕捉するか (operando セル整合)。転移域では少数相のうちは prealign がセルを誤整合し (支配相のピークに
        ロック)、誤セルを warm-start 前進させると Rwp 高止まり→偽相を誘発する (実測)。prealign が正しい
        セルを返すのは相が支配的なフレームのみ。そこで支配フレームで確立した良いセルで (1) P を含む全
        フレームを再 fit (onset 域の誤セル poison 除去) + (2) 前フレームへ逆伝播して onset を捕捉する。既定 True。
    :param warm_start_fractions: 直前フレームの精密化相分率 (HAP Scale) も次フレームの初期値に引き継ぐか
        (Issue #82 再スコープ)。``warm_start`` は格子のみを引き継ぎ、相分率は毎フレーム既定 HAP Scale
        から再出発するため、実測で 2 相 (cubic+tetragonal) ドーム域の一部フレームが未着手の seed 値
        (0.50) に張り付き、分率 warm-start ありの系列は同域で滑らかに追従した (0.50→0.69)。**既定 False**
        (非回帰)。True でも ``warm_start=False`` なら効果なし (格子と同じ warm_start ゲートに従う)。
        **核形成安全弁**: 相集合が変化した直後の 1 フレームは分率を引き継がない (fresh) — 分率
        warm-start は 0 分率の新相を核形成できないため、新規追加相にはウォームスタートなしの
        1 回の精密化機会を与える。runner が 4 番目の引数 (``initial_fractions`` キーワード) を
        受け付ける場合のみ実際に渡される (``Runner`` 3 引数プロトコルは非破壊; `make_gsas_runner` は
        対応済み、カスタム/テスト用 3 引数 runner は従来通り無視される)。
    """

    warm_start: bool = True
    two_theta_limits: tuple[float, float] | None = None
    max_frames: int | None = None
    changepoint_window: int = 5
    phase_id: PhaseIdConfig | None = None
    backward_propagation: bool = True
    warm_start_fractions: bool = False


@dataclass(frozen=True)
class FrameRietveldResult:
    """系列 1 フレームの精密化結果。

    :param frame_index: 0 始まりのフレーム番号
    :param axis_value: フレーム軸値 (温度/時間, None 可)
    :param data_path: 観測データファイル
    :param rwp: 最終 Rwp (%)。失敗フレームは inf
    :param gof: 最終 GOF。失敗フレームは inf
    :param refined_cells: 相名→精密化格子 (a,b,c,α,β,γ)
    :param phase_fractions: 相名→相分率 (単相は {name: 1.0})
    :param phase_names: このフレームで有効な相名 (安定順)
    :param changepoint: 変化点として発火したフレームか
    :param changepoint_reasons: 発火した指標名 (rwp_jump/lattice_jump/new_peaks)
    :param validity_passed: 物理妥当性ゲート合格か
    :param refine_failed: 精密化が失敗 (inf 変換) したフレームか
    :param n_obs: 精密化に使った観測点数 (bic 算出用, M10)。既定 0 で後方互換 (bic 未使用時は不要)
    :param residual_report: このフレームの残差分解 (`autorietveld.residual_report` の
        `ResidualReport`)。None なら残差が復元不能 (runner が残差配列を返していない/スタブ)。

        **配列でなく報告を持つ**理由 (docs/design/operando-diagnosis/architecture.md §4.5):
        残差配列 (`AutoRietveldResult.residual_two_theta`/`_intensity`/`_sigma`) は実データで
        2392 点 × 3 本 ≈ 150KB/フレームあり、247 フレーム系列でそのまま保持すると ~37MB になる。
        一方レポートは数個の float + ~6 特徴と小さい。エンジンがフレーム構築時に
        `residual_report_from_result` で畳んで持たせることで、系列結果の消費側 (③ の J2/J3:
        未説明ピーク → 欠落相 / 強度比異常 → 対称性低下) が**再精密化なしに**残差を判断できる。
        既定 None で後方互換 (既存の 3 引数スタブ runner は残差を持たない)。
    :param phase_weight_fractions: 相名→**重量 (質量) 分率** (`AutoRietveldResult.phase_weight_fractions`
        由来, GSAS-II `calcMassFracs`)。**定量相分析の出版値はこちら** — `phase_fractions` は Scale 正規化
        値で単位胞質量が相間で異なると重量分率と乖離する。乖離は**フレーム毎に違う** (実測
        K₂Mn[Fe(CN)₆] tetra: 65.6 Scale% が 47.2 wt% [1.39 倍]、系列全体で 1.39-1.62 倍)。
        大きさは単位胞質量比 (cubic 1103.4 / tetra 517.8 amu = 2.13 倍) と分率で決まるので
        **単一の換算係数は無い** — Scale に係数を掛けて wt% にはできない。
        既定空 dict で後方互換 (重量分率を持たない runner/スタブ・失敗フレームは空)。
    :param phase_weight_fraction_esd: 相名→重量分率の esd (`AutoRietveldResult.phase_weight_fraction_esd`
        由来)。出版には esd 必須。要素 ``None`` = **多相なのにこの精密化から決まっていない** (相 Scale が
        最終共分散に無い; レビュー第6巡)・単相は ``0.0`` (自明)。既定空 dict で後方互換。
    :param cell_esd: 相名→格子 esd (a,b,c,α,β,γ; `refined_cells` と同一レイアウト,
        `AutoRietveldResult.cell_esd` 由来)。要素 ``None`` = **そのフレームで格子を解放していない**
        (凍結セル/未精密化) ので値が決まっていない。``0.0`` は対称拘束で厳密に固定 (真の陳述)。
        相ごと欠落 = 抽出できなかった。既定空 dict で後方互換。
    """

    frame_index: int
    axis_value: float | None
    data_path: str
    rwp: float
    gof: float
    refined_cells: Mapping[str, Cell]
    phase_fractions: Mapping[str, float]
    phase_names: tuple[str, ...]
    changepoint: bool = False
    changepoint_reasons: tuple[str, ...] = ()
    validity_passed: bool = True
    refine_failed: bool = False
    n_obs: int = 0
    residual_report: "ResidualReport | None" = None
    phase_weight_fractions: Mapping[str, float] = field(default_factory=dict)
    phase_weight_fraction_esd: Mapping[str, float | None] = field(default_factory=dict)
    cell_esd: Mapping[str, CellEsd] = field(default_factory=dict)


@dataclass(frozen=True)
class PhaseAppearance:
    """系列途中で自動同定・採用された新相の記録。

    :param phase_name: 相名
    :param frame_index: 初めて採用されたフレーム
    :param axis_value: そのフレームの軸値
    :param structure_path: 物質化した構造ファイル (CIF) パス
    :param source: 供給元 ("materials_project"/"user_cif"/...)
    :param rwp_before: 相追加前の Rwp
    :param rwp_after: 相追加後の Rwp
    :param evidence: 同定根拠 (dara_score・未指数説明数など)
    """

    phase_name: str
    frame_index: int
    axis_value: float | None
    structure_path: str
    source: str
    rwp_before: float
    rwp_after: float
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SequentialRietveldResult:
    """温度/時間系列の逐次自動 Rietveld の総合結果。

    :param frames: フレーム別結果 (フレーム順)
    :param appearances: 自動同定で採用された新相の記録 (採用順)
    :param phase_names: 系列で観測された全相名の和 (安定順)
    :param warnings: 非致命の警告
    :param ledger: 追記された台帳 (None なら未使用)
    """

    frames: tuple[FrameRietveldResult, ...]
    appearances: tuple[PhaseAppearance, ...] = ()
    phase_names: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    ledger: object | None = None

    def axis_values(self) -> tuple[float | None, ...]:
        """全フレームの軸値。"""
        return tuple(f.axis_value for f in self.frames)

    def cell_series(self, phase: str, component: str = "a") -> tuple[tuple[float, ...], tuple[float, ...]]:
        """相 phase の格子成分 (a/b/c/alpha/beta/gamma) の (軸値, 値) 系列を返す。

        当該相が存在し軸値が数値のフレームのみ (欠測フレームは除外)。decreasing でも順序保持。
        """
        idx = {"a": 0, "b": 1, "c": 2, "alpha": 3, "beta": 4, "gamma": 5}[component]
        axes: list[float] = []
        vals: list[float] = []
        for f in self.frames:
            cell = f.refined_cells.get(phase)
            if cell is None or f.axis_value is None or f.refine_failed:
                continue
            axes.append(float(f.axis_value))
            vals.append(float(cell[idx]))
        return tuple(axes), tuple(vals)

    def fraction_series(
        self, phase: str, *, basis: FractionBasis = "scale"
    ) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """相 phase の相分率の (軸値, 分率) 系列を返す (相集合に無いフレームは 0.0)。

        :param basis: ``"scale"`` (既定) = HAP Scale の正規化値。``"weight"`` = 重量分率
            (**定量相分析の出版値**)。

        ⚠ **basis は「相対比較か出版か」以上の意味を持つ**: この系列の主な消費者
        ``parametric.transition_from_fractions`` → ``sequential.thermal.estimate_transition`` は
        **絶対レベル 0.50 / 0.10 の交差軸値**を報告する。y 軸を Scale から wt% に替えると
        **答えそのものが動く** (実測 K₂Mn[Fe(CN)₆] tetra: Scale 0→0.656 は 0.50 を横切り
        midpoint 9.515 h を出すが、同じ fit の wt% は 0→0.472 で横切らず**転移なし**。
        Scale=0.50 の点は実際には 34.0 wt% であって「半分」ではない)。

        **既定が ``"scale"`` なのは後方互換のため**であり「Scale が転移推定に妥当だから」では
        ない。転移温度・相分率など**報告する数値は ``basis="weight"``** で取ること。

        :raises FractionBasisUnavailableError: ``basis="weight"`` だが重量分率を持たない
            フレームがあるとき。**Scale へは縮退しない** (静かに違う数字を出版させない)。
            欠測フレームを黙って落とすこともしない — 交差の線形補間が別の隣接対で行われ
            midpoint が動くため。
        :raises ValueError: 未知の basis。
        """
        if basis not in ("scale", "weight"):
            raise ValueError(f"unknown basis: {basis!r} (expected 'scale' or 'weight')")

        # 【欠測の先行検出】: 系列を組み立てる前に「重量分率を算出していない」フレームを洗い出す。
        #   `phase_weight_fractions` が空 = 未算出 (スタブ runner / 非 GSAS 経路 / 共分散なし) で
        #   あって「0 wt%」ではない。dict が非空なら当該相の欠落は「相集合に無い」= 0.0 が妥当。
        if basis == "weight":
            missing = [
                f.frame_index
                for f in self.frames
                if f.axis_value is not None and not f.refine_failed and not f.phase_weight_fractions
            ]
            if missing:
                raise FractionBasisUnavailableError(
                    f"phase_weight_fractions が無いフレームがあります: {missing} — "
                    "重量分率を報告できません (Scale へは縮退しません: 静かに違う数字になります)。"
                    "診断目的の相対比較なら basis='scale' を明示してください "
                    "(その値は出版できません)"
                )

        axes: list[float] = []
        vals: list[float] = []
        for f in self.frames:
            if f.axis_value is None or f.refine_failed:
                continue
            source = f.phase_fractions if basis == "scale" else f.phase_weight_fractions
            axes.append(float(f.axis_value))
            vals.append(float(source.get(phase, 0.0)))
        return tuple(axes), tuple(vals)
