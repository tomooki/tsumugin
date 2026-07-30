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
from .inp import (
    Param,
    PhaseHistogramTerms,
    TopasDocument,
    TopasHistogram,
    TopasPhase,
    _slug,
)

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
        "preferred_orientation",
        "absorption",
        "freeze_others",
    }
)
"""現在翻訳できるフラグ。残る ``tof_profile`` / ``hydrostatic_strain`` は実 TOF /
マルチヒストグラム実データで検算できる段 (#174) と併せて追加する — 実行して確かめられない
翻訳表は書かない (言語仕様の正が暗号化 PDF でなく実行結果しかないため)。"""

#: 球面調和の既定次数 (GSAS 側 `engine._apply_stage` の `Pref.Ori.` 既定と揃える)。
_PO_DEFAULT_ORDER = 4

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
            # 【全サイト一斉解放をしない】: 占有率はスケール因子と大域的に縮退するので、
            #   全部解放すると Rwp は下がるのに占有率が 1 を超える非物理解へ行ける
            #   (実 fluoroapatite で occ 0.68-2.24 を実測)。宣言されたサイトのみ。
            allowed = occupancy and site.label in phase.free_occupancy_labels
            updates["occupancy"] = _set_refine(site.occupancy, allowed)
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
    """``prm !ze0 …`` のような**宣言行**の ``!`` を付け外しする。

    【宣言行だけを見る】: 同じ名前は参照側にも現れる (``th2_offset = ze0;``)。行全体を
    対象に置換すると参照式が ``= !ze0;`` に化けて INP が壊れる。TOPAS で ``!`` が意味を
    持つのは宣言のときだけなので、``prm`` で始まる行に限定する。
    """
    preamble = []
    for line in hist.preamble:
        stripped = line.lstrip()
        if stripped.startswith(f"prm !{prefix}") and enable:
            line = line.replace(f"prm !{prefix}", f"prm {prefix}", 1)
        elif stripped.startswith(f"prm {prefix}") and not enable:
            line = line.replace(f"prm {prefix}", f"prm !{prefix}", 1)
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
        phases = [
            _release_sites(p, coords=False, beq=False, occupancy=False).with_updates(
                release_occupancy_groups=False, release_beq_groups=False
            )
            for p in phases
        ]
        # 球面調和は**宣言そのものが解放**なので、凍結は行を落とすことで表す
        # (`!` を付ける先が無い — 係数は TOPAS が自動生成する)。
        histograms = [_drop_phase_extras(h, "PO_Spherical_Harmonics") for h in histograms]

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
        # 共有 prm (混合占有サイトの等値 beq) も同時に解放する。参照式のサイト側は
        # 触れないので、ここを忘れると「uiso 段が何も解放しない」になる。
        phases = [
            _release_sites(p, beq=True).with_updates(release_beq_groups=True) for p in phases
        ]
    if flags.get("occupancy"):
        phases = [
            _release_sites(p, occupancy=True).with_updates(release_occupancy_groups=True)
            for p in phases
        ]

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

    if "preferred_orientation" in flags:
        histograms = _apply_preferred_orientation(
            histograms, phases, flags["preferred_orientation"]
        )

    shared = tuple(doc.shared_params)
    if flags.get("absorption"):
        histograms, shared = _apply_absorption(histograms, phases, shared, stage.label)

    # phase_fraction_sum: TOPAS は MVW が重量分率を正規化して返すため制約不要 (no-op)。

    return doc.with_updates(
        phases=tuple(phases), histograms=tuple(histograms), shared_params=shared
    )


# ---------------------------------------------------------------- 選択配向 / 吸収


def _phase_extras(
    hist: TopasHistogram, phase_name: str, line: str, marker: str
) -> TopasHistogram:
    """``str`` ブロックの追加行を**1 本だけ**保つ (同じ段を 2 度当てても重複しない)。"""
    terms = _terms_for(hist, phase_name)
    kept = tuple(x for x in terms.extras if marker not in x)
    return _with_terms(hist, phase_name, terms.with_updates(extras=(*kept, line)))


