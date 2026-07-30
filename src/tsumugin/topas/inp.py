"""TOPAS INP 文書のビルダ (M12 T2) — 純関数・TOPAS 非依存。

`autorietveld.recipe` / `autorietveld.validity` と同じ立ち位置で、**tc.exe を起動せずに
テストできる**層。ここで組んだ文書を `topas.driver` が書き出して実行する。

**TOPAS のパラメータ意味論** (Tutorial INP から実証):

===========================  ==============================
書き方                        意味
===========================  ==============================
``9.18``                     固定 (無名)
``@ 9.18``                   精密化 (無名)
``lpa1 9.18``                精密化 (名前付き — 名前は既定で精密化対象)
``!lpa1 9.18``               固定 (名前付き; 参照先にできる)
``=lpa1;``                   他パラメータの参照 (式)
``@ 9.18 min 9 max 9.3``     範囲付き
===========================  ==============================

**joint (複数ヒストグラム) の扱い**: TOPAS には GSAS の「1 相を N 本のヒストグラムが共有する」
ネイティブ機構が無い。公式 Tutorial (``PDF Analysis/Joint Bragg-PDF Refinement/
neutron_Si_corefinement.inp``) の idiom に従い、**構造パラメータ (格子・座標・占有率・beq) を
トップレベル ``prm`` へ持ち上げ、各 ``xdd`` 内の ``str`` から ``=name;`` で参照する**。
scale・背景・プロファイル・size/strain は**ヒストグラム固有**なので持ち上げない
(GSAS の HAP = histogram-and-phase パラメータと同じ切り分け)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Mapping, Sequence

__all__ = [
    "Param",
    "PhaseHistogramTerms",
    "TopasDocument",
    "TopasHistogram",
    "TopasPhase",
    "TopasSite",
    "render_param",
]

_INDENT_HIST = "   "
_INDENT_PHASE = "      "


def _fmt(value: float) -> str:
    """浮動小数を決定論的に整形する (repr は Python の最短往復表現でプラットフォーム非依存)。"""
    return repr(float(value))


def _slug(text: str) -> str:
    """TOPAS のパラメータ名に使える識別子へ落とす (英数字と _ のみ)。

    **大小を潰さない**: 原子ラベルは大小で別物になり得る (``O1`` と ``o1``) ため、
    小文字化すると別サイトのパラメータが同名に衝突して**黙って共有される**。
    """
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", text).strip("_")
    return cleaned or "p"


@dataclass(frozen=True)
class Param:
    """TOPAS のパラメータ 1 個 (値 + 精密化フラグ + 名前 + 範囲)、または他パラメータへの参照。"""

    value: float = 0.0
    refine: bool = False
    name: "str | None" = None
    minimum: "float | None" = None
    maximum: "float | None" = None
    expression: "str | None" = None
    """設定時は値でなく式としてレンダリングする (``=expr;``)。共有参照に使う。"""

    @classmethod
    def reference(cls, name: str) -> "Param":
        """他パラメータ ``name`` を参照するパラメータ。"""
        return cls(expression=name)

    @property
    def is_reference(self) -> bool:
        return self.expression is not None

    def with_updates(self, **kw: object) -> "Param":
        return replace(self, **kw)  # type: ignore[arg-type]


def render_param(param: Param) -> str:
    """:class:`Param` を TOPAS の字面へ落とす。"""
    if param.expression is not None:
        return f"={param.expression};"
    if param.name:
        head = f"{param.name} {_fmt(param.value)}" if param.refine else (
            f"!{param.name} {_fmt(param.value)}"
        )
    else:
        head = f"@ {_fmt(param.value)}" if param.refine else _fmt(param.value)
    if param.minimum is not None:
        head += f" min {_fmt(param.minimum)}"
    if param.maximum is not None:
        head += f" max {_fmt(param.maximum)}"
    return head


@dataclass(frozen=True)
class TopasSite:
    """結晶学的サイト 1 つ (``site`` 行)。"""

    label: str
    element: str
    x: Param
    y: Param
    z: Param
    occupancy: Param = field(default_factory=lambda: Param(1.0))
    beq: Param = field(default_factory=lambda: Param(1.0))
    """等方性温度因子 B。**Uiso とは B = 8π²·Uiso の関係** (換算は topas.structure が担う)。"""
    free_coord_axes: tuple[str, ...] = ()
    """**独立に解放してよい**座標軸 (``"x"``/``"y"``/``"z"``)。

    サイト対称で固定される成分 (鏡面上の ``y = 1/4`` など) や、他軸と結束する成分を
    解放すると**対称性が壊れる**。しかも Rwp は下がることがあるので静かに間違った構造へ
    行き着く。GSAS 経路の ``GSASIIspc.GetCSxinel`` に相当する情報で、`topas.symmetry` が
    対称操作から求める。空なら座標を解放しない (判定できないときは触らない)。
    """

    def with_updates(self, **kw: object) -> "TopasSite":
        return replace(self, **kw)  # type: ignore[arg-type]


@dataclass(frozen=True)
class PhaseHistogramTerms:
    """ヒストグラムと相の**組**に属する項 (GSAS の HAP に相当)。

    scale / 結晶子サイズ / 微小歪みは装置とサンプルの組で決まるため、joint でも共有しない。
    """

    scale: "Param | None" = None
    size_lorentzian: "Param | None" = None
    strain_lorentzian: "Param | None" = None
    preferred_orientation: "str | None" = None
    """選択配向マクロの行 (例 ``PO_Spherical_Harmonics(sh, 4)``)。"""
    peak_type: "str | None" = None
    """ピーク形状マクロの行 (例 ``TCHZ_Peak_Type(...)``)。

    **``str`` ブロックの中に置く**必要がある (実測: xdd 直下だと
    ``Cannot locate pk_type from gen_fit_obj`` で異常終了する)。ピーク形状は相と
    ヒストグラムの組に属する量なので、モデル上もここが正しい置き場所である。
    """
    extras: tuple[str, ...] = ()
    """そのまま str ブロックへ差し込む追加行。"""

    def with_updates(self, **kw: object) -> "PhaseHistogramTerms":
        return replace(self, **kw)  # type: ignore[arg-type]


@dataclass(frozen=True)
class TopasPhase:
    """相 1 つの構造 (``str`` ブロック)。ヒストグラム非依存の部分のみを持つ。"""

    phase_name: str
    space_group: str
    cell: Mapping[str, Param]
    sites: tuple[TopasSite, ...] = ()
    occupancy_sum_groups: tuple[tuple[str, ...], ...] = ()
    """占有率和 = 1 のサイト組 (混合占有)。1 変数 x と 1-x で表す。"""
    beq_equiv_groups: tuple[tuple[str, ...], ...] = ()
    """beq を等値拘束するサイト組。"""
    free_occupancy_labels: tuple[str, ...] = ()
    """占有率を**単独で**解放してよい原子ラベル。

    **全サイトの占有率を一斉に解放してはならない** — 占有率はスケール因子と大域的に縮退する
    ため、Rwp は下がるのに占有率が 1 を超える非物理解へ行ける (実 fluoroapatite で occ 0.68-2.24
    を実測)。GSAS 経路が `PhaseSpec.free_occupancy_labels` / 混合占有サイトに限って解放するのと
    同じ規律で、宣言されたサイトだけを解放する。
    """
    release_occupancy_groups: bool = False
    """占有率の共有 ``prm`` を解放するか。

    **既定 False (=``!`` 付きで固定)** が要点。TOPAS では ``prm name value`` は名前付き =
    **既定で精密化対象**なので、`!` を付けずに宣言すると段階解放を無視して最初の段から
    自由に動いてしまう。すると occupancy 段は「既に自由」なので何も起こらず、
    改善しないまま revert されて**段階解放が効いていないことに気づけない**。
    """
    release_beq_groups: bool = False
    """beq の共有 ``prm`` を解放するか (同上)。"""
    free_cell_keys: tuple[str, ...] = ()
    """**解放してよい**格子キー (対称性から独立なもののみ)。

    TOPAS は空間群から格子を自動拘束しないため、``cell`` には従属軸の参照式
    (``b =Get(a);``) が混ざる。参照式は精密化対象になり得ないので、段階フラグ層は
    格子を解放するときこのキー集合だけを見る。空なら ``cell`` の非参照キー全部を
    解放してよい (後方互換)。
    """
    extras: tuple[str, ...] = ()

    def with_updates(self, **kw: object) -> "TopasPhase":
        return replace(self, **kw)  # type: ignore[arg-type]


@dataclass(frozen=True)
class TopasHistogram:
    """観測ヒストグラム 1 本 (``xdd`` ブロック)。"""

    data_path: str
    preamble: tuple[str, ...] = ()
    """放射・光学系のマクロ行 (``CuKa5(0.001)`` / ``LP_Factor(...)`` 等)。"""
    background: "Param | None" = None
    background_coeffs: int = 6
    two_theta_limits: "tuple[float, float] | None" = None
    excluded_regions: tuple[tuple[float, float], ...] = ()
    weight: float = 1.0
    is_neutron: bool = False
    is_tof: bool = False
    tof_calibration: "Mapping[str, float] | None" = None
    """TOF の ``difc``/``difa``/``zero`` (GSAS の difC/difA/Zero と直写像)。"""
    phase_terms: Mapping[str, PhaseHistogramTerms] = field(default_factory=dict)
    """相名 → HAP 項。"""
    extras: tuple[str, ...] = ()

    def with_updates(self, **kw: object) -> "TopasHistogram":
        return replace(self, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------- 共有 prm の計画


def _shared_prm_plan(
    phases: Sequence[TopasPhase], *, share: bool
) -> "tuple[list[str], dict[tuple[str, str], str]]":
    """joint 用に構造パラメータをトップレベル ``prm`` へ持ち上げる計画を立てる。

    :returns: (prm 宣言行, (相名, キー) → prm 名)
    ``share=False`` (単一ヒストグラム) なら何も持ち上げない — INP が読みやすくなるうえ、
    参照の層が 1 枚減って TOPAS 側の式評価も減る。
    """
    lines: list[str] = []
    mapping: dict[tuple[str, str], str] = {}
    if not share:
        return lines, mapping

    def declare(name: str, param: Param, suffix: str = "") -> None:
        # 【`!` の有無が段階解放】: 名前付き prm は TOPAS では**既定で精密化対象**。`!` を
        #   付けずに宣言すると joint では段階解放を無視して最初の段から全構造が動く
        #   (単一ヒストグラム経路では起きないので実データで気づきにくい)。
        prefix = "" if param.refine else "!"
        lines.append(f"prm {prefix}{name} {_fmt(param.value)}{suffix}")

    for phase in phases:
        stem = _slug(phase.phase_name)
        grouped_occ = {label for group in phase.occupancy_sum_groups for label in group}
        grouped_beq = {label for group in phase.beq_equiv_groups for label in group}
        for axis, param in phase.cell.items():
            if param.is_reference:
                continue
            name = f"{stem}_{axis}"
            mapping[(phase.phase_name, f"cell.{axis}")] = name
            declare(name, param)
        for site in phase.sites:
            label = _slug(site.label)
            for axis, param in (("x", site.x), ("y", site.y), ("z", site.z)):
                if param.is_reference:
                    continue
                name = f"{stem}_{label}_{axis}"
                mapping[(phase.phase_name, f"site.{site.label}.{axis}")] = name
                declare(name, param)
            # 【占有率と beq も持ち上げる】: どちらも**構造**の量なので、どの検出器で測っても
            #   同じでなければならない。持ち上げないと `_site_line` が各 xdd の str ブロック内で
            #   同名を宣言し、TOPAS の大域名前空間で衝突する (scale/TCHZ と同じ罠)。
            #   グループ拘束がある場合は `_group_prm_plan` が既に大域で 1 本にしているので除く。
            if site.label not in grouped_occ and not site.occupancy.is_reference:
                name = f"{stem}_{label}_occ"
                mapping[(phase.phase_name, f"occ.{site.label}")] = name
                declare(name, site.occupancy, suffix=" min 0 max 1")
            if site.label not in grouped_beq and not site.beq.is_reference:
                name = f"{stem}_{label}_beq"
                mapping[(phase.phase_name, f"beq.{site.label}")] = name
                declare(name, site.beq)
    return lines, mapping


def _group_prm_plan(phases: Sequence[TopasPhase]) -> "tuple[list[str], dict[tuple[str, str], str]]":
    """占有率和 = 1 / beq 等値の共有 ``prm`` を計画する (単一ヒストグラムでも必要)。"""
    lines: list[str] = []
    mapping: dict[tuple[str, str], str] = {}
    for phase in phases:
        stem = _slug(phase.phase_name)
        for gi, group in enumerate(phase.occupancy_sum_groups):
            name = f"{stem}_occ_g{gi}"
            seed = 1.0 / max(len(group), 1)
            for site in phase.sites:
                if site.label == group[0]:
                    seed = site.occupancy.value
                    break
            # 【[0,1] 拘束】: 占有率は物理的に区間内。境界外への逸走を TOPAS 側で止める。
            # 【`!` の有無が段階解放】: 名前付き prm は既定で精密化対象なので、解放前は `!`。
            prefix = "" if phase.release_occupancy_groups else "!"
            lines.append(f"prm {prefix}{name} {_fmt(seed)} min 0 max 1")
            for position, label in enumerate(group):
                expr = name if position == 0 else f"1-{name}"
                mapping[(phase.phase_name, f"occ.{label}")] = expr
        for gi, group in enumerate(phase.beq_equiv_groups):
            name = f"{stem}_beq_g{gi}"
            seed = 1.0
            for site in phase.sites:
                if site.label == group[0]:
                    seed = site.beq.value
                    break
            prefix = "" if phase.release_beq_groups else "!"
            lines.append(f"prm {prefix}{name} {_fmt(seed)}")
            for label in group:
                mapping[(phase.phase_name, f"beq.{label}")] = name
    return lines, mapping


# ---------------------------------------------------------------- 文書


@dataclass(frozen=True)
class TopasDocument:
    """INP 文書全体。:meth:`render` が決定論的なテキストを返す。"""

    histograms: tuple[TopasHistogram, ...]
    phases: tuple[TopasPhase, ...]
    max_iterations: int = 1000
    do_errors: bool = True
    results_path: "str | None" = None
    """設定時、``out`` ブロックで r_wp/gof/r_exp と相分率を書き出す (決定論的パース対象)。"""
    preamble: tuple[str, ...] = ()
    """``iters`` の後に差し込む追加の制御行。"""

    # ------------------------------------------------------------ 部品

    def _header(self) -> list[str]:
        # 【r_wp 等を裸で置く】: TOPAS は精密化後に **INP を .out へ書き戻す** 際、これらの
        #   キーワードへ実測値を埋める (T0 実測)。コメントアウトすると値が得られない。
        lines = [
            "' generated by tsumugin (do not edit by hand)",
            "r_p 0 r_wp 0 r_exp 0 gof 0",
            "r_wp_dash 0 r_exp_dash 0",
        ]
        if self.do_errors:
            lines.append("do_errors")
        lines.append(f"iters {int(self.max_iterations)}")
        lines.extend(self.preamble)
        return lines

    def _results_block(self) -> list[str]:
        if not self.results_path:
            return []
        out: list[str] = [f'{_INDENT_HIST}out "{self.results_path}"']
        for key in ("r_wp", "gof", "r_exp", "r_wp_dash"):
            out.append(f'{_INDENT_HIST}Out(Get({key}), "{key}\\t%.8f\\n")')
        return out

    def _site_line(
        self, phase: TopasPhase, site: TopasSite, shared: Mapping[tuple[str, str], str]
    ) -> str:
        stem = f"{_slug(phase.phase_name)}_{_slug(site.label)}"

        def named(param: Param, suffix: str) -> Param:
            """結果出力を要求しているときは名前を付ける (`Out()` から参照するため)。

            無名の ``@`` は ``Out()`` で指せず、精密化した値と esd を回収できない。
            """
            if not self.results_path or param.is_reference or param.name or not param.refine:
                return param
            return replace(param, name=f"{stem}_{suffix}")

        def coord(axis: str, param: Param) -> str:
            name = shared.get((phase.phase_name, f"site.{site.label}.{axis}"))
            if name:
                return render_param(Param.reference(name))
            return render_param(named(param, axis))

        occ_expr = shared.get((phase.phase_name, f"occ.{site.label}"))
        occ = (
            render_param(Param.reference(occ_expr))
            if occ_expr
            else render_param(named(site.occupancy, "occ"))
        )
        beq_name = shared.get((phase.phase_name, f"beq.{site.label}"))
        beq = (
            render_param(Param.reference(beq_name))
            if beq_name
            else render_param(named(site.beq, "beq"))
        )
        return (
            f"{_INDENT_PHASE}site {site.label}"
            f" x {coord('x', site.x)} y {coord('y', site.y)} z {coord('z', site.z)}"
            f" occ {site.element} {occ} beq {beq}"
        )

    def _str_block(
        self,
        phase: TopasPhase,
        terms: PhaseHistogramTerms,
        shared: Mapping[tuple[str, str], str],
        index: int = 0,
    ) -> list[str]:
        lines = [f"{_INDENT_HIST}str"]
        name = phase.phase_name
        # 常に引用する (Tutorial INP の作法。空白や記号を含む相名でも壊れない)。
        lines.append(f'{_INDENT_PHASE}phase_name "{name}"')
        lines.append(f"{_INDENT_PHASE}space_group {phase.space_group}")
        for axis, param in phase.cell.items():
            prm = shared.get((name, f"cell.{axis}"))
            if prm:
                value = render_param(Param.reference(prm))
            else:
                # 【名前を付ける】: 名前付きなら `Out(<name>, …)` で**値と esd**を回収できる。
                #   無名の `@` は Out から参照できず、精密化後セルが取り出せない。
                #   結果出力を要求していないときは付けない (INP を無駄に汚さない)。
                named = (
                    replace(param, name=f"{_slug(name)}_{axis}")
                    if (self.results_path and not param.name)
                    else param
                )
                value = render_param(named)
            lines.append(f"{_INDENT_PHASE}{axis} {value}")
        for site in phase.sites:
            lines.append(self._site_line(phase, site, shared))
        if terms.peak_type:
            # ピーク形状は str ブロック内でなければ TOPAS が解決できない (実測)。
            lines.append(f"{_INDENT_PHASE}{terms.peak_type}")
        scale = terms.scale or Param(1e-4)
        scale_name = f"{_slug(name)}_scale_h{index}"
        if self.results_path and not scale.name:
            # 【名前を付ける】: 無名の `@` は `Out()` から指せない。名前を付けずに Out だけ
            #   書くと TOPAS が ``Uninitialized_Variable`` で異常終了する (実測)。
            # 【ヒストグラム索引を混ぜる】: scale は**相とヒストグラムの組**に属する量
            #   (`PhaseHistogramTerms`)。TOPAS のパラメータ名は大域なので、相名だけで命名すると
            #   joint (X 線+中性子) で 2 本の xdd が同名を宣言し、**別々であるべき scale が
            #   強制的に連結される**。TCHZ (`tchz_line` の tag) と同じ対処。
            scale = replace(scale, name=scale_name)
        lines.append(f"{_INDENT_PHASE}scale {render_param(scale)}")
        if terms.size_lorentzian is not None:
            lines.append(f"{_INDENT_PHASE}CS_L(@, {_fmt(terms.size_lorentzian.value)})")
        if terms.strain_lorentzian is not None:
            lines.append(f"{_INDENT_PHASE}Strain_L(@, {_fmt(terms.strain_lorentzian.value)})")
        if terms.preferred_orientation:
            lines.append(f"{_INDENT_PHASE}{terms.preferred_orientation}")
        # 【相分率】: MVW は質量/体積/**重量分率**を返す。Scale ではなく wt% であることが重要
        #   (KMnFe operando の教訓: 相分率は Scale であって wt% でない — 取り違えると描像が変わる)。
        # 【ヒストグラム索引を混ぜる】: MVW の重量分率は xdd ごとに計算される per-histogram の
        #   出力。相名だけで命名すると joint で 2 本の xdd が同名を宣言して衝突する。
        wt_name = f"mvw_wt_{_slug(name)}_h{index}"
        lines.append(f"{_INDENT_PHASE}MVW(0, 0, {wt_name} 0)")
        # 【出版値は先頭ヒストグラム由来】: 相分率は GSAS 経路も「先頭ヒストグラム」の
        #   契約なので揃える。joint で xdd ごとに同じレコードキーを書くと、パーサ側で
        #   後勝ちになりどちらの値か分からなくなる。
        if self.results_path and index == 0:
            # 【値と esd を 1 行に】: 値側の書式に改行を入れると esd が次行へ落ちる (実測)。
            #   1 レコード 1 行にしておくとパーサが行単位で完結する。
            lines.append(
                f'{_INDENT_PHASE}Out({wt_name}, "wt_frac\\t{name}\\t%.8f", "\\t%.8f\\n")'
            )
            # 【Scale そのものも出す】: `phase_fractions` は **Scale を和=1 に正規化した値**で、
            #   `phase_weight_fractions` (wt%) とは**相互変換できない別量** (model.py の注記:
            #   単位胞質量が相間で違うと乖離し、換算係数は存在しない)。wt% で代用できないので
            #   Scale を独立に回収する。空のままだと相分率の不一致検査が静かに空振りする。
            lines.append(
                f'{_INDENT_PHASE}Out({scale.name or f"{_slug(name)}_scale"}, '
                f'"scale_val\\t{name}\\t%.8f", "\\t%.8f\\n")'
            )
            # 【構造の出版値は先頭ヒストグラムで 1 回だけ】: 構造は全ヒストグラムで共有される
            #   1 つの量なので、xdd ごとに Out すると同じレコードが重複して書かれる。
            if index == 0:
                lines.extend(self._structure_out_lines(phase, shared))
        lines.extend(f"{_INDENT_PHASE}{extra}" for extra in terms.extras)
        lines.extend(f"{_INDENT_PHASE}{extra}" for extra in phase.extras)
        return lines

    def _structure_out_lines(
        self, phase: TopasPhase, shared: Mapping[tuple[str, str], str]
    ) -> list[str]:
        """構造 (セル・座標・占有率・beq) の出版値を ``Out()`` で回収する行。

        **持ち上げた名前も必ず出す**: joint では構造が共有 ``prm`` になるが、出力は同じだけ
        必要である。「持ち上げたから」と skip すると **joint でセルが 1 度も出力されず**
        ``refined_cells``/``cell_esd``/``atom_*`` が静かに空になる (実測)。
        参照式 (従属軸) だけは独立変数から復元できるので出さない。
        """
        lines: list[str] = []
        name = phase.phase_name

        def prm_for(key: str, param: Param, fallback: str) -> "str | None":
            hoisted = shared.get((name, key))
            if hoisted:
                # `1-x` のような式は Out の引数にできない (変数名ではない)。
                return hoisted if hoisted.isidentifier() else None
            return None if param.is_reference else (param.name or fallback)

        for axis, param in phase.cell.items():
            if param.is_reference and not shared.get((name, f"cell.{axis}")):
                continue
            prm = prm_for(f"cell.{axis}", param, f"{_slug(name)}_{axis}")
            if prm:
                lines.append(
                    f'{_INDENT_PHASE}Out({prm}, '
                    f'"cell\\t{name}\\t{axis}\\t%.8f", "\\t%.8f\\n")'
                )
        # 【原子の出版値】: 座標・占有率・beq を esd 付きで回収する。**esd の無い精密化値は
        #   出版できない**うえ、「Rwp は下がったが占有率が非物理」を検出する唯一の手段でもある。
        #   解放していないものは出さない (固定値を「精密化した」と読ませない)。
        for site in phase.sites:
            stem = f"{_slug(name)}_{_slug(site.label)}"
            for axis, param in (("x", site.x), ("y", site.y), ("z", site.z)):
                if not param.refine:
                    continue
                prm = prm_for(f"site.{site.label}.{axis}", param, f"{stem}_{axis}")
                if prm:
                    lines.append(
                        f'{_INDENT_PHASE}Out({prm}, '
                        f'"coord\\t{name}\\t{site.label}\\t{axis}\\t%.8f", "\\t%.8f\\n")'
                    )
            if site.occupancy.refine:
                prm = prm_for(f"occ.{site.label}", site.occupancy, f"{stem}_occ")
                if prm:
                    lines.append(
                        f'{_INDENT_PHASE}Out({prm}, '
                        f'"occ\\t{name}\\t{site.label}\\t%.8f", "\\t%.8f\\n")'
                    )
            if site.beq.refine:
                prm = prm_for(f"beq.{site.label}", site.beq, f"{stem}_beq")
                if prm:
                    lines.append(
                        f'{_INDENT_PHASE}Out({prm}, '
                        f'"beq\\t{name}\\t{site.label}\\t%.8f", "\\t%.8f\\n")'
                    )
        return lines

    def _histogram_block(
        self, index: int, hist: TopasHistogram, shared: Mapping[tuple[str, str], str]
    ) -> list[str]:
        lines: list[str] = []
        if hist.is_tof:
            lines.append(f'TOF_XYE("{hist.data_path}", 0)')
        else:
            lines.append(f'xdd "{hist.data_path}"')
        if hist.is_neutron:
            lines.append(f"{_INDENT_HIST}neutron_data")
        if hist.is_tof and hist.tof_calibration:
            cal = hist.tof_calibration
            lines.append(
                f"{_INDENT_HIST}TOF_x_axis_calibration("
                f"!difc_h{index}, {_fmt(cal.get('difc', 0.0))}, "
                f"!difa_h{index}, {_fmt(cal.get('difa', 0.0))}, "
                f"!t0_h{index}, {_fmt(cal.get('zero', 0.0))})"
            )
        lines.extend(f"{_INDENT_HIST}{line}" for line in hist.preamble)
        if hist.weight != 1.0:
            lines.append(f"{_INDENT_HIST}weighting = {_fmt(hist.weight)};")
        if hist.two_theta_limits is not None:
            low, high = hist.two_theta_limits
            lines.append(f"{_INDENT_HIST}start_X {_fmt(low)}")
            lines.append(f"{_INDENT_HIST}finish_X {_fmt(high)}")
        for low, high in hist.excluded_regions:
            lines.append(f"{_INDENT_HIST}exclude {_fmt(low)} {_fmt(high)}")
        if hist.background is not None:
            coeffs = " ".join(_fmt(hist.background.value) for _ in range(hist.background_coeffs))
            prefix = "@ " if hist.background.refine else ""
            lines.append(f"{_INDENT_HIST}bkg {prefix}{coeffs}")
        lines.extend(f"{_INDENT_HIST}{extra}" for extra in hist.extras)
        # 【結果ブロックは先頭ヒストグラムだけ】: `out "file"` は ``append`` を付けない限り
        #   ファイルを**切り詰めて**開く。xdd ごとに出すと joint で 2 本目が 1 本目の
        #   レコードを消してしまう (r_wp すら残らない)。指標は文書全体で 1 つなので
        #   先頭にだけ置く。
        if index == 0:
            lines.extend(self._results_block())
        for phase in self.phases:
            lines.append("")
            terms = hist.phase_terms.get(phase.phase_name, PhaseHistogramTerms())
            lines.extend(self._str_block(phase, terms, shared, index))
        return lines

    # ------------------------------------------------------------ 公開 API

    def render(self) -> str:
        """INP テキストを決定論的に生成する。"""
        share = len(self.histograms) > 1
        shared_lines, shared = _shared_prm_plan(self.phases, share=share)
        group_lines, group_map = _group_prm_plan(self.phases)
        shared = {**shared, **group_map}
        lines = self._header()
        if shared_lines or group_lines:
            lines.append("")
            lines.extend(shared_lines)
            lines.extend(group_lines)
        for index, hist in enumerate(self.histograms):
            lines.append("")
            lines.extend(self._histogram_block(index, hist, shared))
        return "\n".join(lines) + "\n"

    def with_updates(self, **kw: object) -> "TopasDocument":
        return replace(self, **kw)  # type: ignore[arg-type]
