"""段階解放レシピ生成 (M7 自動 Rietveld アルゴリズム中核, 成果物1)。

GSAS-II チュートリアル T1–T4 の手順を一般化した普遍段階列に、ジオメトリ・温度差・多相・
混合占有のアダプタを適用して RefinementStage 列を生成する。純関数 (GSAS 非依存) のため
ユニットテスト可能で、engine 層がこの宣言的フラグを GSAS-II 呼び出しへ翻訳する。

**フラグ語彙 (engine が解釈する正準キー)**:
- ``background``: {"coeffs": N} — プロジェクト背景係数の解放
- ``scale``: True — 相分率スケールの解放
- ``cell``: True — 全相の単位胞
- ``displacement``: {hist_index: [GSAS Sample Parameters キー]} — ジオメトリ別試料変位
- ``profile``: ["U","V","W"] — Gaussian プロファイル係数
- ``profile_lorentzian``: True — X 線 Lorentzian X,Y + Zero の追加解放 (別段階, revert ガード)
- ``size_strain``: True — 結晶子サイズ + 微小歪み (HAP)
- ``coords``: True — 原子座標 X。int なら「重い方から int 番目の元素だけ」、
  ``"heavy_first"`` なら**engine が実元素数に応じて展開する宣言** (REQ-SAR-303)
- ``uiso``: True — 等方温度因子 U。``"shared"``/``"by_element"`` は Uiso 等値拘束の段階
  (REQ-SAR-305; engine が ``add_EquivConstr`` を張る)
- ``occupancy``: True — 混合占有サイトの占有率 (制約下)。``coords`` と同じランク/宣言を取る
- ``phase_fraction_sum``: True — 多相の相分率和=1 制約
- ``hydrostatic_strain``: True — ヒストグラム間温度差の静水圧歪み Dij
- ``freeze_others``: True | [名前…] — 段の適用**前**に既存の解放を落とす (名前の列を渡すと
  それらは凍結しない)。省略時は従来どおり**累積 (enable のみ)**

信頼性: 🔵 チュートリアル手順 (PLAN §4) + T1 プロトタイプ進行の一般化。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .model import Geometry, HistogramSpec, PhaseSpec, RefinementStage

# ---------------------------------------------------------------------------
# 相関群 (REQ-SAR-301) — 分割してはならないパラメータ集合
# ---------------------------------------------------------------------------
#: **分割不能な相関群** (論理名 → 正準の累積順メンバ)。
#:
#: これらは「独立に回せる knob が複数ある」のではなく、**1 つの物理量を張る係数の組**である。
#: 例えば Caglioti の U,V,W は FWHM² = U·tan²θ + V·tanθ + W の係数なので、1 つだけ解放して
#: 残りを凍結すると、その 1 つが担当できない角度依存まで背負わされて解が壊れる。
#: 実測 (CaTeO3): 「W 単独 → 凍結 → U 単独 → 凍結 → V 単独」は U 段と V 段が**両方 revert**
#: して 18.07% で頭打ち。W から**足していく** (W → W,U → W,U,V) と 12.19% まで落ちた
#: (requirements.md F2)。
#:
#: したがって規則は「群を丸ごと足すのは可、**縮めるのは不可**」— 詳細は
#: `validate_correlation_groups`。試料変位は幾何ごとに別群 (Bragg-Brentano と Debye-Scherrer で
#: パラメータが違う) なので ``displacement:<幾何>`` として分けて持つ。
#:
#: ⚠ 本表は**唯一の出所**である: `_GEOMETRY_DISPLACEMENT` もここから導出する。新しく解放する
#: 装置パラメータ (例 Bragg-Brentano の ``Transparency``) を足すときは、単独で段に足すのではなく
#: **所属する群へ足す** — 群に無いパラメータは「分割禁止」の網に掛からない。
CORRELATION_GROUPS: dict[str, tuple[str, ...]] = {
    # Caglioti ガウス幅: FWHM² = U·tan²θ + V·tanθ + W
    "gaussian_profile": ("W", "U", "V"),
    # Lorentzian 幅: X/cosθ + Y·tanθ (engine は profile_lorentzian 段で Zero と一緒に解放する)
    "lorentzian_profile": ("X", "Y"),
    # 結晶子サイズと微小歪みは同じピーク幅を角度依存の違いだけで分け合う (engine は常に同時解放)
    "size_strain": ("Size", "Mustrain"),
    # 格子定数は GSAS が対称性拘束下で一括解放する (a,b,c,α,β,γ を分けられない)
    "cell": ("cell",),
    # 試料変位 (2θ の系統オフセット)。幾何ごとにパラメータが異なるため別群にする
    "displacement:bragg_brentano": ("Shift",),
    "displacement:debye_scherrer": ("DisplaceX", "DisplaceY"),
}

#: 幾何 → その幾何の試料変位群 (`CORRELATION_GROUPS` から導出。ここで手書きしない)。
_GEOMETRY_DISPLACEMENT: dict[Geometry, list[str]] = {
    Geometry.BRAGG_BRENTANO: list(CORRELATION_GROUPS["displacement:bragg_brentano"]),
    Geometry.DEBYE_SCHERRER: list(CORRELATION_GROUPS["displacement:debye_scherrer"]),
}

#: 変位フラグに現れてよい「完全な」キー集合 (どれか 1 つと**厳密一致**していること)。
_DISPLACEMENT_GROUPS: dict[str, frozenset[str]] = {
    name: frozenset(members)
    for name, members in CORRELATION_GROUPS.items()
    if name.startswith("displacement:")
}


class CorrelationGroupViolation(ValueError):
    """相関群 (REQ-SAR-301) を分割した段を検出したときに送出する。

    レシピ生成側で送出することで、**群を割る段を書けてしまう**こと自体を防ぐ
    (engine まで届いてから実測で気づくのでは遅い — 割れた段は revert として現れるだけで、
    原因がパラメータ群の分割であることは Rwp からは読めない)。
    """


def released_group_members(flags: Mapping[str, object], group: str) -> frozenset[str]:
    """段のフラグ ``flags`` が **その段で解放する** ``group`` のメンバ集合を返す。

    engine (`_apply_stage`) の解釈をそのまま写す:

    - ``profile`` はキー列ならその集合、それ以外 (True/未指定値) なら CW 既定 U,V,W
    - ``profile_lorentzian`` は X,Y (+Zero) を一括解放する真偽フラグ
    - ``size_strain`` は Size と Mustrain を常に**同時に**張る (値は mustrain の型)
    - ``cell`` は ``True`` のときだけ解放 (``False`` は凍結なので解放ではない)
    - ``displacement`` はヒストグラム毎のキー列 (完全性は `validate_correlation_groups` が別途検査)

    :raises KeyError: 未知の群名
    """
    members = frozenset(CORRELATION_GROUPS[group])
    if group == "gaussian_profile":
        if "profile" not in flags:
            return frozenset()
        value = flags["profile"]
        if isinstance(value, (list, tuple, set, frozenset)):
            return frozenset(value) & members
        return members  # True/その他 → engine 既定キー (CW: U,V,W)
    if group == "lorentzian_profile":
        out: set[str] = set()
        value = flags.get("profile")
        if isinstance(value, (list, tuple, set, frozenset)):
            out |= set(value) & members
        if flags.get("profile_lorentzian"):
            out |= set(members)
        return frozenset(out)
    if group == "size_strain":
        return members if flags.get("size_strain") else frozenset()
    if group == "cell":
        return members if flags.get("cell") is True else frozenset()
    if group in _DISPLACEMENT_GROUPS:
        mapping = flags.get("displacement") or {}
        if not isinstance(mapping, Mapping):
            return frozenset()
        for keys in mapping.values():
            if isinstance(keys, (list, tuple, set, frozenset)) and (set(keys) & members):
                return members
        return frozenset()
    return frozenset()


def _validate_displacement_stage(
    stage: RefinementStage, histograms: Sequence[HistogramSpec] | None
) -> None:
    """変位段のキー列が**宣言された幾何群と厳密一致**することを確かめる。

    ``{0: ["DisplaceX"]}`` のような取りこぼしを個別に検出したい (累積規則だけだと
    「最後まで DisplaceY が来ない」という遠い場所のエラーになり原因が読めない)。
    """
    mapping = stage.flags.get("displacement")
    if not isinstance(mapping, Mapping):
        return
    known = {name: sorted(members) for name, members in _DISPLACEMENT_GROUPS.items()}
    for index, keys in mapping.items():
        actual = frozenset(keys) if isinstance(keys, (list, tuple, set, frozenset)) else frozenset()
        if actual not in _DISPLACEMENT_GROUPS.values():
            raise CorrelationGroupViolation(
                f"試料変位の群を分割しています: 段 {stage.label!r} のヒストグラム {index} が "
                f"{sorted(actual)} を解放していますが、これは宣言された幾何群 {known} の"
                "いずれとも一致しません。変位キーは幾何ごとに丸ごと解放すること "
                "(`_displacement_map` を使う)"
            )
        if histograms is not None and isinstance(index, int) and 0 <= index < len(histograms):
            geometry = histograms[index].geometry
            expected = frozenset(_GEOMETRY_DISPLACEMENT[geometry])
            if actual != expected:
                raise CorrelationGroupViolation(
                    f"段 {stage.label!r} のヒストグラム {index} の変位キー {sorted(actual)} が"
                    f"幾何 {geometry} の群 {sorted(expected)} と一致しません"
                )


def validate_correlation_groups(
    stages: Sequence[RefinementStage],
    *,
    histograms: Sequence[HistogramSpec] | None = None,
) -> None:
    """段列が相関群を分割していないことを検証する (REQ-SAR-301)。

    **規則は 2 つだけ**:

    1. **縮めない** — ある群を部分的に解放した段の後、その群を次に触る段は
       **前の段のメンバをすべて含む**こと。``W`` → ``W,U`` → ``W,U,V`` の累積は可、
       ``W`` → ``U`` (前の W を落として U へ乗り換える) は不可。
       群を丸ごと解放し切ったらカウンタはリセットされるので、"本気フィット" のように
       周回ごとに ``W`` から積み直すのは可。
    2. **やり残さない** — 段列の最後まで部分解放のままの群があってはならない
       (「W だけ解放して終わり」は V,U が永久に凍結された誤ったフィット)。

    ``freeze_others`` による凍結は規則 1 のリセットに**ならない**: 凍結を挟んで別のメンバへ
    乗り換える手順こそが F2 で壊れた当のパターンだからである。

    :param stages: 検証する段列
    :param histograms: 与えると変位キーを各ヒストグラムの幾何と突き合わせる (省略可)
    :raises CorrelationGroupViolation: 群を分割している段があるとき
    """
    #: 群 → まだ完結していない部分解放集合 (空集合 = 完結済み / 未着手)
    pending: dict[str, frozenset[str]] = {}
    for stage in stages:
        _validate_displacement_stage(stage, histograms)
        for group, full in CORRELATION_GROUPS.items():
            released = released_group_members(stage.flags, group)
            if not released:
                continue
            previous = pending.get(group) or frozenset()
            if previous and not previous <= released:
                raise CorrelationGroupViolation(
                    f"相関群 {group!r} を分割しています: 段 {stage.label!r} は "
                    f"{sorted(released)} を解放しますが、直前にこの群を触った段は "
                    f"{sorted(previous)} を解放していました。群のメンバは**累積して足す**こと "
                    f"(正準順 {list(full)}: W → W,U → W,U,V)。1 つずつ解放/凍結すると "
                    "1 つの物理量の係数が独立に動き、段が両方 revert する "
                    "(CaTeO3 実測 18.07% vs 累積 12.19%)"
                )
            pending[group] = frozenset() if released >= frozenset(full) else released
    unfinished = {group: rest for group, rest in pending.items() if rest}
    if unfinished:
        detail = "; ".join(
            f"{group}: {sorted(rest)} だけ解放され "
            f"{sorted(set(CORRELATION_GROUPS[group]) - rest)} が未解放"
            for group, rest in sorted(unfinished.items())
        )
        raise CorrelationGroupViolation(
            f"相関群が部分解放のまま段列が終わっています ({detail})。"
            "群は最後に必ず丸ごと解放すること — 一部だけ凍結された解は物理的に誤りである"
        )


def _finalize(
    stages: Sequence[RefinementStage], histograms: Sequence[HistogramSpec]
) -> tuple[RefinementStage, ...]:
    """段列に S 番号を振り、**相関群の不変条件を検証してから**返す。

    レシピ生成の唯一の出口にすることで、「群を割る段を作れてしまう」経路を塞ぐ
    (新しいレシピを足しても検証を通らなければ生成時点で失敗する)。
    """
    numbered = tuple(
        RefinementStage(label=f"S{i} {s.label}", flags=s.flags, note=s.note)
        for i, s in enumerate(stages)
    )
    validate_correlation_groups(numbered, histograms=histograms)
    return numbered


def _displacement_map(histograms: Sequence[HistogramSpec]) -> dict[int, list[str]]:
    """各ヒストグラムのジオメトリから試料変位パラメータ集合を決める (REQ-101)。"""
    return {
        i: list(_GEOMETRY_DISPLACEMENT[h.geometry])
        for i, h in enumerate(histograms)
    }


def _has_temperature_difference(histograms: Sequence[HistogramSpec]) -> bool:
    """測定温度が複数ヒストグラム間で異なるか (REQ-103)。"""
    temps = [h.temperature for h in histograms if h.temperature is not None]
    return len(temps) >= 2 and (max(temps) - min(temps) > 1e-9)


def build_recipe(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    background_coeffs: int = 6,
) -> tuple[RefinementStage, ...]:
    """普遍段階列 + アダプタから段階解放レシピを生成する。

    :param histograms: 観測ヒストグラム仕様 (1 本以上)
    :param phases: 相仕様 (1 つ以上)
    :param background_coeffs: 初期背景 (Chebyshev) 係数数
    :returns: RefinementStage の順序付きタプル
    """
    if not histograms:
        raise ValueError("histograms が空です")
    if not phases:
        raise ValueError("phases が空です")

    multiphase = len(phases) > 1
    mixed_occ = any(
        p.mixed_occupancy_groups or p.free_occupancy_labels
        or p.occupancy_equiv_groups or p.occupancy_sum_groups
        for p in phases
    )
    temp_diff = _has_temperature_difference(histograms)
    has_xray = any(not h.radiation.is_neutron for h in histograms)
    disp = _displacement_map(histograms)

    profile_stage = RefinementStage(
        label="profile+size_strain",
        flags={"profile": ["U", "V", "W"], "size_strain": True},
        note="プロファイル係数 + 結晶子サイズ/微小歪み",
    )
    # X 線は Lorentzian (X,Y) + Zero を別段階で追加解放する (実験室/放射光は Lorentzian 支配的;
    # U,V,W のみでは実測ピーク形状に合わず高止まり — CaTeO3 実測 43%→13%)。悪化時は本段階ごと
    # revert され U,V,W は保持 (T3/T4 非回帰)。中性子/TOF は engine 側でスキップ。
    lorentzian_stage = RefinementStage(
        label="profile_lorentzian",
        flags={"profile_lorentzian": True},
        note="X 線 Lorentzian X,Y + Zero (別段階, revert ガード)",
    )
    # 軸発散非対称 SH/L (分割擬フォークト相当の経験的ピーク形状)。X,Y,Zero とは別段階にし常に
    # 改善する訳ではないため悪化時は本段のみ revert (CaTeO3 frame0 で X,Y,Zero と同段だと 13.4→16.3 に劣化)。
    asymmetry_stage = RefinementStage(
        label="profile_asymmetry",
        flags={"profile_asymmetry": True},
        note="X 線 軸発散非対称 SH/L (別段階, revert ガード)",
    )
    coords_stage = RefinementStage(
        label="coords", flags={"coords": True}, note="一般位置の原子座標 X"
    )
    uiso_stage = RefinementStage(
        label="uiso", flags={"uiso": True}, note="等方温度因子 Uiso (混合占有は等価制約下)"
    )

    # 【段順序の実験と差し戻し (2026-07-27/28)】
    #   「格子は単独 → 試料変位は後段」を規定として 3 通り (末尾 / cell 直後 / cell→変位→cell の
    #   交互) 実装し実データで測ったが、**どの配置でも 1 つ以上のベンチマークが落ちた**:
    #     - 末尾・交互      : T3 PbSO4 joint 6.66% → 14.38% (格子発散)
    #     - cell 直後       : T4 NAC+CaF2 ~12.8% → 17.53%
    #   格子と試料変位が強相関なのは事実 (実測: Kα1 単色 CaTeO3 で Shift −274 µm 相当 = 2θ
    #   −0.15° を格子が肩代わりしていた) だが、**単一の段順序で全データを満たすことはできない**。
    #   よって既定は M7 の実績ある「格子 + 変位 同段」に戻し、順序の選択は Phase 2 の
    #   レシピ探索 (REQ-SAR-500) に委ねる。実験の記録は
    #   `chore/stage-order-cell-then-displacement` ブランチと
    #   `docs/spec/stable-auto-rietveld/requirements.md` F1 にある。
    stages: list[RefinementStage] = []

    # S0: 相分率スケール + 背景 (全チュートリアル共通の起点)
    stages.append(
        RefinementStage(
            label="scale+background",
            flags={"scale": True, "background": {"coeffs": background_coeffs}},
            note="起点: スケールと背景のみ",
        )
    )

    if multiphase and not mixed_occ:
        # 多相 (T4 型: 放射光+TOF 二相) の順序 (実測で確立):
        # 相分率(和=1)を単独で先に → 格子+変位+プロファイル(+温度差 Dij) → 座標 → Uiso →
        # size/微小歪みを最後に。相分率を格子と同時に解放すると噛まず、size/歪みを座標より
        # 先に解放すると座標段階が悪化して revert するため、この順序が有効。
        stages.append(
            RefinementStage(
                label="phase_fractions",
                flags={"phase_fraction_sum": True},
                note="相分率 (各ヒストグラム和=1 制約)",
            )
        )
        cell_flags: dict[str, object] = {
            "cell": True,
            "displacement": disp,
            "profile": ["U", "V", "W"],
        }
        cell_note = "格子 + 試料変位 + プロファイル(CW)"
        if temp_diff:
            cell_flags["hydrostatic_strain"] = True
            cell_note += " + 温度差 Dij"
        stages.append(
            RefinementStage(label="cell+displacement+profile", flags=cell_flags, note=cell_note)
        )
        stages.append(coords_stage)
        stages.append(uiso_stage)
        stages.append(
            RefinementStage(
                label="size_strain",
                flags={"size_strain": True},
                note="結晶子サイズ/微小歪み (最後に解放)",
            )
        )
    else:
        # 単相 (T1/T2/T3): 格子+変位 (温度差なら Dij) を先に張る
        s1_flags: dict[str, object] = {"cell": True, "displacement": disp}
        note_bits = ["格子 + ジオメトリ別試料変位"]
        if temp_diff:
            s1_flags["hydrostatic_strain"] = True
            note_bits.append("温度差の静水圧歪み Dij")
        stages.append(
            RefinementStage(label="cell+displacement", flags=s1_flags, note="; ".join(note_bits))
        )
        # 混合占有の有無で解放順序を切り替える:
        # - 混合占有あり (中性子 garnet 型): 占有率 → Uiso(等価) → プロファイル → 一般位置座標。
        # - 混合占有なし (ラボ X 線 fluoroapatite 型): プロファイル → 座標 → Uiso。
        if mixed_occ:
            stages.append(
                RefinementStage(
                    label="occupancy",
                    flags={"occupancy": True},
                    note="混合占有サイトの占有率 (和=1 制約下)",
                )
            )
            stages.append(uiso_stage)
            stages.append(profile_stage)
            stages.append(coords_stage)
        else:
            stages.append(profile_stage)
            stages.append(coords_stage)
            stages.append(uiso_stage)

    # X 線は Lorentzian (X,Y) + Zero → 非対称 (SH/L) を最終段で追加解放 (各 revert ガード;
    # 中性子/TOF のみなら不要)
    if has_xray:
        stages.append(lorentzian_stage)
        stages.append(asymmetry_stage)

    # ラベルに S番号 を前置 (+ 相関群の検証)
    return _finalize(stages, histograms)


# ---------------------------------------------------------------------------
# "本気フィット" (超丁寧) レシピ — 順次解放/凍結を 2 周してから全開放
# ---------------------------------------------------------------------------
#: 座標/占有率を「重原子から順に」解放するときに用意する元素ランク数の上限
#: (``element_expansion="ranks"`` の従来経路)。実際の元素数を超えたランクの段は対象原子ゼロ =
#: no-op になる。T1 (Ca,P,O,F の 4 元素) では 2 ランク × 2 種 = 4 段が空回りしていた。
_MAX_ELEMENT_RANKS = 6

#: 座標/占有率の元素ランク展開方式 (REQ-SAR-303)。
#:
#: - ``"ranks"``  : レシピ側で 0..``_MAX_ELEMENT_RANKS``-1 の段を**決め打ちで並べる** (従来)。
#: - ``"heavy_first"``: レシピは「重原子から順に」と**宣言するだけ**にし、engine が適用時に
#:   実際の元素数へ展開する。
#:
#: ⚠ ``"heavy_first"`` は **engine 側の展開実装 (WS-3 3-3) が入るまで既定にしない**。
#: 展開が無い状態でこの宣言を engine へ渡すと `_element_rank_labels` が `ValueError` を送出し、
#: 当該段は chi2=inf → revert → ledger ``m7_stage_error`` になる (② 入口の `mcp._recipe_spec`
#: は JSON 経路でこれをより早く弾く)。**黙って別物になるよりは落とす**という選択であって、
#: 「使える宣言」ではない — 使えるようにするのは WS-3 3-3 の仕事。
_ELEMENT_EXPANSIONS = ("ranks", "heavy_first")

#: Uiso 等値拘束の緩和段階 (REQ-SAR-305)。**緩い方へ向かう順**で並べてある。
#:
#: - ``"shared"``     : 全原子で 1 つの Uiso (母数 1)
#: - ``"by_element"`` : 元素ごとに 1 つの Uiso
#: - ``"individual"`` : 原子ごと (等値拘束なし = 従来の ``uiso: True`` 段と同じ意味)
#:
#: 母数を減らした状態から始めて段階的に緩める。初手から原子ごとに Uiso を解放すると、弱い
#: 散乱体の Uiso が背景やスケールと相関して非物理値へ流れ、以降の段を巻き添えにする。
#: 等値拘束 (`add_EquivConstr`) は母数そのものを減らすので、この相関を**構造的に**断てる。
#:
#: ⚠ **restraint (ソフト拘束) を使ってはならない** — GSAS-II の headless 経路では penalty が
#: χ² から除外される一方で勾配/Hessian だけが引っ張られる (requirements.md F5, Issue #112)。
#: 等値拘束 (constraint) は変数そのものを消すので headless でも正しく効く。
#:
#: tier 名がそのまま ``uiso`` フラグの値になる。
#:
#: ⚠ **engine 側で tier を等値拘束へ写す実装は未了 (WS-3)**。現状この宣言を渡すと
#: `engine._element_rank_labels` が `ValueError` を送出して当該段が revert される
#: (以前は catch-all に落ちて「等値拘束なしの全原子解放」= ``individual`` 相当に**黙って**
#: 化けていた — 拘束を緩める順序を宣言したつもりで初手から最も緩い段を踏む形)。
#: ``element_expansion="heavy_first"`` と同じ扱いで、実装が入るまでは使えない。
UISO_TIERS: tuple[str, ...] = ("shared", "by_element", "individual")


def build_serious_recipe(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    background_coeffs: int = 6,
    rounds: int = 2,
    element_expansion: str = "ranks",
    uiso_tiers: Sequence[str] | None = None,
) -> tuple[RefinementStage, ...]:
    """超丁寧な段階解放 (人手の「本気フィット」手順を機械化したもの)。

    手順 (ユーザー規定):
      1. 背景 + スケール (以降**常時解放**)
      2-12 を **順次解放 → 凍結** で ``rounds`` 周 (既定 2 周):
         2. 格子 / 3. 試料変位 / 4. プロファイル W → W,U → W,U,V (**累積**。1 つずつ
            解放/凍結すると相関群を割ることになり両段とも revert する — REQ-SAR-301) /
         5. 格子+変位 (収束確認。**以降 格子は常時解放**) / 6. サイズ・微小歪み /
         7. 座標 (重原子から順) / 8. 占有率 (重原子から順) / 9. Lorentzian /
         10. 非対称 / 11. 異方性歪み / 12. Uiso
      13. 全開放 (収束すれば完了)
      14. 2-12 を**累積**解放
      15. 全開放

    ``freeze_others`` は段の適用前に既存の解放を落とす (engine `_freeze_all`)。値に名前の列を
    与えるとそれらは凍結しない — 手順 5 以降は ``["cell"]`` を渡して格子を常時解放にする。
    ``freeze_others`` を持たない段は従来どおり**累積 (enable のみ)** で、手順 14 の ``cum_*`` 段と
    `build_recipe` の全段はこちら (非回帰)。

    座標/占有率の解放単位は ``element_expansion`` で決める:

    - ``"ranks"`` (既定): ``{"coords": 0}`` … ``{"coords": 5}`` を決め打ちで並べる (従来)
    - ``"heavy_first"``: ``{"coords": "heavy_first"}`` の 1 段を**宣言**し、engine が実元素数へ展開する

    **engine 側の契約 (REQ-SAR-303, 未実装 — WS-3 統合で配線)**: ``coords``/``occupancy`` の値が
    ``"heavy_first"`` の段は、engine が適用時に相の実際の元素を Z 降順に並べ、
    「重い方から i 番目の元素だけを解放する段」を**元素数ぶんだけ**生成して順に実行する
    (i 段目の意味は現行の int ランクと同一)。実元素数を超える段は生成しない。
    レシピは CIF を読めない純関数なので元素数を知り得ず、決め打ちだと no-op 段が残る
    (T1 は 4 元素なので 2 ランク × 座標/占有率 = 4 段が空回りしていた)。

    ``uiso_tiers`` を与えると Uiso 段を**等値拘束の段階的緩和**に置き換える (REQ-SAR-305)。
    例 ``("shared", "by_element", "individual")`` で「全原子 1 変数 → 元素ごと → 個別」。
    None (既定) なら従来の 1 段 (個別) のまま = 非回帰。

    **engine 側の契約 (REQ-SAR-305, 未実装)**: ``uiso`` の値が ``"shared"`` なら全原子の Uiso を、
    ``"by_element"`` なら同一元素の Uiso を `add_EquivConstr` で等値にしてから解放する。
    より緩い tier へ進む段では**前段の等値拘束を外す**こと (残ると緩和にならない)。
    ⚠ restraint (ソフト拘束) では代用できない (`UISO_TIERS` の注記参照)。

    **周回入口で最良状態へ戻す (REQ-SAR-304) は engine 側の機能**であり本関数は関与しない。
    設計メモ: 2 周目の入口 (= ``rounds`` ループの各周の先頭段) で、その時点までの**最良 gpx**
    (Rwp 最小かつ妥当性 pass) をロードし直してから周回へ入る。理由は、1 周目の末尾が revert の
    連続で終わっていると 2 周目が「最良でない状態」から出発し、周回を重ねるほど劣化しうるため。
    engine 側で段に ``restore_best`` 相当の指示を持たせるなら、**未知フラグは engine が黙って
    無視する**ため `mcp/_recipe_spec.KNOWN_STAGE_FLAGS` への追加を同じ PR で行うこと。
    """
    if not histograms:
        raise ValueError("histograms が空です")
    if not phases:
        raise ValueError("phases が空です")
    if element_expansion not in _ELEMENT_EXPANSIONS:
        raise ValueError(
            f"element_expansion は {list(_ELEMENT_EXPANSIONS)} のいずれか: {element_expansion!r}"
        )
    tiers = list(uiso_tiers) if uiso_tiers is not None else None
    if tiers is not None:
        unknown = [t for t in tiers if t not in UISO_TIERS]
        if unknown:
            raise ValueError(
                f"uiso_tiers に未知の tier {unknown} があります (許容: {list(UISO_TIERS)})"
            )
        if list(tiers) != [t for t in UISO_TIERS if t in tiers]:
            # 緩い方から始めると母数が減らず、等値拘束を張る意味が無くなる (順序が本質)。
            raise ValueError(
                f"uiso_tiers は拘束の強い順 {list(UISO_TIERS)} の部分列である必要があります: {tiers}"
            )
        if not tiers:
            raise ValueError("uiso_tiers が空です (None なら従来の 1 段)")
    disp = _displacement_map(histograms)
    has_xray = any(not h.radiation.is_neutron for h in histograms)
    multiphase = len(phases) > 1
    stages: list[RefinementStage] = [
        RefinementStage(
            label="bkg+scale",
            flags={"scale": True, "background": {"coeffs": background_coeffs}},
            note="背景 + スケール (以降 常時解放)",
        )
    ]
    if multiphase:
        stages.append(
            RefinementStage(
                label="phase_fractions",
                flags={"phase_fraction_sum": True},
                note="相分率 (和=1)。多相のみ",
            )
        )

    def sequential(keep: "list[str]") -> "list[RefinementStage]":
        """2-12 を 1 周ぶん (順次解放 → 凍結)。``keep`` は凍結しない名前。"""
        k = list(keep)
        out = [
            RefinementStage(label="cell", flags={"freeze_others": k or True, "cell": True},
                            note="格子のみ"),
            RefinementStage(label="displacement",
                            flags={"freeze_others": k or True, "displacement": disp},
                            note="試料変位のみ"),
        ]
        # 【W → U → V は "累積"】: Caglioti の U,V,W は独立の knob ではなく **1 つの物理量**
        #   (FWHM² = U·tan²θ + V·tanθ + W) の係数なので、1 つずつ「解放 → 凍結」すると
        #   意味を成さず後続が効かない。実測 (CaTeO3): W 単独のあと U 単独/V 単独は**両方 revert**
        #   し、以降 Lorentzian も効かず 18% で頭打ち (標準レシピの 12.4% に対し大幅悪化)。
        #   W から順に**足していく** (W → W,U → W,U,V) のが 古典的 な手順であり実測でも合う。
        for coeffs in (["W"], ["W", "U"], ["W", "U", "V"]):
            out.append(
                RefinementStage(label="profile_" + "".join(coeffs),
                                flags={"freeze_others": k or True, "profile": list(coeffs)},
                                note="プロファイル " + ",".join(coeffs) + " (累積)")
            )
        out.append(
            RefinementStage(label="cell+displacement",
                            flags={"freeze_others": k or True, "cell": True, "displacement": disp},
                            note="格子 + 変位 (収束確認。以降 格子は常時解放)")
        )
        # ここから格子は凍結しない
        k2 = sorted(set(k) | {"cell"})
        out.append(
            RefinementStage(label="size_strain",
                            flags={"freeze_others": k2, "size_strain": True},
                            note="サイズ / 微小歪み")
        )
        # 座標 → 占有率を「重原子から順に」。元素ランクの展開方式は element_expansion で決める
        # (REQ-SAR-303: 宣言なら engine が実元素数へ展開し、決め打ちの no-op 段が消える)。
        for flag in ("coords", "occupancy"):
            what = "座標" if flag == "coords" else "占有率"
            if element_expansion == "heavy_first":
                out.append(
                    RefinementStage(
                        label=f"{flag}_heavy_first",
                        flags={"freeze_others": k2, flag: "heavy_first"},
                        note=f"{what} (重原子から順 — engine が実元素数へ展開する宣言)",
                    )
                )
                continue
            for rank in range(_MAX_ELEMENT_RANKS):
                out.append(
                    RefinementStage(label=f"{flag}_z{rank}",
                                    flags={"freeze_others": k2, flag: rank},
                                    note=f"{what} (重い方から {rank + 1} 番目の元素)")
                )
        if has_xray:
            out.append(
                RefinementStage(label="profile_lorentzian",
                                flags={"freeze_others": sorted(set(k2) | {"profile"}),
                                       "profile": ["U", "V", "W"], "profile_lorentzian": True},
                                note="Lorentzian X,Y + Zero (U,V,W は保持 — 同じ FWHM の別成分)")
            )
            out.append(
                RefinementStage(label="profile_asymmetry",
                                flags={"freeze_others": k2, "profile_asymmetry": True},
                                note="軸発散非対称 SH/L")
            )
        out.append(
            RefinementStage(label="aniso_strain",
                            flags={"freeze_others": k2, "size_strain": "generalized"},
                            note="異方性 微小歪み")
        )
        if tiers is None:
            out.append(
                RefinementStage(label="uiso", flags={"freeze_others": k2, "uiso": True},
                                note="Uiso")
            )
        else:
            # 等値拘束を段階的に緩める (REQ-SAR-305)。母数の少ない側から入り、改善しなくなったら
            # revert ガードがそこで止める = 「必要なだけ緩める」が自動で決まる。
            for tier in tiers:
                out.append(
                    RefinementStage(
                        label=f"uiso_{tier}",
                        flags={"freeze_others": k2, "uiso": tier},
                        # note は ledger に出る = ③ が読む。**engine 未対応時に何が起きるか**を
                        # 正確に書く (以前は「拘束なし = individual と同義」と書いていたが、
                        # それは engine が非 int 値を黙って全ラベル解放と読んでいた頃の話。
                        # 今は tier 値を解釈できず ValueError → revert する。個別解放へ静かに
                        # 落ちる経路はもう無いので、individual だけを別扱いする理由も無い)。
                        note=f"Uiso ({tier} 等値拘束)"
                        " — engine 未対応 (WS-3): 現状この段は ValueError → revert",
                    )
                )
        return out

    all_open: dict[str, object] = {
        "cell": True, "displacement": disp, "profile": ["U", "V", "W"],
        "size_strain": True, "coords": True, "uiso": True, "occupancy": True,
    }
    if multiphase:
        all_open["phase_fraction_sum"] = True
    if has_xray:
        all_open["profile_lorentzian"] = True
        all_open["profile_asymmetry"] = True

    keep: list[str] = []
    for _ in range(max(1, rounds)):
        stages.extend(sequential(keep))
        keep = ["cell"]  # 2 周目以降は格子を常時解放のまま入る
    # 13: 全開放
    stages.append(RefinementStage(label="all_open", flags=dict(all_open), note="全開放 (収束確認)"))
    # 14: 2-12 を累積解放 (freeze_others なし = 従来の累積セマンティクス)
    cumulative: list[tuple[str, dict[str, object]]] = [
        ("cell", {"cell": True}),
        ("displacement", {"displacement": disp}),
        ("profile", {"profile": ["W", "U", "V"]}),
        ("size_strain", {"size_strain": True}),
        ("coords", {"coords": True}),
        ("occupancy", {"occupancy": True}),
    ]
    if has_xray:
        cumulative.append(("profile_lorentzian", {"profile_lorentzian": True}))
        cumulative.append(("profile_asymmetry", {"profile_asymmetry": True}))
    cumulative.append(("aniso_strain", {"size_strain": "generalized"}))
    cumulative.append(("uiso", {"uiso": True}))
    for label, fl in cumulative:
        stages.append(RefinementStage(label=f"cum_{label}", flags=fl, note="累積解放"))
    # 15: 全開放
    stages.append(RefinementStage(label="all_open_final", flags=dict(all_open), note="全開放"))
    return _finalize(stages, histograms)
