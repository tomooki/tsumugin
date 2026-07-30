"""構造 (CIF) → TOPAS ``str`` ブロック (M12 T3) — 純関数。

読み取りは `autorietveld.cif_normalize.read_structure_cif` を再利用する (pymatgen を
引き込まない numpy 非依存の CIF パーサ)。本モジュールはその `Structure` を
`topas.inp.TopasPhase` へ写像する。

**【TOPAS は空間群から格子を自動拘束しない】** (実測): ``topas.inc`` の ``Cubic(cv)`` は
``a cv b = Get(a); c = Get(a);`` と**明示展開**する。つまり a/b/c を素直に 3 本並べて
精密化フラグを立てると、立方晶でも 3 軸が独立に動いて対称性が壊れる。GSAS-II の
``set_refinements({"Cell": True})`` が空間群を見て自動で拘束するのとは**逆**なので、
結晶系ごとの拘束をこちら側で張る。

**単位の違い**: CIF/GSAS は Uiso、TOPAS は B (``beq``)。``B = 8π²·Uiso``。
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from .inp import Param, TopasPhase, TopasSite

if TYPE_CHECKING:  # pragma: no cover
    from ..autorietveld.cif_normalize import Structure
    from ..autorietveld.model import PhaseSpec

__all__ = [
    "BEQ_PER_UISO",
    "crystal_system",
    "structure_to_topas_phase",
    "to_topas_element",
    "to_topas_spacegroup",
]

BEQ_PER_UISO: float = 8.0 * math.pi**2
"""B = 8π²·Uiso (TOPAS の beq と CIF/GSAS の Uiso の換算係数)。"""

_ANGLE_KEYS = ("al", "be", "ga")

_CIF_ION = re.compile(r"^([A-Za-z]{1,2})(\d*)([+-])$")


def to_topas_spacegroup(hm_symbol: "str | None", it_number: "int | None") -> str:
    """空間群を TOPAS の ``space_group`` 値へ写像する。

    TOPAS は**空白を除いた H-M 記号** (``Pnma`` / ``Fm-3m`` / ``P21/n``) と **IT 番号**
    (``62``) のどちらも受け付ける (Tutorial INP に両方の実例あり)。H-M を優先するのは
    **非標準セッティングを保つ**ため — 番号だけを渡すと ``P21/n`` が標準の ``P21/c`` として
    生成され、原子座標と対称操作が食い違って消滅則が崩れる (M9 Jana→CIF の教訓と同型)。

    :raises ValueError: 記号も番号も無いとき。**黙って P1 に落とさない** — 対称性の
        取り違えは Rwp に現れないまま構造を壊すため、ここで気づかせる。
    """
    if hm_symbol:
        collapsed = re.sub(r"\s+", "", hm_symbol).strip()
        if collapsed:
            return collapsed
    if it_number is not None:
        return str(int(it_number))
    raise ValueError(
        "空間群を決定できません (H-M 記号も IT 番号も CIF にありません)。"
        "対称性の取り違えは Rwp に現れないため P1 への既定化は行いません。"
    )


def to_topas_element(cif_symbol: str, *, ionic: bool = False) -> str:
    """CIF の ``_atom_site_type_symbol`` を TOPAS の散乱種名へ写像する。

    既定は**中性原子** (``Pb2+`` → ``Pb``)。中性種は TOPAS の散乱表に必ず存在するため、
    未知のイオン種で ``tc.exe`` が落ちる事故を避けられる。``ionic=True`` を渡すと
    CIF の ``Pb2+`` を TOPAS の順序 ``Pb+2`` へ並べ替えて用いる (X 線でイオン散乱因子を
    使いたい場合の opt-in; TOPAS が知らないイオン種なら**明示的に失敗する**)。
    """
    token = (cif_symbol or "").strip()
    match = _CIF_ION.match(token)
    if match is None:
        return token
    element, digits, sign = match.groups()
    if not ionic:
        return element
    return f"{element}{sign}{digits or '1'}"


_HM_TOKEN = re.compile(r"-?\d+(?:/[a-zA-Z])?|[a-zA-Z]")


def _system_from_hm(hm_symbol: str) -> "str | None":
    """H-M 記号から結晶系を推定する (IT 番号が無い CIF 向け)。

    記号を「格子文字 + 対称方向の並び」と見て判定する。要は **3 が 2 番目の方向に来れば
    立方晶、先頭なら三方晶**という古典的な読み方:

    ``Fm-3m`` → ``m|-3|m`` 立方 / ``R-3c`` → ``-3|c`` 三方 / ``P63/m`` → 六方
    """
    raw = (hm_symbol or "").strip()
    if not raw:
        return None
    # 【空白は方向の区切り】: CIF の H-M は `P 2 2 2` のように方向を空白で区切る。先に
    #   詰めてしまうと `222` が 1 トークン (=2₂₂ の螺旋軸?) と読めてしまい方向数を誤る。
    #   空白があるうちに割るのが最も確実で、無い場合だけ字面から推測する。
    if re.search(r"\s", raw):
        parts = raw.split()
        body_tokens = parts[1:] if parts[0][0] in "PABCIFRH" and len(parts[0]) == 1 else parts
        if parts[0][0] in "PABCIFRH" and len(parts[0]) > 1:
            body_tokens = [parts[0][1:], *parts[1:]]
        tokens = [t for t in body_tokens if t]
    else:
        body = raw[1:] if raw[0] in "PABCIFRH" else raw
        if not body:
            return None
        tokens = _HM_TOKEN.findall(body)
    # 末尾/中間の "1" は方向の placeholder (P3121 の 1 など) なので方向数から除く。
    directions = [t for t in tokens if t not in ("1",)]
    if not directions:
        return "triclinic"
    if directions[0] in ("-1",) or (len(directions) == 1 and directions[0] == "-1"):
        return "triclinic"
    joined = "".join(directions)
    if "6" in joined:
        return "hexagonal"
    threes = [i for i, t in enumerate(directions) if t.lstrip("-").startswith("3")]
    if threes:
        # 先頭方向が 3/-3 なら三方晶、そうでなければ (= 2 番目の方向) 立方晶。
        return "trigonal" if threes[0] == 0 else "cubic"
    if "4" in joined:
        return "tetragonal"
    if len(directions) >= 3:
        return "orthorhombic"
    return "monoclinic"


def crystal_system(it_number: "int | None", hm_symbol: "str | None" = None) -> str:
    """結晶系を返す。IT 番号を最優先し、無ければ H-M 記号から推定する。

    **【緩い拘束は安全ではない】**: 実 CIF は IT 番号を持たないことが多い
    (``docs/benchmark/testdata/PbSO4-Wyckoff.cif`` がそう)。番号が無いからと triclinic に
    落とすと、直方晶の 90° 角を 3 本とも解放してしまう。90° 近傍では角度方向の微分がほぼ 0 に
    なるためヘッシアンが特異になり最小二乗が失敗する — CLAUDE.md に記録された CaTeO3 の
    「P1 展開で角 3 つを解放 → 特異ヘッシアン → Refine 失敗」と同じ病理である。
    """
    if it_number is not None:
        number = int(it_number)
        if number <= 2:
            return "triclinic"
        if number <= 15:
            return "monoclinic"
        if number <= 74:
            return "orthorhombic"
        if number <= 142:
            return "tetragonal"
        if number <= 167:
            return "trigonal"
        if number <= 194:
            return "hexagonal"
        return "cubic"
    return _system_from_hm(hm_symbol or "") or "triclinic"


def _is_special_angle(value: float, tol: float = 1e-6) -> bool:
    """90° / 120° ちょうどか (対称性由来の固定角とみなす)。"""
    return abs(value - 90.0) <= tol or abs(value - 120.0) <= tol


def _cell_block(
    structure: "Structure", system: str
) -> "tuple[dict[str, Param], tuple[str, ...]]":
    """結晶系に応じた格子ブロックと**解放してよいキー**を返す。

    従属軸は ``=Get(a);`` の参照式にする (topas.inc の Cubic/Tetragonal/Hexagonal マクロが
    展開するのと同じ形)。参照式のパラメータは精密化対象になり得ないので、
    ``free_cell_keys`` に載せない。
    """
    a, b, c = structure.a, structure.b, structure.c
    al, be, ga = structure.alpha, structure.beta, structure.gamma
    ref_a = Param.reference("Get(a)")

    if system == "cubic":
        return {"a": Param(a), "b": ref_a, "c": ref_a}, ("a",)
    if system == "tetragonal":
        return {"a": Param(a), "b": ref_a, "c": Param(c)}, ("a", "c")
    if system in ("hexagonal", "trigonal"):
        # 【菱面体軸か六方軸か】: γ≈120 なら六方軸 (a=b, γ=120)。そうでなく a≈b≈c かつ
        #   α≈β≈γ≠90 なら菱面体軸 (a=b=c, α=β=γ)。R 空間群は両方の記述があり得る。
        if abs(ga - 120.0) > 1.0 and abs(al - 90.0) > 1.0 and abs(a - c) < 1e-3:
            return (
                {
                    "a": Param(a),
                    "b": ref_a,
                    "c": ref_a,
                    "al": Param(al),
                    "be": Param.reference("Get(al)"),
                    "ga": Param.reference("Get(al)"),
                },
                ("a", "al"),
            )
        return {"a": Param(a), "b": ref_a, "c": Param(c), "ga": Param(120.0)}, ("a", "c")
    if system == "orthorhombic":
        return {"a": Param(a), "b": Param(b), "c": Param(c)}, ("a", "b", "c")
    if system == "monoclinic":
        cell = {"a": Param(a), "b": Param(b), "c": Param(c)}
        free = ["a", "b", "c"]
        # 【一意軸】: b 軸設定 (β≠90) が標準だが c 軸設定 (γ≠90) の CIF もある。
        #   90° から外れている角だけを解放対象にし、残りは 90° に固定する。
        for key, value in zip(_ANGLE_KEYS, (al, be, ga)):
            cell[key] = Param(value)
            if abs(value - 90.0) > 1e-6:
                free.append(key)
        if len(free) == 3:  # すべて 90° — 記述上は直方だが空間群は単斜。β を一意軸とみなす
            free.append("be")
        return cell, tuple(free)
    # triclinic (または系が不明): 角は**特殊値ちょうどなら解放しない**。
    # 90°/120° 近傍では角度方向の微分がほぼ 0 でヘッシアンが特異になり最小二乗が落ちる。
    # 系が推定できなかったときの最後の安全網 (CaTeO3 P1 展開の病理と同型)。
    cell = {"a": Param(a), "b": Param(b), "c": Param(c)}
    free = ["a", "b", "c"]
    for key, value in zip(_ANGLE_KEYS, (al, be, ga)):
        cell[key] = Param(value)
        if not _is_special_angle(value):
            free.append(key)
    return cell, tuple(free)


def structure_to_topas_phase(
    structure: "Structure",
    phase_name: str,
    *,
    spec: "PhaseSpec | None" = None,
    ionic_scattering: bool = False,
) -> TopasPhase:
    """`Structure` を `TopasPhase` へ写像する。

    **何も解放しない状態**で返す (すべて固定)。どのパラメータを解放するかは段階フラグ
    (`topas.flags`) の責務であり、構造の読み込みと解放戦略を混ぜない。

    :param spec: `PhaseSpec` があれば混合占有/等値の宣言を拘束として引き継ぐ。
    :raises ValueError: 原子ラベルが重複しているとき。共有 ``prm`` 名が衝突して
        **別サイトが黙って結合される**ため、ここで弾く。
    """
    labels = [atom.label for atom in structure.atoms]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(
            f"原子ラベルが重複しています: {duplicates}。TOPAS の共有パラメータ名が衝突し "
            f"別サイトが黙って結合されるため、CIF 側でラベルを一意にしてください。"
        )

    system = crystal_system(structure.it_number, structure.spacegroup_hm)
    cell, free_cell_keys = _cell_block(structure, system)

    sites = tuple(
        TopasSite(
            label=atom.label,
            element=to_topas_element(atom.type_symbol, ionic=ionic_scattering),
            x=Param(atom.x),
            y=Param(atom.y),
            z=Param(atom.z),
            occupancy=Param(atom.occ),
            beq=Param(atom.uiso * BEQ_PER_UISO),
        )
        for atom in structure.atoms
    )

    occupancy_sum_groups: tuple[tuple[str, ...], ...] = ()
    beq_equiv_groups: tuple[tuple[str, ...], ...] = ()
    if spec is not None:
        occupancy_sum_groups = tuple(tuple(g) for g in spec.mixed_occupancy_groups)
        occupancy_sum_groups += tuple(tuple(g) for g in spec.occupancy_sum_groups)
        # 【混合占有には Uiso 等価も張る】: 同一サイトを分け合う原子は同じ熱振動をする。
        #   GSAS 経路が add_EqnConstr と add_EquivConstr を対で張るのと同じ (M7 T2 の教訓)。
        beq_equiv_groups = tuple(tuple(g) for g in spec.mixed_occupancy_groups)

    return TopasPhase(
        phase_name=phase_name,
        space_group=to_topas_spacegroup(structure.spacegroup_hm, structure.it_number),
        cell=cell,
        sites=sites,
        occupancy_sum_groups=occupancy_sum_groups,
        beq_equiv_groups=beq_equiv_groups,
        free_cell_keys=free_cell_keys,
    )