def _drop_phase_extras(hist: TopasHistogram, marker: str) -> TopasHistogram:
    """``str`` ブロックの追加行のうち ``marker`` を含むものを落とす。"""
    return hist.with_updates(
        phase_terms={
            name: terms.with_updates(
                extras=tuple(x for x in terms.extras if marker not in x)
            )
            for name, terms in hist.phase_terms.items()
        }
    )


def _apply_preferred_orientation(
    histograms: "list[TopasHistogram]", phases: "list[TopasPhase]", value: object
) -> "list[TopasHistogram]":
    """選択配向を球面調和で入れる。

    GSAS の ``Pref.Ori.`` は次数付きの球面調和で、TOPAS の ``PO_Spherical_Harmonics(sh, order)``
    が対応する。March-Dollase (``PO``) は **hkl 方向を引数に要求する**が中立フラグはその情報を
    運ばないので使わない — 方向を勝手に決めるのは「別のモデルを黙って当てはめた」ことになる。

    球面調和は**宣言そのものが解放**である (係数は TOPAS が自動生成する) ため、解放/凍結は
    行の有無で表す。
    """
    order = _PO_DEFAULT_ORDER if value is True else int(value)  # type: ignore[arg-type]
    for index, hist in enumerate(histograms):
        for phase in phases:
            # 【名前は相 × ヒストグラムで一意に】: TOPAS のパラメータ名は大域なので、
            #   同名だと全相が 1 つの配向分布を強制的に共有する。
            name = f"po_{_slug(phase.phase_name)}_h{index}"
            hist = _phase_extras(
                hist,
                phase.phase_name,
                f"PO_Spherical_Harmonics({name}, {order})",
                "PO_Spherical_Harmonics",
            )
        histograms[index] = hist
    return histograms


def _apply_absorption(
    histograms: "list[TopasHistogram]",
    phases: "list[TopasPhase]",
    shared: "tuple[Param, ...]",
    stage_label: str,
) -> "tuple[list[TopasHistogram], tuple[Param, ...]]":
    """試料吸収 (円筒 µR) を入れる。

    GSAS の Sample Parameters ``Absorption`` に相当。TOPAS の ``Cylindrical_I_Correction(µR)``
    は ``scale_pks`` を書き換えるので**``str`` ブロックにしか置けない**が、吸収は試料の性質
    なので相ごとに別の値を持つのは物理的に誤り。宣言はトップレベルの共有 ``prm`` に 1 つ置き、
    各相からは参照させる。

    **マクロではなくその展開形を書く**: ``Cylindrical_I_Correction(=mur_h0;)`` /
    ``Cylindrical_I_Correction(, =mur_h0;)`` はどちらも ``Error loading sstring_in`` で
    異常終了する (実測)。マクロは名前を受け取って自分で ``prm`` を宣言する形しか通らないため、
    共有したい場合は ``topas.inc`` の中身をそのまま書くしかない。

    :raises UnsupportedStageFlagError: 反射光学系のとき。平板試料に円筒補正を当てるのは
        **黙って別のモデルを適用する**ことになるので拒否する。
    """
    declared = {p.name for p in shared}
    for index, hist in enumerate(histograms):
        if hist.is_bragg_brentano:
            raise UnsupportedStageFlagError(
                f"absorption: 反射光学系 (Bragg-Brentano) のヒストグラム {index} には "
                f"円筒吸収補正を当てられません (段 '{stage_label}')。平板試料に円筒の式を"
                f"当てるのは別のモデルを黙って適用することになるため停止します。"
            )
        name = f"mur_h{index}"
        if name not in declared:
            # µR の箱は TOPAS マクロと同じ (0.0001–12)。初期値は薄めの試料を想定した 0.5。
            shared = (*shared, Param(0.5, refine=True, name=name, minimum=1e-4, maximum=12.0))
            declared.add(name)
        for phase in phases:
            hist = _phase_extras(
                hist,
                phase.phase_name,
                f"scale_pks = AL_Cyl_Corr({name}) Cos(Th)^2 "
                f"+ AB_Cyl_Corr({name}) Sin(Th)^2;",
                "_Cyl_Corr(",
            )
        histograms[index] = hist
    return histograms, shared
