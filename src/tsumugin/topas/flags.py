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
from typing import Sequence

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

__all__ = [
    "NOT_APPLICABLE_FLAGS",
    "SUPPORTED_FLAGS",
    "UnsupportedStageFlagError",
    "apply_stage",
]


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
        "preferred_orientation",
        "absorption",
        "tof_profile",
        "hydrostatic_strain",
        "freeze_others",
    }
)
"""現在翻訳できるフラグ。

``hydrostatic_strain`` は **joint 専用** — ヒストグラム間の温度差を per-xdd の格子オフセットで
吸収する量なので、単一ヒストグラムでは格子そのものと縮退する
(:func:`apply_stage` が明示的に失敗させる)。

:data:`NOT_APPLICABLE_FLAGS` は「GSAS には要るが TOPAS には**概念が無い**」フラグで、
受理せず理由付きで失敗させる。"""

#: TOPAS には対応物が無いフラグ → 理由。**黙って受理して no-op にしない**。
#:
#: 以前は ``phase_fraction_sum`` を受理して何もしていなかったが、それだと ③ から見て
#: 「相分率の拘束を掛けた」ことになってしまう。実際には TOPAS の相ごと ``scale`` が
#: 相分率そのもので、``MVW`` が重量分率を正規化して返すため拘束する対象が無い。
NOT_APPLICABLE_FLAGS: "dict[str, str]" = {
    "phase_fraction_sum": (
        "TOPAS では相ごとの `scale` が相分率そのもので、`MVW` が重量分率を正規化して返すため "
        "和=1 の拘束は存在しません (GSAS は per-histogram の HAP Scale を別々に持つので要る)。"
        "相分率は `scale` フラグで解放してください。"
    ),
}

#: 格子オフセットを張る軸。**角度には張らない** — 熱膨張の等方成分ではないうえ、
#: 90° 近傍では角度方向の微分がほぼ 0 でヘッシアンが特異になる (structure.py と同じ判断)。
_STRAIN_AXES = ("a", "b", "c")

#: 格子オフセットの箱 (±2%)。実データの温度差 (M7 T3 の 285 K) が生む歪みは 0.3% 程度なので
#: 物理的には十分広い。
#:
#: **±5% は実 tc.exe が異常終了する** (実測): TOPAS はセルが式で書かれていると hkl の d 範囲を
#: 箱の分だけ広げて評価するらしく、**波長の長い CW 中性子**では縮み側が ``d < λ/2`` を跨いで
#: ``Invalid d spacing encountered`` で落ちる (PbSO4 joint: λ=1.909 Å に対し観測の d_min は
#: λ/2 の 3% 上にしかない)。同じ INP でも X 線ヒストグラムに張った場合は完走するので、
#: 「式にすると落ちる」のではなく**箱が波長に対して広すぎる**のが原因である。
#: ±1%/±2% は実測で完走する。
_STRAIN_LIMIT = 0.02

#: TOF のピーク幅パラメータ接頭辞 (`instrument.tof_peak_type` が宣言する名前と対)。
_TOF_WIDTH_NAMES = ("tofw1", "tofw2")

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


def _apply_cell_strain(
    histograms: list[TopasHistogram], phases: Sequence[TopasPhase], enable: bool
) -> list[TopasHistogram]:
    """2 本目以降の各 xdd に格子オフセット ε を張る (先頭は基準として 0 固定)。"""
    out = list(histograms)
    for index, hist in enumerate(out):
        if index == 0:
            continue
        for phase in phases:
            terms = _terms_for(hist, phase.phase_name)
            stem = _slug(phase.phase_name)
            strain = dict(terms.cell_strain or {})
            for axis in _STRAIN_AXES:
                param = phase.cell.get(axis)
                # 従属軸 (``=Get(a);``) は独立軸に追随するので張らない (二重に張ると縮退)。
                if param is None or param.is_reference:
                    continue
                existing = strain.get(axis)
                if existing is not None:
                    strain[axis] = replace(existing, refine=enable)
                elif enable:
                    strain[axis] = Param(
                        0.0,
                        refine=True,
                        name=f"eps_{stem}_{axis}_h{index}",
                        minimum=-_STRAIN_LIMIT,
                        maximum=_STRAIN_LIMIT,
                    )
            hist = _with_terms(hist, phase.phase_name, terms.with_updates(cell_strain=strain))
        out[index] = hist
    return out


def _with_terms(
    hist: TopasHistogram, phase_name: str, terms: PhaseHistogramTerms
) -> TopasHistogram:
    merged = dict(hist.phase_terms)
    merged[phase_name] = terms
    return hist.with_updates(phase_terms=merged)


