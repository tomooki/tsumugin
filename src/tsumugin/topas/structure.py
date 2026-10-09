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
from typing import TYPE_CHECKING, NoReturn

from .inp import Param, TopasPhase, TopasSite
from .symmetry import free_coord_axes, snap_to_special_position

if TYPE_CHECKING:  # pragma: no cover
    from ..autorietveld.cif_normalize import Atom, Structure
    from ..autorietveld.model import PhaseSpec

__all__ = [
    "BEQ_PER_UISO",
    "PHASE_SPEC_FIELDS",
    "check_phase_spec_supported",
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


def _site(
    atom: "Atom", symops: "tuple[str, ...]", *, ionic_scattering: bool
) -> TopasSite:
    """1 原子を `TopasSite` へ写す (特殊位置は厳密値へ吸着させる)。"""
    raw = (atom.x, atom.y, atom.z)
    x, y, z = snap_to_special_position(symops, raw)
    return TopasSite(
        label=atom.label,
        element=to_topas_element(atom.type_symbol, ionic=ionic_scattering),
        x=Param(x),
        y=Param(y),
        z=Param(z),
        occupancy=Param(atom.occ),
        beq=Param(atom.uiso * BEQ_PER_UISO),
        # 【自由軸は吸着前の座標で判定する】: 吸着は判定結果を変えないが (同じサイト対称群
        #   から出るので)、判定の入力を吸着後にすると「吸着が自分の判定根拠を作る」循環に
        #   なる。1e-4 の許容差で拾えなかったサイトが吸着で拾えるようになる、という
        #   取りこぼしの隠蔽を避ける。
        free_coord_axes=free_coord_axes(symops, raw),
    )


# ---------------------------------------------------------------- PhaseSpec の相の指定

#: `PhaseSpec` の各フィールドを TOPAS 経路がどう扱うか (**単一の真実源**)。値は (分類, 説明)。
#:
#: - ``honored``: GSAS 経路と同じ意味で INP に写す
#: - ``refused``: 既定値でなければ**精密化の前に** `InvalidPhaseSpecError` で止める
#: - ``unused``: **どのバックエンドも読まない** (TOPAS だけで拒否すると、同じ入力が片方の
#:   エンジンでだけ止まる)
#:
#: **PhaseSpec にフィールドを足したら、ここで分類しない限りテストが落ちる**
#: (`tests/topas/test_phase_spec_fields.py`)。以前の TOPAS 経路は `refine_cell` /
#: `frozen_coord_labels` / `free_uiso_labels` などを一度も参照せず、`backend="topas"` で渡すと
#: 何もせずに完走していた (= 呼べるが黙って間違う)。個別に直しても次に足したフィールドで
#: 再発するので、分類そのものを強制する。③ の手順書 (`skills/analyze`) もこの表と突き合わせる。
PHASE_SPEC_FIELDS: "dict[str, tuple[str, str]]" = {
    "structure_path": ("honored", "CIF を読む"),
    "phase_name": ("honored", "str ブロックの phase_name とパラメータ名の接頭辞"),
    "format_hint": (
        "refused",
        "TOPAS 経路は CIF しか読まない (`read_structure_cif`)。GSAS .EXP 等は CIF にして渡す",
    ),
    "mixed_occupancy_groups": (
        "honored", "2 原子の組だけ (x と 1-x)。beq の等値と座標の結束も張る (GSAS と同じ)",
    ),
    "free_occupancy_labels": ("honored", "占有率段で単独に解放する ([0,1])"),
    "occupancy_equiv_groups": ("honored", "組で 1 つの占有率 (GSAS と同じく [0,1] は張らない)"),
    "free_uiso_labels": ("honored", "None = 全原子 / () = 0 原子 / 列挙 = その原子だけ"),
    "position_equiv_groups": ("honored", "座標のシフトを等値にする (初期の相対位置を保つ)"),
    "occupancy_sum_groups": ("honored", "(親, 子1, …) で 親 = Σ子 ([0,1] は張らない)"),
    "frozen_coord_labels": ("honored", "座標段で解放しない"),
    "refine_cell": ("honored", "False なら格子段でも格子を固定する (#47)"),
    "temperature": (
        "unused",
        "どのバックエンドも読まない (ヒストグラム間の温度差は HistogramSpec.temperature で判定)",
    ),
    "frozen_uiso_labels": ("honored", "uiso 段で解放しない (free_uiso_labels より強い)"),
}


def check_phase_spec_supported(spec: "PhaseSpec") -> None:
    """TOPAS 経路が実装していない相の指定を、**構造ファイルを読む前に**拒否する。

    :raises InvalidPhaseSpecError: ``refused`` に分類したフィールドが既定値でないとき
        (② は error dict へ縮退する)
    """
    from dataclasses import MISSING, fields

    from ..errors import InvalidPhaseSpecError

    defaults = {f.name: f.default for f in fields(spec)}
    used: list[str] = []
    for name, (kind, note) in PHASE_SPEC_FIELDS.items():
        if kind != "refused" or name not in defaults:
            continue
        value, default = getattr(spec, name), defaults[name]
        if default is MISSING:
            continue
        if isinstance(value, str) and isinstance(default, str):
            # 大小と前後の空白は意味を持たない ("cif" も CIF)。
            differs = value.strip().upper() != default.strip().upper()
        else:
            differs = value != default
        if differs:
            used.append(f"`{name}`={value!r} ({note})")
    if used:
        raise InvalidPhaseSpecError(
            f"相 {spec.phase_name!r}: TOPAS バックエンドが実装していない指定です: "
            f"{'; '.join(used)}。黙って別の意味で精密化しないよう止めます。"
            "backend='gsasii' を使うか、指定を外してください"
        )


def _resolve_phase_spec(spec: "PhaseSpec", sites: "tuple[TopasSite, ...]") -> dict:
    """相の指定を検証し、`TopasPhase` のフィールドへ解決する。

    意味を決められない指定は推測で埋めずに止める。**エンジンを問わない規則** (相に無いラベル /
    2 原子以上を指すラベル / 異なる 2 原子に満たない組) は GSAS 経路と同じ関数
    (`autorietveld.model.check_phase_spec_labels`) で検査する。ここに残るのは **TOPAS の INP の
    書き方 (1 原子 = 1 つの式・組 = 1 変数) に起因する**制約で、GSAS 経路には同じ規則を課さない
    (GSAS が意味を決めて張れることを実測したのは占有率拘束の重なりだけ。残りの GSAS での扱いは
    未検証):

    - 3 原子以上の混合占有 (``x, 1-x, 1-x`` は和が 1 にならない)
    - 1 原子が 2 つの占有率拘束に入っている (INP では後に書いた方だけが効く。GSAS は
      equivalence を constraint に変換して全拘束を同時に満たす)
    - 1 変数に束ねた組 (混合占有の beq / 座標の結束) の**一部だけ**を凍結する
    - サイト対称の違う原子どうしの座標の結束 (特殊位置の原子が特殊位置から外れる)

    :raises InvalidPhaseSpecError: 上記のとき
    """
    from ..autorietveld.model import check_phase_spec_labels, resolve_uiso_targets
    from ..errors import InvalidPhaseSpecError

    order = [site.label for site in sites]
    check_phase_spec_labels(spec, order)

    def refuse(message: str) -> NoReturn:
        raise InvalidPhaseSpecError(f"相 {spec.phase_name!r}: {message}")

    groups = {
        "mixed_occupancy_groups": tuple(tuple(g) for g in spec.mixed_occupancy_groups),
        "occupancy_equiv_groups": tuple(tuple(g) for g in spec.occupancy_equiv_groups),
        "occupancy_sum_groups": tuple(tuple(g) for g in spec.occupancy_sum_groups),
        "position_equiv_groups": tuple(tuple(g) for g in spec.position_equiv_groups),
    }
    for group in groups["mixed_occupancy_groups"]:
        if len(group) != 2:
            refuse(
                f"`mixed_occupancy_groups` の組 {list(group)}: TOPAS 経路の混合占有は 2 原子 "
                "(x と 1-x) だけです。3 原子以上に同じ形を当てると x, 1-x, 1-x で和が 1 に"
                "なりません。backend='gsasii' を使ってください"
            )

    owner: dict[str, str] = {}
    for name in ("mixed_occupancy_groups", "occupancy_equiv_groups", "occupancy_sum_groups"):
        for group in groups[name]:
            for label in group:
                if label in owner:
                    # 【GSAS では正しい入力でありうる】: D/H 混合 (`deuterium.place_hd_mix`) は
                    #   親水 O を 2 つの和の組 (O = D1 + H1, O = D2 + H2) に入れ、GSAS は両方を
                    #   同時に満たす。TOPAS 経路の写し方 (1 原子 = 1 つの式) では表せないので、
                    #   「まとめろ」ではなく GSAS で回すよう案内する。
                    refuse(
                        f"原子 {label} の占有率が 2 つの拘束 (`{owner[label]}` と `{name}`) に"
                        "入っています。TOPAS 経路は 1 原子の占有率を 1 つの式でしか書けず、"
                        "INP では後に書いた方だけが効くため止めます。GSAS は両方の拘束を同時に"
                        "満たすので backend='gsasii' を使ってください (D/H 混合 `place_hd_mix` の"
                        "「親水 O が 2 つの和の組に入る」形もこれ)"
                    )
                owner[label] = name

    # 【座標の結束】: GSAS は混合占有の組にも座標 (dAx/dAy/dAz) の等値を張る。等値は推移的
    #   なので、混合占有と position_equiv_groups を連結成分に合併して 1 組 1 変数にする。
    root = {label: label for label in order}

    def find(label: str) -> str:
        while root[label] != label:
            root[label] = root[root[label]]
            label = root[label]
        return label

    for group in (*groups["mixed_occupancy_groups"], *groups["position_equiv_groups"]):
        for label in group[1:]:
            root[find(label)] = find(group[0])
    components: dict[str, list[str]] = {}
    for label in order:  # 組の中の並びはサイト順 (先頭 = 共有座標の初期値の出どころ)
        components.setdefault(find(label), []).append(label)
    by_label = {site.label: site for site in sites}
    frozen_coords = set(spec.frozen_coord_labels)
    position_groups: list[tuple[str, ...]] = []
    for members in components.values():
        if len(members) < 2:
            continue
        axes = {by_label[label].free_coord_axes for label in members}
        if len(axes) > 1:
            detail = {label: by_label[label].free_coord_axes for label in members}
            refuse(
                f"座標を結束する組 {members} のサイト対称が揃っていません (自由軸 {detail})。"
                "結束すると特殊位置の原子が特殊位置から外れるため止めます"
            )
        if not next(iter(axes)):
            continue  # 全員が特殊位置で動かない — 結束する変数が無い
        frozen = [label for label in members if label in frozen_coords]
        if frozen and len(frozen) != len(members):
            refuse(
                f"座標を結束する組 {members} の一部 {frozen} だけが `frozen_coord_labels` に"
                "あります。結束した原子は一緒に動くので一部だけは凍結できません — 組ごと"
                "凍結するか、凍結を外してください"
            )
        position_groups.append(tuple(members))

    # 【Uiso の対象】: GSAS 経路と**同じ関数**で解決する (`model.resolve_uiso_targets`:
    #   None = 全原子 / () = 0 原子 / 列挙 = その原子、凍結が解放指定に勝つ)。何も指定が無いときは
    #   None のまま (従来の INP)。
    beq_release: "tuple[str, ...] | None" = None
    if spec.free_uiso_labels is not None or spec.frozen_uiso_labels:
        targets = set(
            resolve_uiso_targets(order, spec.free_uiso_labels, spec.frozen_uiso_labels)
        )
        beq_release = tuple(label for label in order if label in targets)
        for group in groups["mixed_occupancy_groups"]:
            inside = [label for label in group if label in beq_release]
            if inside and len(inside) != len(group):
                refuse(
                    f"混合占有の組 {list(group)} の beq は 1 変数 (等値拘束) なので、一部 {inside} "
                    "だけは解放できません。`free_uiso_labels` / `frozen_uiso_labels` に組の全員を"
                    "入れるか、全員を外してください"
                )

    return {
        "mixed_occupancy_groups": groups["mixed_occupancy_groups"],
        # 【混合占有には Uiso 等価も張る】: 同一サイトを分け合う原子は同じ熱振動をする。
        #   GSAS 経路が add_EqnConstr と add_EquivConstr を対で張るのと同じ (M7 T2 の教訓)。
        "beq_equiv_groups": groups["mixed_occupancy_groups"],
        "free_occupancy_labels": tuple(spec.free_occupancy_labels),
        "occupancy_equiv_groups": groups["occupancy_equiv_groups"],
        "occupancy_parent_sum_groups": groups["occupancy_sum_groups"],
        "position_groups": tuple(position_groups),
        "refine_cell": bool(spec.refine_cell),
        "frozen_coord_labels": tuple(spec.frozen_coord_labels),
        "beq_release_labels": beq_release,
    }


def structure_to_topas_phase(
    structure: "Structure",
    phase_name: str,
    *,
    spec: "PhaseSpec | None" = None,
    ionic_scattering: bool = False,
    symops: "tuple[str, ...] | None" = None,
) -> TopasPhase:
    """`Structure` を `TopasPhase` へ写像する。

    **何も解放しない状態**で返す (すべて固定)。どのパラメータを解放するかは段階フラグ
    (`topas.flags`) の責務であり、構造の読み込みと解放戦略を混ぜない。

    :param spec: `PhaseSpec` があれば相の指定 (拘束・凍結) を引き継ぐ。扱いはフィールドごとに
        :data:`PHASE_SPEC_FIELDS` が決める。
    :param symops: 対称操作の上書き。CIF が対称操作を持たないとき、呼び出し側 (engine) が
        TOPAS の ``Sg/`` から補完したものを渡す。**本関数自体は純粋なまま**にするため、
        tc.exe を起動する補完はここでは行わない (`topas.symmetry.ensure_symops` の責務)。
    :raises InvalidPhaseSpecError: 原子ラベルが重複しているとき (共有 ``prm`` 名が衝突して
        **別サイトが黙って結合される**)、または相の指定の意味を決められないとき
        (`_resolve_phase_spec`)。``ValueError`` を継ぐので従来の捕まえ方とも互換。
    """
    from ..errors import InvalidPhaseSpecError

    if spec is not None:
        # engine は構造を読む前に同じ検査をする (読めない形式で読みに行かないため)。ここでも
        # 呼ぶのは engine を経ずに本関数を使う呼び手のため — 拒否したフィールドが黙って
        # 素通りする入口を作らない。
        check_phase_spec_supported(spec)
    labels = [atom.label for atom in structure.atoms]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise InvalidPhaseSpecError(
            f"原子ラベルが重複しています: {duplicates}。TOPAS の共有パラメータ名が衝突し "
            f"別サイトが黙って結合されるため、CIF 側でラベルを一意にしてください。"
        )

    system = crystal_system(structure.it_number, structure.spacegroup_hm)
    cell, free_cell_keys = _cell_block(structure, system)

    # 【サイト対称】: 特殊位置の座標を解放すると対称性が壊れる (しかも Rwp は下がりうるので
    #   静かに間違った構造へ行き着く)。GSAS の GetCSxinel に相当する判定を対称操作から行う。
    #
    # 【特殊位置は厳密値へ吸着させる】: TOPAS は多重度を座標の一致で決め、許容差は約 1e-8。
    #   CIF の 5-8 桁では 1/3 が届かず、4f サイトが一般位置 (多重度 12) へ化けて**単位胞に
    #   存在しない原子が増えたまま完走する** (実 fluoroapatite で cell_mass 1008.6 → 1329.2)。
    #   ピーク位置は正しいままなので Rwp を見ても原因に辿り着けない (#172)。
    effective_symops = symops if symops is not None else structure.symops
    sites = tuple(
        _site(atom, effective_symops, ionic_scattering=ionic_scattering)
        for atom in structure.atoms
    )
    resolved = _resolve_phase_spec(spec, sites) if spec is not None else {}

    return TopasPhase(
        phase_name=phase_name,
        space_group=to_topas_spacegroup(structure.spacegroup_hm, structure.it_number),
        cell=cell,
        sites=sites,
        free_cell_keys=free_cell_keys,
        **resolved,
    )
