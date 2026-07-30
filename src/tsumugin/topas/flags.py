"""段階解放フラグ → TOPAS 解放指示 (M12 T6) — 純関数。

`autorietveld.engine._apply_stage` の TOPAS 版。`autorietveld.recipe.build_recipe` が作る
**中立な宣言的フラグ**を受け取り、`TopasDocument` を「そのパラメータが解放された新しい文書」へ
純粋変換する。

**GSAS との意味論の違い**: GSAS の ``set_refinements`` は**置換**なので engine 側が per-atom の
累積マップを持つ必要があったが、TOPAS は毎回 INP を書き下すため**文書がそのまま状態**である。
`apply_stage` は前段の文書を受けて新しい文書を返す純関数で、累積は自然に表現される
(``freeze_others`` は「解放を落とした文書を作る」だけ)。

**未対応フラグは黙って無視しない** (:class:`UnsupportedStageFlagError`)。無視すると
「段を適用したのに何も変わっていない」= CLAUDE.md の無言 no-op と同じ病理を招く。
"""

from __future__ import annotations

from dataclasses import replace

from ..autorietveld.model import RefinementStage
from ..errors import TsumuginError
from .inp import Param, PhaseHistogramTerms, TopasDocument, TopasHistogram, TopasPhase

__all__ = ["SUPPORTED_FLAGS", "UnsupportedStageFlagError", "apply_stage"]


class UnsupportedStageFlagError(TsumuginError):
    """TOPAS バックエンドがまだ翻訳できない段階フラグを与えられたとき。

    **黙って無視しない**のが要点。無視すると「段を適用したのに何も解放されていない」段が
    rwp にも reverted にも現れないまま完走する (CLAUDE.md の無言 no-op と同型)。
    """


SUPPORTED_FLAGS: frozenset[str] = frozenset(
    {
        "background",
        "scale",
        "cell",
        "coords",
        "uiso",
        "occupancy",
        "size_strain",
        "displacement",
        "profile",
        "profile_lorentzian",
        "profile_asymmetry",
        "phase_fraction_sum",
        "freeze_others",
    }
)
"""現在翻訳できるフラグ。``recipe`` が生成しうる残り (``tof_profile`` / ``absorption`` /
``hydrostatic_strain`` / ``preferred_orientation``) は M12 の後続タスクで追加する。"""

_PROFILE_NAMES = {"profile": ("u", "v", "w"), "profile_lorentzian": ("x", "y")}


def _set_refine(param: Param, refine: bool) -> Param:
    """参照式のパラメータは解放できない (対称拘束・共有の従属側)。"""
    if param.is_reference:
        return param
    return replace(param, refine=refine)


def _release_cell(phase: TopasPhase, enable: bool) -> TopasPhase:
    free = set(phase.free_cell_keys) if phase.free_cell_keys else {
        k for k, v in phase.cell.items() if not v.is_reference
    }
    cell = {
        key: _set_refine(param, enable and key in free) for key, param in phase.cell.items()
    }
    return phase.with_updates(cell=cell)


def _release_sites(
    phase: TopasPhase, *, coords: bool | None = None, beq: bool | None = None,
    occupancy: bool | None = None,
) -> TopasPhase:
    sites = []
    for site in phase.sites:
        updates: dict[str, object] = {}
        if coords is not None:
            # 【サイト対称】: 特殊位置の成分 (鏡面上の y=1/4 など) や他軸と結束する成分を
            #   解放すると対称性が壊れる。`topas.symmetry` が対称操作から求めた自由軸だけを
            #   解放する (GSAS の GetCSxinel 相当)。判定できていない (空) なら触らない。
            for axis in ("x", "y", "z"):
                allowed = coords and axis in site.free_coord_axes
                updates[axis] = _set_refine(getattr(site, axis), allowed)
        if beq is not None:
            updates["beq"] = _set_refine(site.beq, beq)
        if occupancy is not None:
            updates["occupancy"] = _set_refine(site.occupancy, occupancy)
        sites.append(site.with_updates(**updates))
    return phase.with_updates(sites=tuple(sites))


def _terms_for(hist: TopasHistogram, phase_name: str) -> PhaseHistogramTerms:
    return hist.phase_terms.get(phase_name, PhaseHistogramTerms())


def _with_terms(
    hist: TopasHistogram, phase_name: str, terms: PhaseHistogramTerms
) -> TopasHistogram:
    merged = dict(hist.phase_terms)
    merged[phase_name] = terms
    return hist.with_updates(phase_terms=merged)


