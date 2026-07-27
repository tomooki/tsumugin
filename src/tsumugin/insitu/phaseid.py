"""M9 相同定→PhaseSpec 物質化ブリッジ (M6 reference の未配線ギャップの解消)。

M6 の `reference.identify_phases` は候補相をランキングするが、`autorietveld` が精密化できる
`PhaseSpec` (CIF パス) への**物質化 (materialization)** が未配線だった (M6 探索で確認)。本モジュールが
それを埋める: 残差/生パターン + 元素ヒントから新相を同定し、上位候補の実構造を CIF に書き出して
`PhaseSpec` を組む。系列途中で出現する新相を自動で精密化対象にするための橋渡し。

3 層:
- **同定 (numpy)**: `reference.identify_phases` を供給元 (既定 MP) で駆動。既知相は `exclude` で除外。
- **物質化 (遅延 pymatgen)**: `PhaseMaterializer` 抽象 — `phase_id` から CIF を書き出す。MP 実装は
  pymatgen `CifWriter`。供給元・物質化器はともに注入可能 (テストはスタブ、本番は MP)。
- **PhaseSpec 生成**: 書き出した CIF パスで `autorietveld.PhaseSpec` を組む。

コアは numpy のみ。pymatgen / mp-api は本モジュールの関数内で遅延 import する。

信頼性: 🔵 architecture.md §4。M6 identify + M7 PhaseSpec を接続する新規配線。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Protocol, Sequence, runtime_checkable

import numpy as np

from ..autorietveld.model import PhaseSpec
from ..reference.iterative import IdentifyConfig, identify_pattern
from ..reference.model import ReferencePhase
from ..reference.provider import ReferenceProvider

# 絶対格子 (a, b, c, α, β, γ)
Cell6 = tuple[float, float, float, float, float, float]
# 物質化 CIF パス → 精密化済み絶対格子 (or None)。異方セル補正の注入点 (Issue #20)。
CellRefiner = Callable[[str], "Cell6 | None"]


@runtime_checkable
class PhaseMaterializer(Protocol):
    """相 ID から精密化可能な構造ファイル (CIF) を物質化する境界。"""

    def materialize(
        self,
        phase_id: str,
        elements: Sequence[str],
        out_path: str,
        strain: float = 0.0,
        cell: Cell6 | None = None,
    ) -> str:
        """相 ID の実構造を out_path (CIF ファイルパス) に書き出しそのパスを返す。取得不能なら例外。

        cell を与えると格子を**その絶対値 (a,b,c,α,β,γ) に置換**して書き出す (異方的な DFT 格子誤差を
        異方セルプリアラインで補正した格子を反映; Issue #20)。cell=None かつ strain!=0 なら格子を等方
        (1+strain) 倍する (M6 align_peaks 由来の等方補正)。cell は strain に優先する。
        """
        ...


@dataclass(frozen=True)
class IdentifiedPhase:
    """同定・物質化された 1 相 (PhaseSpec + 根拠)。"""

    phase_spec: PhaseSpec
    phase_id: str
    formula: str
    score: float
    strain: float
    source: str
    # 異方セルプリアラインで精密化した絶対格子 (異方補正を適用した場合のみ非 None, Issue #20)。
    refined_cell: Cell6 | None = None


def _sanitize(name: str) -> str:
    """相名/ID をファイル名安全な形へ (英数と -_ のみ)。"""
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in name) or "phase"


def structure_to_cif(
    structure: object,
    path: str | Path,
    strain: float = 0.0,
    cell: Cell6 | None = None,
    symprec: float = 0.01,
) -> str:
    """pymatgen ``Structure`` を CIF に書き出す (遅延 import)。書き出し先パスを返す。

    cell を与えると格子を**その絶対値に置換**して書き出す (分率座標は保持; 異方的 DFT 格子誤差を
    異方セルプリアラインで補正した格子を反映)。cell=None かつ strain!=0 なら格子を等方 (1+strain) 倍
    する。cell は strain に優先する。元構造は不変 (copy/新 Structure に適用)。

    **``symprec`` で対称性を検出して書く (P1 展開で書いてはならない)**: ``CifWriter(structure)``
    は symprec 未指定だと空間群を ``P 1`` として全等価原子を書き出す。加えて ``cell`` 置換は
    ``Structure(Lattice…, species, frac_coords)`` で素の Structure を組み直すため、MP 構造が
    持っていた対称性情報がその時点で失われる。**実害 (CaTeO3 delta 実測)**: P1 CIF を読んだ
    GSAS-II は相を三斜晶と解釈しセル 6 変数 (**角度 3 つを含む**) を解放するが、90/90/90 の
    擬直方構造では角度方向の微分がほぼ 0 = 特異ヘッシアンになり ``Refine`` が
    'divide by zero encountered in scalar divide' で失敗する。しかもその失敗は
    ``G2Project.refine`` が ``GSASIIstrMain.Refine`` の戻り値を捨てるため**例外にならず**、
    engine は陳腐化した Covariance を読んで「悪化していない」と判断する → revert もされず
    **以降の全段が無言で何も精密化しないまま完走する** (Rwp には一切現れない)。実測では
    frame180 の二相試行が S2 以降 7 段すべて no-op になり、単相 base (35.32%) に負けて
    delta が棄却されていた。対称化すると同じ段が通り 36.34→33.98% (base 比 +3.78%)。
    座標/Uiso の母数も非対称単位に縮む (delta: 40 原子 → 10 原子)。

    対称性検出に失敗する構造 (結晶系を壊すセル置換等) は P1 で書き出して**物質化自体は
    落とさない** (提案≠適用の安全側; 下がった対称性でも精密化は成立する)。
    """
    from pymatgen.io.cif import CifWriter

    if cell is not None:
        from pymatgen.core import Lattice, Structure

        structure = Structure(
            Lattice.from_parameters(*(float(x) for x in cell)),
            structure.species,  # type: ignore[attr-defined]
            structure.frac_coords,  # type: ignore[attr-defined]
        )
    elif strain:
        structure = structure.copy()  # type: ignore[attr-defined]
        structure.apply_strain(float(strain))  # type: ignore[attr-defined]
    try:
        CifWriter(structure, symprec=float(symprec)).write_file(str(path))
    except Exception:  # noqa: BLE001 — 対称性検出不能は P1 へフォールバック (物質化を落とさない)
        CifWriter(structure).write_file(str(path))
    return str(path)


def phasespec_to_reference(
    phase_spec: PhaseSpec,
    *,
    refined_cell: Cell6 | None = None,
    wavelength: float = 1.5406,
    two_theta_range: tuple[float, float] = (10.0, 90.0),
) -> ReferencePhase | None:
    """現行相 `PhaseSpec` (CIF) を warm-start 用 `ReferencePhase` (ピーク列付) へ変換する (operando 一本化 B)。

    operando の逐次同定で現行相集合を `identify_pattern(known_phases=)` に渡し**先に残差から減算**する
    ため、CIF を pymatgen で読み XRD ピークを生成する (`mp.xrd.simulate_reference_peaks`)。`refined_cell`
    を与えると格子をその**精密化格子**へ置換してから生成する — CIF 素の (DFT/物質化時) 格子より現フレーム
    の実測に近く、減算残差がクリーンになり少数新相の検出感度が上がる (M11 の「減算前ピーク整合」の operando 版)。

    `phase_id`/`formula` に相名 (`phase_spec.phase_name`) を使い、シム `identify_new_phases` の `known_ids`
    (相名) 除外と整合させる。**pymatgen 不在・CIF 読込失敗・ピーク生成失敗は例外を握って None を返す**
    (安全側フォールバック = warm-start せず静的同定に縮退; 提案≠適用)。決定論 (乱数なし)。

    :param phase_spec: 現行相 (CIF パスを持つ)
    :param refined_cell: 現フレームの精密化格子 (a,b,c,α,β,γ)。None なら CIF 素の格子を使う
    :param wavelength: XRD 生成の線源波長 (Å)。放射光/中性子系列では実波長を指定
    :param two_theta_range: XRD 生成の 2θ 範囲 (度)
    :returns: ピーク列付き ReferencePhase、または変換不能時 None
    """
    try:
        from pymatgen.core import Lattice, Structure

        from ..mp.xrd import simulate_reference_peaks

        structure = Structure.from_file(phase_spec.structure_path)
        if refined_cell is not None:
            structure = Structure(
                Lattice.from_parameters(*(float(x) for x in refined_cell)),
                structure.species,
                structure.frac_coords,
            )
        peaks = simulate_reference_peaks(
            structure, wavelength_angstrom=wavelength, two_theta_range=two_theta_range
        )
        composition = structure.composition
        return ReferencePhase(
            phase_id=phase_spec.phase_name,
            formula=composition.reduced_formula,
            element_system=tuple(sorted(str(e) for e in composition.elements)),
            peaks=peaks,
            energy_above_hull=None,
        )
    except Exception:
        return None  # pymatgen 不在 / 読込失敗 / 生成失敗 → warm-start せず静的同定へ縮退 (安全側)


def make_residual_cell_refiner(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    *,
    known_phases: Sequence[ReferencePhase] = (),
    wavelength: float = 1.5406,
    two_theta_range: tuple[float, float] = (10.0, 90.0),
    subtract_bg: bool = True,
    require_subtraction: bool = True,
    cfg: IdentifyConfig | None = None,
    prealign: Callable[..., object] | None = None,
) -> CellRefiner | None:
    """異方セルプリアラインを**既知相を引いた残差**へ向ける `cell_refiner` を作る (Issue #20 続き)。

    プリアラインの目的関数 (`autorietveld.lattice._peak_match_fom`) は観測ピーク基準のため、
    少数相のセルを**生パターン**へ整合させると FoM が支配相のピークに占められ、少数相の反射を
    支配相の位置へばら撒くセルを選ぶ。実測 (CaTeO3 frame180, delta ~28%, 出発セルを 4 通りに振る):

        整合先          delta セルの最大軸誤差
        生パターン       2.84 – 4.37 %   ← **出発セル (1.64–3.42%) より必ず悪化**
        残差 (alpha 減算) 0.42 – 0.64 %   ← 実測セルをほぼ回復

    誤セルの方が FoM が良い (0.268 < 0.290 for 真セル) ため `require_improvement` ガードでも
    止まらない — 目的関数側の問題であり、整合先を変えるのが正しい対処。

    :param two_theta: 観測 2θ (度, 昇順)
    :param intensity: 観測強度 (生)
    :param known_phases: 現行相 (精密化格子で生成したピーク列付。`phasespec_to_reference` 由来)
    :param wavelength: プリアラインの線源波長 (Å)
    :param two_theta_range: プリアラインの評価 2θ 範囲
    :param subtract_bg: SNIP 背景減算を行うか。残差経路では**残差計算側**に適用し (プリアラインには
        減算済を渡す)、既知相ゼロの経路ではプリアラインへそのまま渡す。``cfg`` 明示時は cfg が優先
    :param require_subtraction: True で「既知相を引けないならプリアラインしない」(``None`` を返す)。
        既存相があるのに生パターンへ整合するのは上表の通り有害なので、等方 strain のまま渡す方が
        安全側 (提案≠適用)。単相/静的同定など**候補が支配的と分かっている**呼び出しでのみ False にする
    :param cfg: 残差計算の設定 (`reference.iterative.subtract_known_phases` へ委譲)
    :param prealign: プリアライン関数 (**テスト注入専用**。既定 `prealign_cell_from_structure`)
    :returns: CIF パス→絶対格子 (or None) の `CellRefiner`。プリアラインすべきでないときは ``None``
        (呼び出し側は `identify_new_phases(cell_refiner=None)` = 等方 strain のまま)
    """
    from ..autorietveld.cell_refine import prealign_cell_from_structure
    from ..reference.iterative import subtract_known_phases

    align_fn = prealign if prealign is not None else prealign_cell_from_structure
    tt = np.asarray(two_theta, dtype=float)
    refs = list(known_phases)

    if not refs and require_subtraction:
        return None  # 既存相を引けない → 生パターン整合は有害 (上表) なのでプリアラインしない

    raw = np.asarray(intensity, dtype=float)
    bg = False if refs else subtract_bg  # 残差は減算済 → プリアライン側で二重に引かない
    # `subtract_bg` は残差計算側へ渡す (背景減算済データの二重減算を避ける)。cfg 明示時は cfg 優先。
    resid_cfg = cfg if cfg is not None else IdentifyConfig(subtract_bg=subtract_bg)
    cache: list[np.ndarray] = []

    def _pattern() -> np.ndarray:
        """整合先パターン (残差 or 生) を**初回呼び出し時に**作る。

        遅延にするのは (1) 候補が 1 つも物質化されなければ減算が要らない、(2) 減算が失敗しても
        `identify_new_phases` の `cell_refiner` 例外ハンドラに落ち**等方 strain へ縮退できる**
        ため (即時計算だと finder 全体が落ち、そのフレームの相同定ごと失われる)。
        """
        if not cache:
            cache.append(subtract_known_phases(tt, raw, refs, cfg=resid_cfg) if refs else raw)
        return cache[0]

    def refiner(cif_path: str) -> Cell6 | None:
        sol = align_fn(
            cif_path, tt, _pattern(),
            wavelength=wavelength, two_theta_range=two_theta_range, subtract_bg=bg,
        )
        return sol.cell if sol is not None else None  # type: ignore[union-attr]

    return refiner


def identify_new_phases(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    *,
    elements: Sequence[str],
    provider: ReferenceProvider,
    materializer: PhaseMaterializer,
    workdir: str,
    exclude_formulas: Sequence[str] = (),
    exclude_phase_ids: Sequence[str] = (),
    top_k: int = 1,
    hull_cutoff_ev: float | None = 0.1,
    subtract_bg: bool = True,
    refine_lattice: bool = True,
    max_strain: float = 0.05,
    kalpha2: object | None = None,
    name_prefix: str = "phase",
    cell_refiner: CellRefiner | None = None,
    rerank_top_k: int = 5,
    rerank_wavelength: float = 1.5406,
    require_full_element_system: bool = True,
    known_phases: Sequence[ReferencePhase] = (),
    cfg: IdentifyConfig | None = None,
) -> tuple[IdentifiedPhase, ...]:
    """パターンから新相を同定し上位 top_k を CIF に物質化して返す (M11 で `identify_pattern` 委譲)。

    **同定は M11 逐次減算同定 `reference.identify_pattern` に一本化** (FR-118-6)。静的同定は
    `known_phases=()` 起点、operando 逐次同定は現行相集合を `known_phases=` に渡す (同一プリミティブ)。
    残差支持による受理 (joint 非負スケール) と S/N 停止で、素の identify_phases ランキングより偽陽性を
    抑えつつ少数相を拾う。既知相 (`exclude_formulas` / `exclude_phase_ids` / `known_phases`) は受理集合
    から除外する (系列途中の新相出現で「既知の alpha ではない相 = delta」を選ぶため)。物質化 →
    PhaseSpec の配線 (材料化・異方セル補正・失敗フォールバック) は M9 のまま温存する。物質化に失敗した
    相は飛ばして次の受理相を採る。1 つも物質化できなければ空タプル。

    :param two_theta: 観測 2θ (度, 昇順)
    :param intensity: 観測強度 (残差 or 生パターン)
    :param elements: 相同定に許す元素系
    :param provider: 候補相供給元 (既定 MP)。identify_pattern に渡す
    :param materializer: phase_id→CIF 物質化器 (既定 MP)
    :param workdir: CIF 書き出し先ディレクトリ
    :param exclude_formulas: 除外する組成式 (既知相)
    :param exclude_phase_ids: 除外する相 ID (既知相)
    :param top_k: 物質化する上位受理相数
    :param hull_cutoff_ev: MP 安定性フィルタ (identify_pattern 経由で identify_phases へ)
    :param subtract_bg: 背景減算 (SNIP) してから同定するか
    :param refine_lattice: 格子精密化 (DFT 格子ズレ吸収) を有効にするか
    :param max_strain: 格子整合で許す等方歪みの上限。**DFT (MP) 構造は実測より格子が ~1–3% 大きい**
        ため既定 0.05 (M6 の 0.01 では吸収できず物質化構造が実測とずれ Rietveld が収束しない)。
        求めた歪みは物質化 CIF の格子にも適用する (materialize の strain)。
    :param name_prefix: 生成する相名/CIF 名の接頭辞
    :param cell_refiner: 物質化 CIF パス→精密化絶対格子 (or None) の異方セル補正器 (Issue #20)。
        与えると等方 strain で物質化した後、この補正器で**異方セル**を求め、非 None なら CIF を
        その絶対格子で再物質化する (DFT の異方的格子誤差を吸収; M6 等方 strain の上位互換)。
        補正器が None を返す/例外を投げると等方 strain 版のまま (安全側フォールバック)。
    :param rerank_top_k: >0 で相同定の上位 K 候補を**異方格子整合で再スコア**する (Issue #20 hybrid)。
        等方整合が DFT の軸別格子誤差で正解相を過小評価し top_k から落とすのを防ぐ (供給元が
        cell/crystal_system/hkl を持つ相のみ; MP 供給元は対応済)。
    :param rerank_wavelength: 異方再スコアの線源波長 (Å)
    :param require_full_element_system: True で新相候補を**全元素系 (elements すべてを含む) 相**に限定する
        (③ 化学ガード)。相転移は骨格元素を保存するため、元素部分集合の単純相 (元素 Ca・O₂・CaO 等) が
        少数相パターンに偶然マッチして上位化するのを防ぐ (実測: Ca-Te-O 三元限定で delta が #33→#1)。
        `identify_pattern` の `require_elements` (opt-in hard ガード) に写像する。
    :param known_phases: operando 現行相集合 (`ReferencePhase` 列)。`identify_pattern` の warm-start
        起点として先に残差から減算され、受理集合には残るが物質化からは除外される (既知相の再物質化回避)。
        既定 () で静的同定 (空集合起点)。M9 の呼び出し側は文字列 `exclude_*` のみを渡すため通常は空。
    :param cfg: 逐次同定の詳細設定 (snr_stop/eps_gain/try_k 等の第1/2層パラメータ)。個別引数
        (subtract_bg/refine_lattice/max_strain/hull_cutoff_ev/kalpha2/rerank_*/require_*) は本 cfg を
        `replace` で上書きするため、cfg 側で指定しても個別引数が優先される。None なら既定 IdentifyConfig。
    :returns: 物質化した IdentifiedPhase の列 (受理順・最大 top_k)
    """
    base = cfg if cfg is not None else IdentifyConfig()
    cfg = replace(
        base,
        subtract_bg=subtract_bg,
        refine_lattice=refine_lattice,
        max_strain=max_strain,
        hull_cutoff_ev=hull_cutoff_ev,
        kalpha2=kalpha2,
        rerank_top_k=rerank_top_k,
        rerank_wavelength=rerank_wavelength,
        require_elements=list(elements) if require_full_element_system else None,
    )
    result = identify_pattern(
        np.asarray(two_theta, dtype=float),
        np.asarray(intensity, dtype=float),
        provider,
        elements=list(elements),
        known_phases=known_phases,
        cfg=cfg,
    )

    excl_forms = {f.lower() for f in exclude_formulas}
    excl_ids = set(exclude_phase_ids)
    known_ids = {r.phase_id for r in known_phases}
    workpath = Path(workdir)
    workpath.mkdir(parents=True, exist_ok=True)

    out: list[IdentifiedPhase] = []
    for accepted in result.accepted:  # 受理順 (残差支持で採った順 = 概ね強度降順)
        ref = accepted.reference
        # 既知相 (文字列除外 / known_phases 起点) は物質化しない。新相のみ CIF 化する。
        if (
            ref.phase_id in excl_ids
            or ref.phase_id in known_ids
            or ref.formula.lower() in excl_forms
        ):
            continue
        cif_name = f"{_sanitize(name_prefix)}_{_sanitize(ref.phase_id)}.cif"
        cif_path = str(workpath / cif_name)
        strain = float(accepted.strain)
        # 【整合先の出発セル】: cell_refiner があるときは**等方 strain を掛けずに**物質化する。
        #   同定段の strain は「支配相に汚染されうるパターン」に対しランキング用に求めた量で、
        #   符号を誤ると DFT 誤差を打ち消すどころか**増幅**し、プリアラインの探索域 (±5%/軸) の
        #   外へ出発点を押し出す。実測 (CaTeO3, 支配相を引かない静的同定): 既に c が +3.4% 過大な
        #   DFT セルに strain +3.4% が乗り、出発点 c +6.94% → 残差整合でも 1.43% までしか戻せない
        #   (DB 素のセルから始めれば 0.51%)。異方プリアラインの方が良い推定量なので素から始める。
        seed_strain = 0.0 if cell_refiner is not None else strain
        try:
            materializer.materialize(
                ref.phase_id, list(elements), cif_path, strain=seed_strain
            )
        except Exception:
            continue  # 物質化失敗は飛ばして次の受理相へ (提案≠適用の安全側)
        # 異方セル補正 (Issue #20): DFT の軸別誤差を異方セルプリアラインで求め、非 None ならその
        # 絶対格子で再物質化する。失敗/None は**等方 strain 版へ戻す** (従来の補正を失わない)。
        refined_cell: Cell6 | None = None
        if cell_refiner is not None:
            try:
                refined_cell = cell_refiner(cif_path)
            except Exception:
                refined_cell = None
            try:
                if refined_cell is not None:
                    materializer.materialize(
                        ref.phase_id, list(elements), cif_path, cell=refined_cell
                    )
                elif strain:
                    materializer.materialize(
                        ref.phase_id, list(elements), cif_path, strain=strain
                    )
            except Exception:
                refined_cell = None  # 再物質化失敗は素の DB セルのまま (物質化自体は落とさない)
        phase_name = f"{_sanitize(name_prefix)}_{_sanitize(ref.formula)}"
        out.append(
            IdentifiedPhase(
                phase_spec=PhaseSpec(
                    structure_path=cif_path, phase_name=phase_name, format_hint="CIF"
                ),
                phase_id=ref.phase_id,
                formula=ref.formula,
                score=float(accepted.score),
                strain=float(accepted.strain),
                source="materials_project",
                refined_cell=refined_cell,
            )
        )
        if len(out) >= top_k:
            break
    return tuple(out)


# ------------------------- MP 実装 (遅延 import 境界) -------------------------


class MPMaterializer:
    """Materials Project 実装の物質化器 (phase_id→CIF, 遅延 import)。

    MPClient で元素系を検索し material_id が一致する実構造を pymatgen `CifWriter` で CIF 化する。
    ``entries`` を注入すればネットワーク再取得を避けられる (provider と同じ client を共有)。
    """

    def __init__(self, client: object | None = None) -> None:
        self._client = client
        self._cache: dict[str, object] = {}  # material_id -> structure

    def _lookup(self, phase_id: str, elements: Sequence[str]) -> object:
        if phase_id in self._cache:
            return self._cache[phase_id]
        if self._client is None:
            from ..mp.client import MPRestClient  # pragma: no cover - 環境依存

            self._client = MPRestClient()  # 環境変数 MATERIALS_PROJECT_API を読む
        entries = self._client.search(list(elements))  # type: ignore[union-attr]
        for e in entries:
            sid = getattr(e, "material_id", None)
            struct = getattr(e, "structure", None)
            if sid is not None and struct is not None:
                self._cache[str(sid)] = struct
        if phase_id not in self._cache:
            raise ValueError(f"MP に相 {phase_id} の実構造が見つかりません。")
        return self._cache[phase_id]

    def materialize(
        self,
        phase_id: str,
        elements: Sequence[str],
        out_path: str,
        strain: float = 0.0,
        cell: Cell6 | None = None,
    ) -> str:
        structure = self._lookup(phase_id, elements)
        return structure_to_cif(structure, out_path, strain=strain, cell=cell)
