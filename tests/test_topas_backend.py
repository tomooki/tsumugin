"""M12 T9: `TopasBackend` — `RefinementBackend` Protocol の TOPAS 実装。

`tests/test_gsasii_backend.py` と**対の並行スイート**。両バックエンドが同じ契約を満たすことを
別々に検証する (共有 contract test を持たないのが既存の作法)。

**なぜ必要か**: 実構造の多仮説探索は `AutoRietveldBackend(runner=…)` に TOPAS runner を渡せば
既に成立するが、`search.tree` / `sequential.engine` は `simulate()` を要求する。そこだけが
TOPAS で塞がっていた (#175)。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from tsumugin.backends.base import RefinementBackend, RefinementModel, param_name
from tsumugin.backends.topas import TopasBackend
from tsumugin.errors import TopasUnavailableError
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.topas.availability import topas_available


def _phase(a: float = 4.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _grid() -> np.ndarray:
    return np.arange(20.0, 80.0, 0.05)


# ---------------- 可用性 / 契約 (TOPAS 非依存) ----------------


def test_backend_raises_when_unavailable(monkeypatch):
    """未導入環境では構築時に落とす (GSAS 側と同じ縮退)。"""
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", "none")
    with pytest.raises(TopasUnavailableError):
        TopasBackend()


def test_backend_satisfies_the_protocol():
    """`RefinementBackend` は runtime_checkable な構造的 Protocol。"""
    assert isinstance(TopasBackend, type)
    assert hasattr(TopasBackend, "refine") and hasattr(TopasBackend, "simulate")


def test_backend_name_identifies_the_engine():
    """**Rwp/BIC を跨いで比較するときの前提**なので名前が要る。"""
    assert TopasBackend.name == "topas"


# ---------------- 実 tc.exe ----------------


@pytest.mark.topas
def test_instance_is_a_refinement_backend():
    assert isinstance(TopasBackend(), RefinementBackend)


@pytest.mark.topas
def test_simulate_produces_nontrivial_pattern():
    backend = TopasBackend()
    tt = _grid()
    y = backend.simulate((_phase(a=4.0, scale=1.0),), tt)
    assert y.shape == tt.shape
    assert np.all(np.isfinite(y))
    # 回折ピークが平坦な背景から十分に立ち上がっていること
    assert y.max() > 5 * max(float(np.median(y)), 1e-9)


@pytest.mark.topas
def test_simulate_is_deterministic():
    """NFR-102: 同じ入力からビット同一 (Ycalc を使い観測ノイズを混ぜない)。"""
    backend = TopasBackend()
    tt = _grid()
    a = backend.simulate((_phase(),), tt)
    b = backend.simulate((_phase(),), tt)
    assert np.array_equal(a, b)


@pytest.mark.topas
def test_simulate_tracks_the_lattice():
    """格子を変えるとピーク位置が動くこと (格子が前方計算に効いている証拠)。"""
    backend = TopasBackend()
    tt = _grid()
    small = backend.simulate((_phase(a=4.0),), tt)
    large = backend.simulate((_phase(a=4.2),), tt)
    assert int(np.argmax(small)) != int(np.argmax(large))


@pytest.mark.topas
def test_refine_with_nothing_free_reports_zero_params():
    backend = TopasBackend()
    tt = _grid()
    truth = _phase()
    y = backend.simulate((truth,), tt)
    result = backend.refine(
        RefinementModel(phases=(truth,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    assert result.n_params == 0
    assert result.n_obs == tt.size
    assert result.rwp >= 0.0


@pytest.mark.topas
def test_refine_scale_improves_fit():
    """スケールを解放すると、ずらした初期値から真値へ戻ること。"""
    backend = TopasBackend()
    tt = _grid()
    truth = _phase(scale=1.0)
    y = backend.simulate((truth,), tt)
    start = _phase(scale=0.5)
    before = backend.refine(
        RefinementModel(phases=(start,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    after = backend.refine(
        RefinementModel(
            phases=(start,),
            free_params=frozenset({param_name(0, "scale")}),
            two_theta=tt,
            intensity=y,
        )
    )
    assert after.rwp < before.rwp
    assert after.n_params >= 1


@pytest.mark.topas
def test_rwp_is_on_the_same_scale_as_the_gsas_backend():
    """**バックエンド間で rwp/chi2 の意味を揃える** (不変条件: BIC 比較の一貫性)。

    ``rwp = 100·√(Σw(yo−yc)² / Σw·yo²)``。TOPAS の ``r_wp_dash`` は背景差引きで非互換なので
    使わない — ここでは残差から自前で計算し、定義のずれを持ち込まない。
    """
    backend = TopasBackend()
    tt = _grid()
    truth = _phase()
    y = backend.simulate((truth,), tt)
    result = backend.refine(
        RefinementModel(phases=(truth,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    expected = 100.0 * np.sqrt(result.chi2 / float(np.sum(y**2)))
    assert result.rwp == pytest.approx(expected, rel=1e-6)


@pytest.mark.topas
def test_backend_failure_becomes_infinite_chi2_not_an_exception():
    """**不変条件**: バックエンドの失敗は例外でなく chi2=inf に変換する。"""
    backend = TopasBackend()
    tt = _grid()
    # 格子 0 は INP としては書けるが物理的に成立しない → tc.exe が落ちる。
    broken = PhaseInstance(phase_ref="P", lattice=LatticeParams(0.0, 0.0, 0.0), scale=1.0)
    result = backend.refine(
        RefinementModel(
            phases=(broken,), free_params=frozenset(), two_theta=tt, intensity=np.ones_like(tt)
        )
    )
    assert np.isinf(result.chi2) and np.isinf(result.rwp)
    assert result.converged is False


@pytest.mark.topas
def test_failure_strips_stale_lattice_sigma():
    """失敗結果に**古い σ を残さない** — chi2=inf の仮説に σ が付いて見えるため (GSAS 側と同じ)。"""
    backend = TopasBackend()
    tt = _grid()
    lattice = LatticeParams(
        0.0, 0.0, 0.0, sigma={"a": 0.01}, sigma_source="covariance"
    )
    broken = PhaseInstance(phase_ref="P", lattice=lattice, scale=1.0)
    result = backend.refine(
        RefinementModel(
            phases=(broken,), free_params=frozenset(), two_theta=tt, intensity=np.ones_like(tt)
        )
    )
    assert result.phases[0].lattice.sigma == {}
    assert result.phases[0].lattice.sigma_source == ""


@pytest.mark.topas
def test_unknown_parameter_suffixes_are_ignored():
    """未対応 suffix は黙って無視する (GSAS 版と同挙動 — 探索側が広い語彙を投げてくる)。"""
    backend = TopasBackend()
    tt = _grid()
    truth = _phase()
    y = backend.simulate((truth,), tt)
    result = backend.refine(
        RefinementModel(
            phases=(truth,),
            free_params=frozenset({param_name(0, "texture.march")}),
            two_theta=tt,
            intensity=y,
        )
    )
    assert result.n_params == 0


def test_availability_helper_is_consistent_with_the_module():
    """`topas_available()` と構築可否が食い違わないこと。"""
    if topas_available():
        TopasBackend()  # 例外を出さない
    else:
        with pytest.raises(TopasUnavailableError):
            TopasBackend()


# ---------------- 相ごとの解放 (多相) ----------------


def _document_for(free_params, n_phases=2):
    """`_document` は純関数 (tc.exe 不要) — 生成される INP を直接見る。"""
    import numpy as _np

    backend = TopasBackend.__new__(TopasBackend)  # __init__ の可用性検査を迂回
    backend.wavelength = 1.5406
    phases = tuple(_phase(a=4.0 + i, ref=f"P{i}") for i in range(n_phases))
    scale_free, cell_free = TopasBackend._recognized(frozenset(free_params), n_phases)
    import tempfile as _tempfile
    from pathlib import Path as _Path

    with _tempfile.TemporaryDirectory() as tmp:
        work = _Path(tmp)
        grid = _np.arange(20.0, 30.0, 0.05)
        from tsumugin.topas.instrument import write_xye

        write_xye(work / "obs.xye", grid, _np.ones_like(grid))
        doc = backend._document(
            phases, work, cell_free=cell_free, scale_free=tuple(scale_free), max_cyc=5
        )
        return doc.render(), scale_free, cell_free


def test_lattice_is_released_only_for_the_requested_phase():
    """**相ごとの指定が潰れない**こと。

    `free_params={"phase1.lattice.a"}` で相 0 の格子まで解放すると、要求していない相が
    黙って動いて相 1 のフィットと相関する。しかも `_read_back` は要求分しか読み戻さないので
    **TOPAS が実際に動かした値と結果が食い違う**。
    """
    text, _, cell_free = _document_for({param_name(1, "lattice.a")})
    assert cell_free == {1}
    assert "a !phase0_a" in text, "相 0 の格子が解放されている"
    assert "a phase1_a" in text, "相 1 の格子が解放されていない"


def _released_cell_params(text: str) -> int:
    """生成された INP で実際に解放されている格子パラメータ数。

    **TOPAS のパラメータ意味論に従って判定する** (「``!`` が付いていない」では足りない):

    ============================  ==========
    軸トークンの次                  意味
    ============================  ==========
    ``@``                         解放 (無名)
    ``!name``                     固定 (名前付き)
    ``name``                      **解放** (名前付きは既定で精密化対象)
    数値                          固定 (無名)
    ``=expr;``                    参照 (解放できない)
    ============================  ==========

    無名固定 (``a 4.0``) を「解放」と数えないために**数値かどうかを見る**。現状 `_document`
    は必ず名前を付けるので該当しないが、それは呼び出し側の都合であってこの数え方の前提には
    しない (前提にすると、名前付けをやめた瞬間に黙って過大に数える)。
    """
    count = 0
    for raw in text.splitlines():
        head, _, rest = raw.strip().partition(" ")
        if head not in ("a", "b", "c") or not rest:
            continue
        token = rest.split()[0]
        if token.startswith(("!", "=")):
            continue  # 固定 (名前付き) / 参照
        if token == "@":
            count += 1
            continue
        try:
            float(token)
        except ValueError:
            count += 1  # 名前付き = 既定で精密化対象
    return count


def test_released_cell_params_follows_topas_parameter_semantics():
    """数え方そのものを固定する (このヘルパが間違うと上位のテストが静かに嘘をつく)。"""
    assert _released_cell_params("a @ 4.0") == 1          # 無名・解放
    assert _released_cell_params("a nm 4.0") == 1         # 名前付き = 既定で精密化対象
    assert _released_cell_params("a !nm 4.0") == 0        # 名前付き・固定
    assert _released_cell_params("a 4.0") == 0            # 無名・固定
    assert _released_cell_params("b =Get(a);") == 0       # 参照
    assert _released_cell_params("  site a1 x 0.0") == 0  # 軸行ではない


def test_generated_inp_releases_only_the_requested_lattices():
    """生成された INP で解放されている格子が要求分だけであること。"""
    text, _, cell_free = _document_for({param_name(1, "lattice.a")})
    assert _released_cell_params(text) == 3 * len(cell_free) == 3


@pytest.mark.topas
def test_n_params_matches_what_the_generated_inp_actually_releases():
    """**BIC 比較の一貫性**: `RefinementResult.n_params` が INP の実解放数と一致すること。

    `n_params` が実際に解放した数と食い違うと仮説間の BIC/AIC が意味を失う。純関数側
    (`_document`) だけを見ても `refine()` が返す `n_params` は検証されない — 数式を書き写す
    行にタイポが入っても気づけないので、**実際に回して返り値を突き合わせる**。
    """
    backend = TopasBackend()
    tt = _grid()
    phases = (_phase(a=4.0, ref="A"), _phase(a=4.3, ref="B"))
    observed = backend.simulate(phases, tt)
    free = {param_name(1, "lattice.a"), param_name(0, "scale")}
    result = backend.refine(
        RefinementModel(
            phases=phases, free_params=frozenset(free), two_theta=tt, intensity=observed
        )
    )
    text, scale_free, cell_free = _document_for(free)
    assert result.n_params == _released_cell_params(text) + len(scale_free)
    assert result.n_params == 3 * len(cell_free) + len(scale_free) == 4


@pytest.mark.topas
def test_read_back_only_updates_the_requested_phase():
    """**要求していない相の格子を書き換えない** (TOPAS が動かした値との食い違いを作らない)。"""
    backend = TopasBackend()
    tt = _grid()
    phases = (_phase(a=4.0, ref="A"), _phase(a=4.3, ref="B"))
    observed = backend.simulate(phases, tt)
    result = backend.refine(
        RefinementModel(
            phases=phases,
            free_params=frozenset({param_name(1, "lattice.a")}),
            two_theta=tt,
            intensity=observed,
        )
    )
    # 相 0 は解放していないので入力値のまま・σ も付かない。
    assert result.phases[0].lattice.a == pytest.approx(4.0)
    assert result.phases[0].lattice.sigma == {}


def test_scale_is_also_per_phase():
    """スケールも同様に相ごと (既に集合で渡っているが回帰ガードとして固定する)。"""
    text, _, _ = _document_for({param_name(0, "scale")})
    assert "scale !P1_scale" in text or "scale !phase1_scale" in text


# ---------------- 実 CIF (structure_ref) — 捏造構造で代替しない (#180) ----------------

_CUBIC_CIF = """data_caf2
_cell_length_a    5.46300
_cell_length_b    5.46300
_cell_length_c    5.46300
_cell_angle_alpha 90.0000
_cell_angle_beta  90.0000
_cell_angle_gamma 90.0000
_symmetry_space_group_name_H-M   'F m -3 m'
_symmetry_Int_Tables_number      225
loop_
 _symmetry_equiv_pos_as_xyz
 'x,y,z'
 '-x,-y,z'
 '-x,y,-z'
 'x,-y,-z'
 'y,z,x'
 'z,x,y'
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 _atom_site_U_iso_or_equiv
 Ca1   Ca   0.00000   0.00000   0.00000  1.000  0.01000
 F1    F    0.25000   0.25000   0.25000  1.000  0.01000