def _toggle_profile_names(hist: TopasHistogram, keys: tuple[str, ...], enable: bool
                          ) -> TopasHistogram:
    """``TCHZ_Peak_Type`` 行の該当パラメータの ``!`` を付け外しして解放/凍結する。

    ピーク形状の行は **``str`` ブロック内** = `PhaseHistogramTerms.peak_type` にある
    (xdd 直下だと TOPAS が解決できないため)。
    """
    terms = dict(hist.phase_terms)
    for phase_name, term in terms.items():
        if not term.peak_type:
            continue
        line = term.peak_type
        for key in keys:
            marker = f"pk{key}"
            if enable:
                line = line.replace(f"!{marker}", marker)
            elif f"!{marker}" not in line:
                line = line.replace(marker, f"!{marker}")
        terms[phase_name] = term.with_updates(peak_type=line)
    return hist.with_updates(phase_terms=terms)


def _toggle_named(hist: TopasHistogram, prefix: str, enable: bool) -> TopasHistogram:
    """``ZE(!ze0, …)`` のような名前付きパラメータの ``!`` を付け外しする。"""
    preamble = []
    for line in hist.preamble:
        if enable:
            line = line.replace(f"!{prefix}", prefix)
        elif prefix in line and f"!{prefix}" not in line:
            line = line.replace(prefix, f"!{prefix}")
        preamble.append(line)
    return hist.with_updates(preamble=tuple(preamble))


def apply_stage(doc: TopasDocument, stage: RefinementStage) -> TopasDocument:
    """段階フラグを適用した新しい文書を返す (純粋変換)。

    :raises UnsupportedStageFlagError: 未翻訳のフラグが含まれるとき
    """
    flags = dict(stage.flags)
    unknown = sorted(set(flags) - SUPPORTED_FLAGS)
    if unknown:
        raise UnsupportedStageFlagError(
            f"TOPAS バックエンドが未対応の段階フラグです: {unknown} (段 '{stage.label}')。"
            f"黙って無視すると「解放されていない段」が完走してしまうため停止します。"
        )

    phases = list(doc.phases)
    histograms = list(doc.histograms)

    if flags.get("freeze_others"):
        # 累積解放を一旦落とす。TOPAS では「解放を落とした文書を作る」だけで表現できる。
        phases = [_release_cell(p, False) for p in phases]
        phases = [_release_sites(p, coords=False, beq=False, occupancy=False) for p in phases]

    if "background" in flags:
        spec = flags["background"]
        coeffs = int(spec.get("coeffs", 6)) if isinstance(spec, dict) else 6
        histograms = [
            h.with_updates(background=Param(0.0, refine=True), background_coeffs=coeffs)
            for h in histograms
        ]

    if flags.get("scale"):
        for i, hist in enumerate(histograms):
            for phase in phases:
                terms = _terms_for(hist, phase.phase_name)
                current = terms.scale or Param(1e-4)
                hist = _with_terms(
                    hist, phase.phase_name,
                    terms.with_updates(scale=replace(current, refine=True)),
                )
            histograms[i] = hist

    if "cell" in flags:
        enable = flags["cell"] is not False
        phases = [_release_cell(p, enable) for p in phases]

    if flags.get("coords"):
        phases = [_release_sites(p, coords=True) for p in phases]
    if flags.get("uiso"):
        phases = [_release_sites(p, beq=True) for p in phases]
    if flags.get("occupancy"):
        phases = [_release_sites(p, occupancy=True) for p in phases]

    if flags.get("size_strain"):
        for i, hist in enumerate(histograms):
            for phase in phases:
                terms = _terms_for(hist, phase.phase_name)
                hist = _with_terms(
                    hist, phase.phase_name,
                    terms.with_updates(
                        size_lorentzian=Param(
                            (terms.size_lorentzian or Param(200.0)).value, refine=True
                        ),
                        strain_lorentzian=Param(
                            (terms.strain_lorentzian or Param(0.01)).value, refine=True
                        ),
                    ),
                )
            histograms[i] = hist

    if flags.get("displacement"):
        # GSAS の "Shift"/"DisplaceX" に相当。TOPAS ではゼロ点 (ZE) と試料変位が別物だが、
        # v1 はゼロ点のみを解放する (両方同時は 2θ 方向で強く縮退するため)。
        histograms = [_toggle_named(h, "ze", True) for h in histograms]

    for flag, keys in _PROFILE_NAMES.items():
        if flags.get(flag):
            histograms = [_toggle_profile_names(h, keys, True) for h in histograms]

    if flags.get("profile_asymmetry"):
        histograms = [
            h.with_updates(preamble=(*h.preamble, "Simple_Axial_Model(@, 5.0)"))
            if not any("Simple_Axial_Model" in line for line in h.preamble)
            else h
            for h in histograms
        ]

    # phase_fraction_sum: TOPAS は MVW が重量分率を正規化して返すため制約不要 (no-op)。

    return doc.with_updates(phases=tuple(phases), histograms=tuple(histograms))