def _toggle_tof_widths(hist: TopasHistogram, enable: bool) -> TopasHistogram:
    """TOF ピーク幅 (``prm !tofw1…`` / ``!tofw2…``) の ``!`` を付け外しする。

    **宣言行だけを見る** — 同じ名前は ``pv_fwhm = tofw1… D_spacing + …`` の参照側にも
    現れるので、行全体を置換すると式が ``!tofw1…`` に化けて INP が壊れる (ゼロ点と同型)。
    """
    terms = dict(hist.phase_terms)
    for phase_name, term in terms.items():
        if not term.peak_type:
            continue
        lines = []
        for line in term.peak_type.splitlines():
            for name in _TOF_WIDTH_NAMES:
                if enable and line.startswith(f"prm !{name}"):
                    line = line.replace(f"prm !{name}", f"prm {name}", 1)
                elif not enable and line.startswith(f"prm {name}"):
                    line = line.replace(f"prm {name}", f"prm !{name}", 1)
            lines.append(line)
        terms[phase_name] = term.with_updates(peak_type="\n".join(lines))
    return hist.with_updates(phase_terms=terms)


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
    # 【1 回でまとめて報告する】: 「概念が無い」と「未知」を別々に投げると、両方入った段で
    #   1 つ直すたびに実データの精密化をやり直す羽目になる (③ から見て往復が増える)。
    inapplicable = sorted(set(flags) & set(NOT_APPLICABLE_FLAGS))
    unknown = sorted(set(flags) - SUPPORTED_FLAGS - set(NOT_APPLICABLE_FLAGS))
    if inapplicable or unknown:
        parts: list[str] = []
        if inapplicable:
            reasons = " / ".join(NOT_APPLICABLE_FLAGS[name] for name in inapplicable)
            parts.append(f"TOPAS に対応物が無い段階フラグです: {inapplicable}。{reasons}")
        if unknown:
            parts.append(
                f"TOPAS バックエンドが未対応の段階フラグです: {unknown}。"
                "黙って無視すると「解放されていない段」が完走してしまうため停止します。"
            )
        raise UnsupportedStageFlagError(f"(段 '{stage.label}') " + " ".join(parts))

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
        histograms = [_toggle_tof_widths(h, False) for h in histograms]
        histograms = _apply_cell_strain(histograms, phases, False)

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

    if "hydrostatic_strain" in flags:
        enable = flags["hydrostatic_strain"] is not False
        if enable and len(histograms) < 2:
            # 【縮退】: 単一ヒストグラムでは ε と格子が同じ方向を向く。黙って no-op に
            #   すると「段を適用したのに何も解放されていない」段が完走する。
            raise UnsupportedStageFlagError(
                f"hydrostatic_strain は joint (複数ヒストグラム) 専用です (段 '{stage.label}')。"
                "単一ヒストグラムでは格子そのものと縮退するため張れません。"
            )
        histograms = _apply_cell_strain(histograms, phases, enable)

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
        # 【TOF には張らない — 飛ばすのではなくモデルが違う】: ``CS_L``/``Strain_L`` は
        #   ``lor_fwhm = 0.1 Rad Lam / (Cos(Th) CS)`` と ``lor_fwhm = MS Tan(Th)`` = **波長と
        #   Bragg 角で書かれた角度分散のモデル**で、TOF (x 軸が時間) には対応物が無い。
        #   実 tc.exe は ``Negative FWHM encountered`` で**異常終了する** (TOF を 1 本混ぜる
        #   だけで落ち、X 線だけなら完走することを実測)。TOF で同じ物理を担うのは幅の
        #   d/d² 項 (``tof_profile``) である — 微小歪みは Δd/d 一定 → FWHM ∝ d、
        #   結晶子サイズは Δd ∝ d² → FWHM ∝ d²。
        if all(hist.is_tof for hist in histograms):
            raise UnsupportedStageFlagError(
                f"size_strain を張れるヒストグラムがありません (段 '{stage.label}')。"
                "``CS_L``/``Strain_L`` は角度分散のモデルなので TOF には当てられません "
                "(実 tc.exe は Negative FWHM で異常終了する)。TOF の粒径/微小歪みは "
                "``tof_profile`` (幅の d/d² 項) が担います。"
            )
        for i, hist in enumerate(histograms):
            if hist.is_tof:
                continue
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

    if flags.get("tof_profile"):
        # TOF の d 依存幅 (GSAS の sig-1/sig-2 相当)。装置プロファイルは較正済みなので
        # 既定レシピには載せず、近似 instprm を実測へ寄せたいときの opt-in 段にする
        # (GSAS 経路 T4 と同じ教訓)。CW ヒストグラムには当てない (混在 joint がありうる)。
        histograms = [
            _toggle_tof_widths(h, True) if h.is_tof else h for h in histograms
        ]

    if "preferred_orientation" in flags:
        histograms = _apply_preferred_orientation(
            histograms, phases, flags["preferred_orientation"]
        )

    shared = tuple(doc.shared_params)
    if flags.get("absorption"):
        histograms, shared = _apply_absorption(histograms, phases, shared, stage.label)


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