"""


@pytest.fixture()
def cubic_cif(tmp_path) -> str:
    path = tmp_path / "caf2.cif"
    path.write_text(_CUBIC_CIF, encoding="ascii")
    return str(path)


def _structure_document(cif: str, *, cell_free=frozenset({0}), a: float = 5.5):
    """実 CIF 相 1 つの文書を組む (tc.exe 不要)。"""
    import tempfile as _tempfile
    from pathlib import Path as _Path

    from tsumugin.topas.instrument import write_xye

    backend = TopasBackend.__new__(TopasBackend)
    backend.wavelength = 1.5406
    phase = PhaseInstance(
        phase_ref="CaF2", lattice=LatticeParams(a, a, a), scale=1.0, structure_ref=cif
    )
    with _tempfile.TemporaryDirectory() as tmp:
        work = _Path(tmp)
        grid = np.arange(20.0, 60.0, 0.05)
        write_xye(work / "obs.xye", grid, np.ones_like(grid))
        doc = backend._document(
            (phase,), work, cell_free=set(cell_free), scale_free=(), max_cyc=5
        )
        return doc


def test_structure_ref_builds_the_real_structure_not_the_simplified_one(cubic_cif):
    """**実 CIF を渡されたら実構造で組む**。

    黙って簡約モデル (P m m m・Ni 1 原子) で代替すると、③ から見て「実構造で判別した」
    ことになる — 判別 (`discriminate`) はまさにこの経路なので、捏造構造で走った結果が
    実データの結論として返ってしまう (これが #180 まで ② 非露出だった理由)。
    """
    text = _structure_document(cubic_cif).render()
    assert "Pmmm" not in text, "簡約モデルの空間群が残っている"
    assert "site Ni1" not in text, "簡約モデルの原子が残っている"
    assert "space_group Fm-3m" in text or "space_group F_m_-3_m" in text, text[:400]
    assert "site Ca1" in text and "site F1" in text


def test_structure_ref_cell_takes_the_warm_start_lengths_and_the_cif_angles(cubic_cif):
    """格子長は warm-start (判別が動かした値)、角度は CIF 由来を保つ。

    GSAS 側 `_apply_cell` と同じ規律 — 判別は a/b/c しか解放しないので、角度を
    `LatticeParams` の既定 90° で上書きすると単斜/三斜 CIF の正しい角を潰す。
    """
    doc = _structure_document(cubic_cif, a=5.5)
    cell = doc.phases[0].cell
    assert cell["a"].value == pytest.approx(5.5), "warm-start の格子長が入っていない"
    # 立方晶なので b/c は a への参照 (独立変数ではない)
    assert cell["b"].is_reference and cell["c"].is_reference


def test_symmetry_constrained_axes_are_not_released_independently(cubic_cif):
    """立方晶で 3 軸を独立に解放すると対称性が壊れる (しかも Rwp は下がりうる)。"""
    doc = _structure_document(cubic_cif, cell_free=frozenset({0}))
    refined = [k for k, v in doc.phases[0].cell.items() if v.refine]
    assert refined == ["a"], f"解放された軸: {refined}"


def test_free_parameter_count_follows_the_symmetry_not_a_fixed_three(cubic_cif):
    """`n_params` は **BIC の母数**なので、対称拘束で減った分を数え落とさない。

    簡約モデル (P m m m) は常に 3 軸独立だったので `3 * len(cell_free)` で正しかったが、
    実 CIF では結晶系で変わる (立方晶は 1)。過大申告すると仮説比較が歪む。
    """
    from tsumugin.backends.topas import count_free_params

    doc = _structure_document(cubic_cif)
    assert count_free_params(doc, scale_free=()) == 1


def test_phases_without_structure_ref_still_use_the_simplified_model():
    """回帰: 簡約モデルの相 (structure_ref なし) は従来どおり P m m m で組む。"""
    text, _, _ = _document_for(set(), n_phases=1)
    assert "Pmmm" in text and "site Ni1" in text


@pytest.mark.topas
def test_real_cif_refinement_runs_and_reads_the_cell_back(cubic_cif):
    """実 tc.exe で実 CIF 相を精密化し、格子が読み戻ること (従属軸込み)。

    従属軸 (``b =Get(a);``) は `Out()` に出ないので、参照式を解かないと**格子が
    「動かなかった」ように見える** (実際には TOPAS が動かしている)。
    """
    backend = TopasBackend()
    tt = _grid()
    phase = PhaseInstance(
        phase_ref="CaF2", lattice=LatticeParams(5.463, 5.463, 5.463), scale=1.0,
        structure_ref=cubic_cif,
    )
    observed = backend.simulate((phase,), tt)
    assert np.all(np.isfinite(observed)) and observed.max() > 0.0

    # 【摂動は収束半径の中に置く】: ピーク幅より大きくずらすと最小二乗は原理的に戻れない
    #   (0.7% ずらすと 5.5018 で止まることを実測)。ここで見たいのは収束半径ではなく
    #   「実 CIF 相が精密化されて格子が読み戻るか」なので 0.13% にする。
    warm = phase.with_updates(lattice=LatticeParams(5.470, 5.470, 5.470))
    result = backend.refine(
        RefinementModel(
            phases=(warm,), free_params=frozenset({param_name(0, "lattice.a")}),
            two_theta=tt, intensity=observed,
        )
    )
    assert math.isfinite(result.chi2)
    assert result.n_params == 1, "立方晶なのに 3 と数えている (BIC の母数が過大)"
    refined = result.phases[0].lattice
    assert refined.a == pytest.approx(refined.b) == pytest.approx(refined.c), (
        "従属軸が読み戻せていない (Get(a) の参照式を解いていない)"
    )
    assert abs(refined.a - 5.463) < abs(5.470 - 5.463), "真値へ寄っていない"


# ---------------- 既定重みの共有 (chi2 セマンティクスの統一) ----------------


def test_default_weights_are_shared_with_the_other_backends():
    """``weights`` 未指定時の統計重みは**バックエンド横断で 1 つの定義**であること。

    TopasBackend だけ ``w=1`` だったため、同じ実データ・同じ実 CIF で chi2 が
    1.4e9 (TOPAS) 対 6.8e5 (GSAS-II) と数桁ずれていた (**格子は 0.07% 以内で一致**)。
    判別 (`discriminate`) は ``close_threshold`` という**絶対 ΔBIC の閾値**を両エンジンに
    同じ値で使うので、重みがずれると「僅差かどうか」がエンジン依存になる。
    """
    import inspect

    from tsumugin.backends import simulated
    from tsumugin.backends.base import default_weights
    from tsumugin.backends.topas import default_weights as topas_default

    assert topas_default is default_weights, "TOPAS 側が別定義を持っている"
    assert "default_weights" in inspect.getsource(simulated.SimulatedBackend.refine), (
        "SimulatedBackend が共有定義を使っていない"
    )
    y = np.array([0.0, 0.5, 1.0, 100.0])
    assert np.allclose(default_weights(y), 1.0 / np.maximum(y, 1.0))


# ---------------- 2 エンジンが同じ構造へ収束するか (#180 の前提, M12 最重要の観測点) ----


_PBSO4_CIF = Path("docs/benchmark/testdata/PbSO4-Wyckoff.cif")
_PBSO4_XRA = Path("docs/benchmark/testdata/m7/cwcombined/PBSO4.XRA")


@pytest.mark.gsas
@pytest.mark.topas
@pytest.mark.skipif(
    not (_PBSO4_CIF.is_file() and _PBSO4_XRA.is_file()),
    reason="実データが無い (gitignore 対象で CI には存在しない)",
)
def test_both_backends_recover_the_same_cell_from_the_same_real_cif():
    """**同じ実 CIF・同じ実データ・同じ摂動**から両エンジンが同じ格子へ収束すること。

    `discriminate(backend=)` を許した前提はここにある — TOPAS 側が簡約モデルへ戻ると、
    ③ から見て「実構造で判別した」結果が捏造構造で走り、**その嘘は結果からは見えない**。
    格子が一致することは、両者が本当に同じ構造を読んでいることの検算になる。

    実測 (2026-08-19, 真値 8.482/5.398/6.959 から 0.4% 摂動した 8.45/5.38/6.94 を出発点):
    TOPAS 8.47648/5.40376/6.95684 と GSAS-II 8.48207/5.40312/6.96325 で最大 0.066% 差。
    """
    from tsumugin.backends.gsasii import GSASIIBackend
    from tsumugin.reference.io import load_pattern

    x, y = load_pattern(str(_PBSO4_XRA), "GSAS")
    window = (x >= 20.0) & (x <= 90.0)
    warm = PhaseInstance(
        phase_ref="PbSO4",
        lattice=LatticeParams(8.45, 5.38, 6.94),
        scale=1.0,
        structure_ref=str(_PBSO4_CIF),
    )
    model = RefinementModel(
        phases=(warm,),
        free_params=frozenset({param_name(0, "scale"), param_name(0, "lattice.a")}),
        two_theta=x[window],
        intensity=y[window],
    )
    cells = {}
    for name, backend in (("topas", TopasBackend()), ("gsasii", GSASIIBackend())):
        lattice = backend.refine(model, max_cycles=20).phases[0].lattice
        cells[name] = (lattice.a, lattice.b, lattice.c)

    reference = (8.482, 5.398, 6.959)
    for name, cell in cells.items():
        for axis, (got, want) in enumerate(zip(cell, reference)):
            assert abs(got - want) / want < 0.003, f"{name} の軸 {axis} が真値から遠い: {got}"
    for axis, (t_val, g_val) in enumerate(zip(cells["topas"], cells["gsasii"])):
        assert abs(t_val - g_val) / g_val < 0.002, (
            f"2 エンジンの軸 {axis} が食い違う: TOPAS {t_val} / GSAS {g_val}。"
            "どちらかが違う構造を読んでいる"
        )
