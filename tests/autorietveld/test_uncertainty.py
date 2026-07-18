"""格子 esd 抽出 (`_cell_esd_map`) の GSAS 非依存テスト (レビュー第5巡 HIGH-F1)。

**捏造しないこと**を検査する。`get_cell_and_esd()` は**凍結した格子でも例外を出さず 0.0 を返す**
(GSAS `getCellEsd` は `varyList` に無い項の分散を 0 にするため)。旧実装はこれを素通しし、
「精密化して 0 に決まった」と読める値を出版経路へ流していた (実測: 論文用 CSV の
`mono_a_esd=0.0` が 192/192 フレーム、`tetra` 63/63、`cubic` 34/211)。

**③ が区別できなければならない 3 状態**:

| 状態 | 表現 | 意味 |
|---|---|---|
| 精密化した | `>0.0` | 共分散由来の su。`a = 10.0316(133)` と書ける |
| 対称拘束で固定 | `0.0` | mono の α/γ は**厳密に 90°**。0.0 は真の陳述 |
| 精密化していない | `None` | 凍結セル (手動 `refine_cell=False` / `auto_freeze_minor_cells`)。 |
|  |  | このデータからは決まっていない → esd を書いてはならない |
| 抽出できなかった | 相ごと欠落 | `get_cell_and_esd()` が例外 (共分散構造の破損など) |

numpy-only。実 GSAS 版は `test_uncertainty_gsas.py`。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.engine import (
    _cell_esd_map,
    _cell_was_refined,
    _weight_esd_or_none,
    _weight_fraction_maps,
)

_KEYS = ("length_a", "length_b", "length_c", "angle_alpha", "angle_beta", "angle_gamma")


class _FakeProject:
    """`ph.proj['Covariance']['data']` を提供する最小プロジェクト (GSAS の構造に一致)。"""

    def __init__(self, vary_list: list[str] | None):
        self._cov = {} if vary_list is None else {"varyList": list(vary_list)}

    def __getitem__(self, key: str) -> dict:
        if key != "Covariance":
            raise KeyError(key)
        return {"data": self._cov}


class _FakePhase:
    """`G2Phase` の `_cell_esd_map` が触る面だけを模したスタブ。

    :param vary_list: 最後の精密化の変数名列 (`None` で Covariance 自体が無い = 未精密化)
    :param esd: `get_cell_and_esd()` の第 2 要素が返す値 (GSAS は凍結セルでも 0.0 を返す)
    :param raises: `get_cell_and_esd()` が例外を送出するか (抽出不能相)
    """

    def __init__(
        self,
        name: str,
        pid: int,
        *,
        vary_list: list[str] | None = None,
        esd: tuple[float, ...] = (0.0,) * 6,
        raises: bool = False,
    ):
        self.name = name
        self.id = pid
        self.proj = _FakeProject(vary_list)
        self._esd = esd
        self._raises = raises

    def get_cell_and_esd(self) -> tuple[dict, dict]:
        if self._raises:
            raise RuntimeError("covariance structure broken")
        cell = dict.fromkeys(_KEYS, 10.0)
        return cell, dict(zip(_KEYS, self._esd))


def _refined(name: str, pid: int, esd: tuple[float, ...]) -> _FakePhase:
    """格子を解放した相 (varyList に `<pId>::A0..A5` が立つ)。"""
    return _FakePhase(name, pid, vary_list=[f"{pid}::A{i}" for i in range(6)], esd=esd)


# --- _cell_was_refined (authoritative source = Covariance varyList) ---


def test_cell_was_refined_true_when_a_terms_in_vary_list():
    assert _cell_was_refined(_FakePhase("p", 0, vary_list=["0::A0", "0::A2", "0:0:Scale"])) is True


def test_cell_was_refined_false_when_no_a_terms():
    # 凍結セル: Scale 等は精密化されているが A0..A5 は変数でない (= 実データの cubic/tetra)。
    assert _cell_was_refined(_FakePhase("p", 0, vary_list=["0:0:Scale", "0::AUiso:0"])) is False


def test_cell_was_refined_uses_the_phase_prefix_not_bare_a_terms():
    """★別相の A 項を自相のものと取り違えないこと (pId プレフィクスで識別する)。

    多相 operando では主相 (pId=0) の格子だけを解放するのが普通であり、プレフィクスを見ない
    実装は**凍結した副相 (pId=1,2) まで「精密化した」と判定**して 0.0 を出版経路へ戻す。
    """
    frozen_minor = _FakePhase("tetra", 2, vary_list=["0::A0", "0::A1", "0::A2", "1::A0"])
    assert _cell_was_refined(frozen_minor) is False


def test_cell_was_refined_false_without_covariance():
    # 精密化前/未収束 (Covariance 無し) → 「精密化した」と主張できない。
    assert _cell_was_refined(_FakePhase("p", 0, vary_list=None)) is False


def test_cell_was_refined_is_false_when_the_probe_itself_fails():
    """探れないときは False (= esd を主張しない)。**判定不能を「精密化した」に倒さない**。"""

    class _Broken:
        name = "p"
        id = 0
        proj = None  # `proj['Covariance']` が TypeError

    assert _cell_was_refined(_Broken()) is False


# --- _cell_esd_map (3 状態の作り分け) ---


def test_frozen_cell_esd_is_none_not_zero():
    """★F1 の核心: 凍結セルに esd=0.0 を捏造しない (0.0 は「決まった」と読まれる)。"""
    frozen = _FakePhase("cubic", 1, vary_list=["0::A0", "0:0:Scale"], esd=(0.0,) * 6)
    out = _cell_esd_map([frozen])
    assert out["cubic"] == (None,) * 6, (
        f"凍結セルに 0.0 を捏造している: {out['cubic']} — 論文では a = 10.5200(0) と読まれる"
    )


def test_refined_cell_keeps_symmetry_fixed_zeros():
    """★対称拘束で固定された角度の 0.0 は**真の陳述**なので残す (mono の α/γ は厳密に 90°)。"""
    mono = _refined("mono", 0, (0.013303, 0.017739, 0.010871, 0.0, 0.130036, 0.0))
    out = _cell_esd_map([mono])
    assert out["mono"] == (0.013303, 0.017739, 0.010871, 0.0, 0.130036, 0.0)


def test_the_three_states_are_distinguishable_in_one_result():
    """★実データの配置 (mono 解放 + cubic/tetra 凍結) で 3 状態が判別できること。

    ③ には「解放して 0 に決まった」も「凍結」も同じ present な 0.0 に見えていた。
    """
    phases = [
        _refined("mono", 0, (0.0133, 0.0177, 0.0109, 0.0, 0.1300, 0.0)),
        _FakePhase("cubic", 1, vary_list=["0::A0"], esd=(0.0,) * 6),
        _FakePhase("tetra", 2, vary_list=["0::A0"], esd=(0.0,) * 6),
    ]
    out = _cell_esd_map(phases)

    assert out["mono"][0] > 0.0  # 解放 → 共分散由来の su
    assert out["mono"][3] == 0.0 and out["mono"][5] == 0.0  # 対称拘束 → 真の 0.0
    assert out["cubic"] == (None,) * 6 and out["tetra"] == (None,) * 6  # 凍結 → 「無い」
    # レイアウト不変条件 (refined_cells と同じ相集合・6 要素) は保つ。
    assert set(out) == {"mono", "cubic", "tetra"}
    assert all(len(v) == 6 for v in out.values())


def test_non_finite_esd_of_a_refined_cell_becomes_none_not_zero():
    """解放したセルの NaN/inf esd も 0.0 に丸めない (「値が無い」であって「厳密」ではない)。"""
    ph = _refined("p", 0, (float("nan"), float("inf"), 0.001, 0.0, 0.0, 0.0))
    out = _cell_esd_map([ph])
    assert out["p"] == (None, None, 0.001, 0.0, 0.0, 0.0)


def test_unextractable_phase_is_dropped_entirely():
    """例外を出す相は**キーごと落とす** (抽出不能 ≠ 凍結。相ごと欠落で区別する)。"""
    ok = _refined("mono", 0, (0.001, 0.001, 0.001, 0.0, 0.0, 0.0))
    broken = _FakePhase("broken", 1, raises=True)
    out = _cell_esd_map([ok, broken])
    assert set(out) == {"mono"}


def test_empty_phase_list_gives_empty_map():
    assert _cell_esd_map([]) == {}


@pytest.mark.parametrize("vary", [["0::A0"], ["0::A5"], ["0::A3", "0:0:Scale"]])
def test_any_single_a_term_counts_as_refined(vary):
    """A0..A5 のどれか 1 つでも変数なら格子は解放されている (対称性で自由項数が異なる)。"""
    assert _cell_was_refined(_FakePhase("p", 0, vary_list=vary)) is True


# --- 重量分率 esd (`_weight_fraction_maps` / `_weight_esd_or_none`) — レビュー第6巡 HIGH ---
#
# GSAS-II `calcMassFracs` は相分率 (相 Scale) が**最終共分散の varyList に無い**とき、当該
# ヒストグラムの**全相**の su を厳密に 0.0 にする (導関数ベクトル `Avec` が全 0 → sqrt(0);
# `GSASIIstrMath.calcMassFracs` L5218-5285 で確認)。この 0.0 は「精密化して 0 に決まった」では
# なく「決まっていない」を意味する — cell_esd (F1) と**同型の捏造**。実測 (K₂Mn[Fe(CN)₆] M10
# `publication_m10.csv`): fr213 は fr212 と重量分率が完全一致 (0.80115/0.19885) で su だけ 0.0、
# fr224 も fr223 と一致で su 0.0 = 全段 revert (warm-start 種のまま) のフレームである。


class _FakeName:
    """`_weight_fraction_maps` が単相分岐で触る面 (`.name`) だけを持つスタブ。"""

    def __init__(self, name: str):
        self.name = name


class _FakeHist:
    """`g2hists[0].ComputeMassFracs()` を模したスタブ (GSAS の {name:(val,su)} 契約)。"""

    def __init__(self, vals: dict | None, *, raises: bool = False):
        self._vals = vals
        self._raises = raises

    def ComputeMassFracs(self) -> dict:  # noqa: N802 — GSAS-II の API 名に合わせる
        if self._raises:
            raise RuntimeError("no covariance (未収束/未精密化)")
        return dict(self._vals or {})


def test_weight_esd_or_none_maps_zero_and_nonfinite_to_none():
    """★核心: 多相 su の 0.0 / 非有限 / 負は `None` (捏造回避)、正のみ値を残す。"""
    assert _weight_esd_or_none(0.0) is None  # calcMassFracs の「未決定」= 捏造の 0.0
    assert _weight_esd_or_none(-1e-9) is None
    assert _weight_esd_or_none(float("nan")) is None
    assert _weight_esd_or_none(float("inf")) is None
    assert _weight_esd_or_none(None) is None
    assert _weight_esd_or_none("garbage") is None
    assert _weight_esd_or_none(0.00789) == pytest.approx(0.00789)


def test_multiphase_zero_su_becomes_none_not_fabricated_zero():
    """★実データ fr32/fr213/fr224 の再現: 多相で分率は present だが su=0.0 → esd を捏造しない。

    分率 (0.7104/0.2896) は残るが、esd は `None` (このフレームでは決まっていない) になる。
    旧実装 (`_finite_or_zero`) はここで 0.0 を返し `wt = 0.290(0)` = 無限精度を出版していた。
    """
    hist = _FakeHist({"mono": (0.7104, 0.0), "cubic": (0.2896, 0.0)})
    fracs, esds = _weight_fraction_maps([_FakeName("mono"), _FakeName("cubic")], [hist])
    assert fracs == {"mono": pytest.approx(0.7104), "cubic": pytest.approx(0.2896)}
    assert esds == {"mono": None, "cubic": None}, (
        f"多相の su=0.0 を捏造している: {esds} — 論文では wt = 0.290(0) と読まれる"
    )


def test_multiphase_nonzero_su_is_preserved():
    """分率精密化が共分散に残った多相フレームは su>0 をそのまま出版する (正常経路の非回帰)。"""
    hist = _FakeHist({"mono": (0.72115, 0.00789), "cubic": (0.27885, 0.00789)})
    _fracs, esds = _weight_fraction_maps([_FakeName("mono"), _FakeName("cubic")], [hist])
    assert esds == {"mono": pytest.approx(0.00789), "cubic": pytest.approx(0.00789)}


def test_multiphase_nonfinite_su_becomes_none():
    """NaN/inf の su も 0.0 に丸めず None (「値が無い」であって「厳密 0」ではない)。"""
    hist = _FakeHist({"mono": (0.6, float("nan")), "cubic": (0.4, float("inf"))})
    _fracs, esds = _weight_fraction_maps([_FakeName("mono"), _FakeName("cubic")], [hist])
    assert esds == {"mono": None, "cubic": None}


def test_single_phase_weight_esd_zero_is_true_not_none():
    """★逆誤り防止: 単相の {name: 0.0} は**真の陳述** (孤立相は 1.0・不確かさ無し) なので None にしない。

    単相分岐は calcMassFracs を通さず早期 return するため、`_weight_esd_or_none` の 0.0→None の
    規則には掛からない。ここを None に「修正」すると R5 の逆 (真の 0.0 を消す) 誤りになる。
    """
    fracs, esds = _weight_fraction_maps([_FakeName("mono")], [_FakeHist(None)])
    assert fracs == {"mono": 1.0}
    assert esds == {"mono": 0.0}


def test_empty_or_failing_massfracs_degrades_to_empty_maps():
    """相/ヒストグラム無し・ComputeMassFracs 例外は空 dict へ縮退し例外を送出しない。"""
    assert _weight_fraction_maps([], []) == ({}, {})
    hist = _FakeHist(None, raises=True)
    assert _weight_fraction_maps([_FakeName("a"), _FakeName("b")], [hist]) == ({}, {})
