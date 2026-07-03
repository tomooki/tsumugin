"""TASK-0026 backends 拡張 (global パラメータ文法 + 吸収補正 v1) の失敗テスト (TDD Red)。

対象実装 (本フェーズでは未実装):
- ``src/tsumugin/absorption/model.py`` (新設): ``AbsorptionConfig`` frozen dataclass +
  ``AbsorptionConfig.from_cell_config`` / ``AbsorptionConfig.empirical`` staticmethod +
  ``transmission_factor(two_theta_deg, mu_t)`` = exp(-μt/cosθ)。
- ``src/tsumugin/backends/base.py``: ``parse_param("global.mu_t") -> (-1, "mu_t")`` 追加、
  ``RefinementResult`` 末尾に ``globals: Mapping[str, float]`` / ``warnings: tuple[str, ...]`` 追加。
- ``src/tsumugin/backends/simulated.py``: ``SimulatedBackend(absorption=...)`` 追加。simulate は
  透過因子を乗算、refine は ``"global.mu_t"`` を restraint 付きで精密化し globals へ記録。
- ``src/tsumugin/backends/gsasii.py``: v1 吸収は scale 畳み込み近似である旨を docstring 明記 (REQ-020)。

すべて既定値付きの非破壊追加 (REQ-404)。``tsumugin.absorption.model`` は未作成のため、当該シンボルを
参照する各テストは呼び出し時に ``ModuleNotFoundError`` / ``TypeError`` / ``AttributeError`` /
``ValueError`` で失敗する想定 (Red フェーズ)。既存挙動の非干渉を守る T-E01 / 前タスク充足済みの
T-E05 は回帰確認として通過する (仕様どおり)。テストケース定義 (26 件: 正常系 13 / 異常系 5 /
境界値 8) に 1:1 対応する。書式は ``tests/test_simulated_backend.py`` /
``tests/test_backend_interface.py`` を範とする。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from tsumugin.backends.base import (
    RefinementModel,
    RefinementResult,
    param_name,
    parse_param,
)
from tsumugin.backends.gsasii import GSASIIBackend
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import CellConfig, LatticeParams, PhaseInstance, XraylibMuCalculator


# ---- 共通ヘルパ (tests/test_simulated_backend.py 準拠) ----------------------


def _phase(a: float = 5.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    """試験用 PhaseInstance (立方近似格子)。"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _grid() -> np.ndarray:
    """既存 SimulatedBackend テストと同域の合成 2θ グリッド。"""
    return np.arange(15.0, 80.0, 0.02)


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_transmission_factor_matches_formula_and_monotone():
    # 【テスト目的】: transmission_factor が exp(-μt/cosθ) と一致し 2θ 増加で吸収減となることを確認 (T-N01)
    # 【テスト内容】: μt=0.5 の合成グリッドで理論式一致・低角ほど小・全域 (0,1) を検証
    # 【期待される動作】: A(θ;μt)=exp(-μt/cosθ)、θ=radians(2θ/2)。factor[0] < factor[-1]
    # 🔵 信頼性: requirements 2.3 / architecture.md D8 L96 / interfaces.py L112-114 に依拠

    # 【テストデータ準備】: 合成グリッド (既存 _grid 同域) + 現実的中程度吸収 μt=0.5
    from tsumugin.absorption.model import transmission_factor

    tt = np.arange(15.0, 80.0, 0.02)
    factor = transmission_factor(tt, 0.5)

    # 【結果検証】: 理論式一致と単調傾向・値域を確認
    expected = np.exp(-0.5 / np.cos(np.radians(tt / 2.0)))
    assert np.allclose(factor, expected)  # 【確認内容】: 半角変換込みで理論式に一致 🔵
    assert factor.shape == tt.shape  # 【確認内容】: 形状が入力と同一 🔵
    # A=exp(-μt/cosθ) は θ 増加で cosθ 減 → μt/cosθ 増 → 単調減少。高角ほど吸収が強い。
    assert factor[0] > factor[-1]  # 【確認内容】: 高角ほど小 (吸収が強い) 🔵
    assert np.all(factor > 0.0)  # 【確認内容】: 吸収因子は正 🔵
    assert np.all(factor < 1.0)  # 【確認内容】: μt>0 では全域 1 未満 🔵


def test_transmission_factor_specific_angles():
    # 【テスト目的】: 既知角での透過因子の数値正確性を確認 (T-N02)
    # 【テスト内容】: 2θ=0°(θ=0, cosθ=1) と 2θ=60°(θ=30°) で数値一致を検証
    # 【期待される動作】: factor[0]=exp(-1)、factor[1]=exp(-1/cos30°)
    # 🔵 信頼性: 式 A(θ;μt)=exp(-μt/cosθ) の直接評価に依拠

    from tsumugin.absorption.model import transmission_factor

    factor = transmission_factor(np.array([0.0, 60.0]), 1.0)

    assert factor[0] == pytest.approx(np.exp(-1.0))  # 【確認内容】: θ→0 で exp(-μt) 🔵
    assert factor[1] == pytest.approx(
        np.exp(-1.0 / np.cos(np.radians(30.0)))
    )  # 【確認内容】: cosθ 分母計算が正しい 🔵


def test_parse_param_global_returns_minus_one_index():
    # 【テスト目的】: parse_param("global.mu_t") が (-1, "mu_t") を返すことを確認 (T-N03)
    # 【テスト内容】: head=="global" で相インデックス -1、tail を抽出する文法拡張を検証
    # 【期待される動作】: (-1, "mu_t")。-1 は「大域 (どの相にも属さない)」の標識
    # 🔵 信頼性: interfaces.py L93 / architecture.md D8 L94 に依拠

    # 【実際の処理実行】: 大域パラメータ名を解析 (未実装なら現状 ValueError で失敗)
    assert parse_param("global.mu_t") == (-1, "mu_t")  # 【確認内容】: 大域標識 -1 と tail 抽出 🔵


def test_refinement_result_holds_globals_and_warnings():
    # 【テスト目的】: RefinementResult が新規末尾フィールド globals/warnings を保持することを確認 (T-N04)
    # 【テスト内容】: globals/warnings を明示指定して生成し値の保持を検証
    # 【期待される動作】: .globals=={"mu_t":0.42}、.warnings==("w1",)
    # 🔵 信頼性: interfaces.py L95 / requirements 2.2 に依拠

    # 【テストデータ準備】: fitted μt 記録 + 警告文字列を持つ精密化結果を再現
    r = RefinementResult(
        phases=(), chi2=1.0, rwp=2.0, n_obs=2, n_params=1, converged=True, n_cycles=3,
        free_params=frozenset({"global.mu_t"}), globals={"mu_t": 0.42}, warnings=("w1",),
    )

    assert r.globals == {"mu_t": 0.42}  # 【確認内容】: Mapping フィールドが保持される 🔵
    assert r.warnings == ("w1",)  # 【確認内容】: tuple フィールドが保持される 🔵


def test_absorption_config_defaults_and_explicit_fields():
    # 【テスト目的】: AbsorptionConfig が既定値/明示値で生成できフィールドを保持することを確認 (T-N05)
    # 【テスト内容】: 既定生成と全指定生成の 2 通りでフィールド値を検証
    # 【期待される動作】: 既定 mu_t_initial=0.0 / mu_t_calc=None / restraint_weight=100.0 / empirical_mode=False
    # 🔵 信頼性: interfaces.py L97-104 / requirements 2.3 に依拠

    from tsumugin.absorption.model import AbsorptionConfig

    default = AbsorptionConfig()
    assert default.mu_t_initial == pytest.approx(0.0)  # 【確認内容】: 初期 μt 既定 0.0 🔵
    assert default.mu_t_calc is None  # 【確認内容】: restraint 中心 既定 None 🔵
    assert default.restraint_weight == pytest.approx(100.0)  # 【確認内容】: w_r 既定 100.0 (強) 🔵
    assert default.empirical_mode is False  # 【確認内容】: 経験モード 既定 False 🔵

    explicit = AbsorptionConfig(
        mu_t_initial=0.3, mu_t_calc=0.5, restraint_weight=50.0, empirical_mode=False
    )
    assert explicit.mu_t_initial == pytest.approx(0.3)  # 【確認内容】: 明示 mu_t_initial 保持 🔵
    assert explicit.mu_t_calc == pytest.approx(0.5)  # 【確認内容】: 明示 mu_t_calc 保持 🔵
    assert explicit.restraint_weight == pytest.approx(50.0)  # 【確認内容】: 明示 w_r 保持 🔵


def test_from_cell_config_with_mu_t_builds_strong_restraint():
    # 【テスト目的】: from_cell_config(mu_t_calc あり) が強 restraint 構成を返すことを確認 (T-N06)
    # 【テスト内容】: CellConfig.mu_t_calc=0.6 を restraint 中心かつ初期値に採る挙動を検証
    # 【期待される動作】: mu_t_calc=0.6 / mu_t_initial=0.6 / restraint_weight=100.0 / empirical_mode=False
    # 🔵 信頼性: requirements 2.3 / REQ-017/019 / architecture.md D8 L99 に依拠

    from tsumugin.absorption.model import AbsorptionConfig

    # 【テストデータ準備】: μt 算出済みの透過セル (MuCalculator/xraylib は呼ばず mu_t_calc を読むだけ)
    cfg = AbsorptionConfig.from_cell_config(CellConfig(geometry="transmission", mu_t_calc=0.6))

    assert cfg.mu_t_calc == pytest.approx(0.6)  # 【確認内容】: restraint 中心に μt_calc を採用 🔵
    assert cfg.mu_t_initial == pytest.approx(0.6)  # 【確認内容】: 初期値にも μt_calc を採用 🔵
    assert cfg.restraint_weight == pytest.approx(100.0)  # 【確認内容】: 強 restraint (100.0) 🔵
    assert cfg.empirical_mode is False  # 【確認内容】: 経験モードでない 🔵


def test_empirical_builds_weak_restraint_mode():
    # 【テスト目的】: empirical() が弱 restraint + 経験モード構成を返すことを確認 (T-N07)
    # 【テスト内容】: CellConfig 未提供ファクトリの各フィールドを検証
    # 【期待される動作】: mu_t_calc=None / restraint_weight=1.0 (弱) / empirical_mode=True
    # 🔵 信頼性: interfaces.py L103/109 / REQ-018 に依拠 (w_r=1.0 は 🟡 既定値)

    from tsumugin.absorption.model import AbsorptionConfig

    cfg = AbsorptionConfig.empirical()

    assert cfg.mu_t_calc is None  # 【確認内容】: 経験推定は restraint 中心なし 🔵
    assert cfg.restraint_weight == pytest.approx(1.0)  # 【確認内容】: 弱 restraint (1.0) 🟡
    assert cfg.empirical_mode is True  # 【確認内容】: 経験モード True 🔵


def test_simulate_multiplies_transmission_factor():
    # 【テスト目的】: absorption 設定時 simulate 出力が無補正出力×透過因子となることを確認 (T-N08)
    # 【テスト内容】: 無補正 backend と μt=0.5 補正 backend の simulate を比較
    # 【期待される動作】: y1 ≈ y0 * transmission_factor(tt, 0.5)。ピーク位置は不変
    # 🔵 信頼性: requirements 2.4 / architecture.md D8 L95-96 / REQ-020 に依拠

    from tsumugin.absorption.model import AbsorptionConfig, transmission_factor

    tt = _grid()
    phase = _phase(a=5.0, scale=2.0)
    y0 = SimulatedBackend(peak_fwhm=0.2).simulate((phase,), tt)
    y1 = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.5)
    ).simulate((phase,), tt)

    assert np.allclose(y1, y0 * transmission_factor(tt, 0.5))  # 【確認内容】: 透過因子の一様乗算 🔵


def test_refine_recovers_true_mu_t_within_restraint():
    # 【テスト目的】: μt>0 生成データを μt=0 初期から精密化し真値を restraint 内で回収する (T-N09/TC-207-02)
    # 【テスト内容】: 真値 μt=0.5 で生成 → 初期 μt=0・restraint 中心 0.5 で refine
    # 【期待される動作】: converged かつ globals["mu_t"] ≈ 0.5 (abs=0.05)
    # 🔵 信頼性: acceptance-criteria TC-207-02 / REQ-017 に依拠 (許容幅 abs=0.05 は 🟡)

    from tsumugin.absorption.model import AbsorptionConfig

    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
    y = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.5)
    ).simulate((truth,), tt)

    # 【初期条件設定】: μt=0 初期 + restraint 中心 0.5・強 w_r。scale も併走解放
    backend = SimulatedBackend(
        peak_fwhm=0.2,
        absorption=AbsorptionConfig(mu_t_initial=0.0, mu_t_calc=0.5, restraint_weight=100.0),
    )
    model = RefinementModel(
        phases=(_phase(a=5.0, scale=2.0),),
        free_params=frozenset({"global.mu_t", param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)

    assert result.converged  # 【確認内容】: μt 追加後も収束する 🔵
    assert result.globals["mu_t"] == pytest.approx(0.5, abs=0.05)  # 【確認内容】: 真値回収 🔵


def test_restraint_pulls_solution_toward_center():
    # 【テスト目的】: 強 restraint が中心から遠い解を抑制することを確認 (T-N10/TC-207-03)
    # 【テスト内容】: 中心 0.3 から遠い (真 μt≈0.8) データを強/弱 w_r で refine し中心距離を比較
    # 【期待される動作】: |強w_r 解 - 0.3| < |弱w_r 解 - 0.3|
    # 🔵 信頼性: acceptance-criteria TC-207-03 / requirements 2.4 に依拠

    from tsumugin.absorption.model import AbsorptionConfig

    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
    y = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.8)
    ).simulate((truth,), tt)

    model = RefinementModel(
        phases=(_phase(a=5.0, scale=2.0),),
        free_params=frozenset({"global.mu_t", param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    strong = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.0, mu_t_calc=0.3, restraint_weight=100.0)
    ).refine(model)
    weak = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.0, mu_t_calc=0.3, restraint_weight=1.0)
    ).refine(model)

    assert abs(strong.globals["mu_t"] - 0.3) < abs(
        weak.globals["mu_t"] - 0.3
    )  # 【確認内容】: 強 w_r ほど中心へ引き戻される 🔵


def test_empirical_mode_emits_warning_with_back_calculated_mu_t():
    # 【テスト目的】: 経験推定モードが warnings に経験モード明示 + 逆算 μt を出すことを確認 (T-N11/TC-207-04)
    # 【テスト内容】: empirical() 構成で refine し globals["mu_t"] と warnings を検証
    # 【期待される動作】: globals に mu_t、warnings が非空で「経験」/「empirical」相当を含む
    # 🔵 信頼性: acceptance-criteria TC-207-04 / REQ-018 に依拠 (警告文面は 🟡)

    from tsumugin.absorption.model import AbsorptionConfig

    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
    y = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.5)
    ).simulate((truth,), tt)

    backend = SimulatedBackend(peak_fwhm=0.2, absorption=AbsorptionConfig.empirical())
    model = RefinementModel(
        phases=(_phase(a=5.0, scale=2.0),),
        free_params=frozenset({"global.mu_t", param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)

    assert "mu_t" in result.globals  # 【確認内容】: 弱 restraint でも μt が精密化される 🔵
    assert result.warnings  # 【確認内容】: 経験推定モードで警告が必ず出る 🔵
    assert any(
        ("経験" in w) or ("empirical" in w.lower()) for w in result.warnings
    )  # 【確認内容】: 経験推定モード明示 + 逆算 μt 提示 🔵


def test_refine_free_params_and_globals_coexist():
    # 【テスト目的】: global.mu_t 解放時に free_params と globals が整合することを確認 (T-N12)
    # 【テスト内容】: {"global.mu_t","phase0.scale"} 解放で両パラメータが共存精密化されるか検証
    # 【期待される動作】: free_params に両名、globals に "mu_t"
    # 🔵 信頼性: architecture.md D8 / requirements 2.4 に依拠

    from tsumugin.absorption.model import AbsorptionConfig

    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
    y = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.5)
    ).simulate((truth,), tt)

    backend = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.0, mu_t_calc=0.5)
    )
    model = RefinementModel(
        phases=(_phase(a=5.0, scale=2.0),),
        free_params=frozenset({"global.mu_t", param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)

    assert "global.mu_t" in result.free_params  # 【確認内容】: 大域パラメータが解放記録される 🔵
    assert "mu_t" in result.globals  # 【確認内容】: fitted μt が globals に記録 🔵
    assert param_name(0, "scale") in result.free_params  # 【確認内容】: 相パラメータも従来どおり解放 🔵


def test_gsasii_docstring_documents_scale_convolution_approximation():
    # 【テスト目的】: GSASIIBackend docstring が v1 吸収=scale 畳み込み近似である旨を明記することを確認 (T-N13)
    # 【テスト内容】: GSASIIBackend.__doc__ に吸収 + scale/畳み込み相当語が含まれるかを検証 (import のみ)
    # 【期待される動作】: docstring に「吸収」/「absorption」かつ「scale」/「畳み込み」相当を含む
    # 🟡 信頼性: architecture.md D8 L101 / REQ-020 に依拠 (docstring 文面は裁量)

    doc = GSASIIBackend.__doc__ or ""

    assert ("吸収" in doc) or ("absorption" in doc.lower())  # 【確認内容】: 吸収への言及 🟡
    assert ("scale" in doc.lower()) or ("畳み込み" in doc)  # 【確認内容】: scale 畳み込み近似の明記 🟡


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（エラーハンドリング）
# ---------------------------------------------------------------------------


def test_parse_param_rejects_invalid_names():
    # 【テスト目的】: global 分岐追加後も不正名/tail 空を従来どおり拒否することを確認 (T-E01)
    # 【テスト内容】: phase/global いずれでもない名前・tail 空・ドットなしで ValueError を検証
    # 【期待される動作】: いずれも ValueError (既存の厳格性を緩めない)
    # 🔵 信頼性: src/tsumugin/backends/base.py L60-61 の既存挙動 + 追加分岐の境界に依拠

    # 【品質保証の観点】: global 分岐が既存 phase 経路の fail-loud を壊していないこと
    for bad in ("foo.bar", "global", "", "globalmu_t"):
        with pytest.raises(ValueError):  # 【確認内容】: 正準文法非合致は沈黙採用せず拒否 🔵
            parse_param(bad)


def test_refinement_result_is_frozen():
    # 【テスト目的】: 新フィールド追加後も RefinementResult が frozen であることを確認 (T-E02)
    # 【テスト内容】: globals/warnings を持つ結果を生成し再代入で FrozenInstanceError を検証
    # 【期待される動作】: 再代入は dataclasses.FrozenInstanceError で拒否される
    # 🔵 信頼性: tests/test_backend_interface.py L41-42 の frozen 検証パターンに依拠

    r = RefinementResult(
        phases=(), chi2=1.0, rwp=2.0, n_obs=2, n_params=1, converged=True, n_cycles=3,
        free_params=frozenset({"global.mu_t"}), globals={"mu_t": 0.42}, warnings=("w1",),
    )

    with pytest.raises(FrozenInstanceError):
        r.globals = {}  # type: ignore[misc]  # 【確認内容】: 不変値オブジェクトへの再代入拒否 🔵


def test_absorption_config_is_frozen():
    # 【テスト目的】: AbsorptionConfig のフィールド再代入が禁止されることを確認 (T-E03)
    # 【テスト内容】: mu_t_initial への再代入を試みる
    # 【期待される動作】: dataclasses.FrozenInstanceError が送出される
    # 🔵 信頼性: frozen dataclass 規約 (CLAUDE.md) / interfaces.py L97 に依拠

    from tsumugin.absorption.model import AbsorptionConfig

    cfg = AbsorptionConfig(mu_t_initial=0.5)

    with pytest.raises(FrozenInstanceError):
        cfg.mu_t_initial = 1.0  # type: ignore[misc]  # 【確認内容】: frozen のため再代入不可 🔵


def test_restraint_overrun_emits_correlation_warning():
    # 【テスト目的】: fitted μt が restraint 幅を超えて逸脱したとき相関疑い警告を出すことを確認 (T-E04/TC-207-06)
    # 【テスト内容】: 中心 0.2 に対し真 μt≈1.0 のデータを弱 restraint で refine し警告を検証
    # 【期待される動作】: warnings 非空で「相関」/「restraint」/「逸脱」相当を含む
    # 🔵 信頼性: acceptance-criteria TC-207-06 / REQ-103 / §14 に依拠 (許容幅定義は 🟡 設計裁量)

    from tsumugin.absorption.model import AbsorptionConfig

    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
    y = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=1.0)
    ).simulate((truth,), tt)

    # 【初期条件設定】: restraint 中心 0.2・弱 w_r で、中心から遠い解 (≈1.0) へ収束させる
    backend = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.0, mu_t_calc=0.2, restraint_weight=1.0)
    )
    model = RefinementModel(
        phases=(_phase(a=5.0, scale=2.0),),
        free_params=frozenset({"global.mu_t", param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)

    assert result.warnings  # 【確認内容】: 逸脱時は沈黙せず警告付きで返す 🔵
    assert any(
        ("相関" in w) or ("restraint" in w.lower()) or ("逸脱" in w) for w in result.warnings
    )  # 【確認内容】: §14 相関リスクをユーザー/エージェントへ通知 🔵


def test_fitted_mu_t_beyond_restraint_width_emits_literal_warning():
    # 【テスト目的】: fitted μt が restraint_width を超えて逸脱したとき、rwp が閾値未満 (良好適合) でも
    #   字義どおりの相関疑い警告を出すことを確認 (T-E06/REQ-103 字義)。rwp ベース補完シグナルとは独立に
    #   「顕在的逸脱」を検出できることを保証する (Green は rwp 閾値ベースのみ実装だった)。
    # 【テスト内容】: 真 μt=1.0 の合成データを restraint 中心 0.2・極弱 restraint・scale 固定で refine。
    #   scale を解放しないため μt–scale 相関が起きず μt はデータ選好 (≈1.0) へ収束し、rwp は小さいまま
    #   中心 0.2 から restraint_width=0.3 を超えて逸脱する (逸脱を強制する合成ケース)。
    # 【期待される動作】: |fitted μt − 0.2| > 0.3 かつ rwp < 0.5 (rwp 補完シグナル不発) かつ
    #   warnings に「幅逸脱」/「逸脱」相当を含む。
    # 🔵 信頼性: REQ-103 字義 / requirements 2.4 / §14 に依拠 (restraint_width=0.3 は 🟡 設計裁量)

    from tsumugin.absorption.model import AbsorptionConfig

    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
    y = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=1.0)
    ).simulate((truth,), tt)

    # 【初期条件設定】: 中心 0.2・極弱 restraint (w_r=0.001)・scale 真値固定 (free_params に scale 無し)
    backend = SimulatedBackend(
        peak_fwhm=0.2,
        absorption=AbsorptionConfig(
            mu_t_initial=0.0, mu_t_calc=0.2, restraint_weight=0.001, restraint_width=0.3
        ),
    )
    model = RefinementModel(
        phases=(_phase(a=5.0, scale=2.0),),
        free_params=frozenset({"global.mu_t"}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)

    assert abs(result.globals["mu_t"] - 0.2) > 0.3  # 【確認内容】: 中心から許容幅 0.3 超で逸脱 🔵
    assert result.rwp < 0.5  # 【確認内容】: rwp 補完シグナルは不発 (良好適合) — 字義判定が単独で発火 🔵
    assert result.warnings  # 【確認内容】: 逸脱時は沈黙せず警告付きで返す 🔵
    assert any(
        ("幅逸脱" in w) or ("逸脱" in w) for w in result.warnings
    )  # 【確認内容】: 字義どおりの restraint 幅逸脱 (REQ-103) を通知 🔵


def test_xraylib_mu_calculator_still_not_implemented():
    # 【テスト目的】: 組成→μt が M3 未実装 (NotImplementedError) のままであることを回帰確認 (T-E05/TC-207-07)
    # 【テスト内容】: XraylibMuCalculator().mu_t(CellConfig) の送出例外を検証
    # 【期待される動作】: NotImplementedError (本タスクは xraylib へ実依存を持ち込まない)
    # 🔵 信頼性: acceptance-criteria TC-207-07 / src/tsumugin/model/cell.py L90-97 に依拠

    # 【品質保証の観点】: REQ-403 コア依存 numpy のみ (TASK-0025 で確立、本タスクは回帰のみ通過)
    with pytest.raises(NotImplementedError):  # 【確認内容】: 未実装は fail-loud で拒否 🔵
        XraylibMuCalculator().mu_t(CellConfig(geometry="transmission"))


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（最小値・境界・null・回帰）
# ---------------------------------------------------------------------------


def test_transmission_factor_mu_t_zero_is_all_one():
    # 【テスト目的】: transmission_factor(μt=0) が全域 1.0 となることを確認 (T-B01/EDGE-006)
    # 【テスト内容】: μt=0 (吸収なし) の境界で exp(0)=1 を検証
    # 【期待される動作】: 全要素が 1.0 (補正因子 1 = 無補正の代数的保証)
    # 🔵 信頼性: EDGE-006 / acceptance-criteria TC-207-05 / interfaces.py L113 に依拠

    from tsumugin.absorption.model import transmission_factor

    factor = transmission_factor(np.arange(15.0, 80.0, 0.02), 0.0)

    assert np.allclose(factor, 1.0)  # 【確認内容】: μt=0 で全域 1.0 (無補正境界) 🔵


def test_simulate_absorption_none_bit_identical():
    # 【テスト目的】: absorption=None の simulate が無補正経路とビット一致することを確認 (T-B02)
    # 【テスト内容】: absorption 省略 backend と absorption=None backend の simulate を比較
    # 【期待される動作】: np.array_equal (ビット一致)。既存経路を壊さない
    # 🔵 信頼性: REQ-404 非破壊 / EDGE-006 / tests/test_simulated_backend.py に依拠

    tt = _grid()
    phase = _phase(a=5.0, scale=2.0)
    reference = SimulatedBackend(peak_fwhm=0.2).simulate((phase,), tt)
    y = SimulatedBackend(peak_fwhm=0.2, absorption=None).simulate((phase,), tt)

    assert np.array_equal(y, reference)  # 【確認内容】: absorption=None は乗算スキップでビット一致 🔵


def test_simulate_absorption_mu_t_zero_bit_identical():
    # 【テスト目的】: absorption 設定ありでも μt=0 なら無補正とビット一致することを確認 (T-B03/TC-207-05)
    # 【テスト内容】: mu_t_initial=0.0 の AbsorptionConfig を渡した simulate を無補正と比較
    # 【期待される動作】: np.array_equal (補正因子 1)
    # 🔵 信頼性: acceptance-criteria TC-207-05 / EDGE-006 に依拠

    from tsumugin.absorption.model import AbsorptionConfig

    tt = _grid()
    phase = _phase(a=5.0, scale=2.0)
    reference = SimulatedBackend(peak_fwhm=0.2).simulate((phase,), tt)
    y = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.0)
    ).simulate((phase,), tt)

    assert np.array_equal(y, reference)  # 【確認内容】: μt=0 設定でも無補正一致 🔵


def test_globals_empty_when_mu_t_not_freed():
    # 【テスト目的】: global.mu_t 未解放時は μt を精密化せず globals が空になることを確認 (T-B04)
    # 【テスト内容】: absorption 設定ありだが free_params に global.mu_t を含めず refine
    # 【期待される動作】: globals == {} (μt はフィット対象外)、scale のみ精密化
    # 🟡 信頼性: requirements 2.4 (globals 記録は解放時のみ) からの妥当推測

    from tsumugin.absorption.model import AbsorptionConfig

    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
    backend = SimulatedBackend(peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.4))
    y = backend.simulate((truth,), tt)

    model = RefinementModel(
        phases=(_phase(a=5.0, scale=1.0),),
        free_params=frozenset({param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)

    assert result.globals == {}  # 【確認内容】: 未解放なら μt はフィットされず globals 空 🟡


def test_refine_with_mu_t_is_deterministic():
    # 【テスト目的】: μt 解放込みの refine を 2 回実行してビット同一になることを確認 (T-B05/NFR-102)
    # 【テスト内容】: 同一 RefinementModel を 2 回 refine し chi2/globals/warnings/phases を比較
    # 【期待される動作】: すべてビット同一 (乱数不使用の決定論拡張)
    # 🔵 信頼性: NFR-102 / REQ-402 / tests/test_simulated_backend.py::test_deterministic に依拠

    from tsumugin.absorption.model import AbsorptionConfig

    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
    y = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.5)
    ).simulate((truth,), tt)

    backend = SimulatedBackend(
        peak_fwhm=0.2,
        absorption=AbsorptionConfig(mu_t_initial=0.0, mu_t_calc=0.5, restraint_weight=100.0),
    )
    model = RefinementModel(
        phases=(_phase(a=5.0, scale=2.0),),
        free_params=frozenset({"global.mu_t", param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    r1 = backend.refine(model)
    r2 = backend.refine(model)

    assert r1.chi2 == r2.chi2  # 【確認内容】: chi2 がビット同一 🔵
    assert r1.globals["mu_t"] == r2.globals["mu_t"]  # 【確認内容】: fitted μt がビット同一 🔵
    assert r1.warnings == r2.warnings  # 【確認内容】: 警告列がビット同一 🔵
    assert r1.phases == r2.phases  # 【確認内容】: 相状態がビット同一 🔵


def test_refinement_result_defaults_globals_and_warnings_empty():
    # 【テスト目的】: 新フィールド省略の既存生成が globals={} / warnings=() で成立することを確認 (T-B06)
    # 【テスト内容】: 7 引数 (新フィールド省略) で RefinementResult を生成し既定値を検証
    # 【期待される動作】: 生成成功、.globals=={}、.warnings==() (後方互換)
    # 🔵 信頼性: REQ-404 / tests/test_backend_interface.py L38-40 の既存生成に依拠

    r = RefinementResult(
        phases=(), chi2=1.0, rwp=2.0, n_obs=2, n_params=0, converged=True, n_cycles=1
    )

    assert r.globals == {}  # 【確認内容】: 追加フィールド globals の既定 {} 🔵
    assert r.warnings == ()  # 【確認内容】: 追加フィールド warnings の既定 () 🔵


def test_from_cell_config_none_falls_back_to_empirical():
    # 【テスト目的】: from_cell_config(mu_t_calc=None) が経験推定へフォールバックすることを確認 (T-B07)
    # 【テスト内容】: mu_t_calc 未算出 (既定 None) の CellConfig から構成を生成し検証
    # 【期待される動作】: empirical_mode=True / mu_t_calc=None / restraint_weight=1.0 (= empirical() 相当)
    # 🟡 信頼性: requirements 2.3 のフォールバック方針 (REQ-018 から妥当推測)

    from tsumugin.absorption.model import AbsorptionConfig

    cfg = AbsorptionConfig.from_cell_config(CellConfig(geometry="transmission"))

    assert cfg.empirical_mode is True  # 【確認内容】: μt 未算出は経験推定へフォールバック 🟡
    assert cfg.mu_t_calc is None  # 【確認内容】: restraint 中心なし 🟡
    assert cfg.restraint_weight == pytest.approx(1.0)  # 【確認内容】: 弱 restraint (1.0) 🟡


def test_extension_is_nondestructive_regression_gate():
    # 【テスト目的】: 拡張全体が既存資産を壊さない非破壊追加であることを確認 (T-B08)
    # 【テスト内容】: 既存生成/既存文法の不変 (回帰) と、新規追加面 (absorption/globals) の存在を検証
    # 【期待される動作】: 既存 7 引数生成・phase 文法が不変、かつ absorption モジュールと新フィールドが追加済み
    # 🔵 信頼性: CLAUDE.md 不変条件 / REQ-404 / note.md ベースライン (477 collected) に依拠

    # 【回帰】: 既存 RefinementResult 生成 (7 引数) と既存 phase 文法が無改変で成立
    legacy = RefinementResult(
        phases=(), chi2=1.0, rwp=2.0, n_obs=2, n_params=0, converged=True, n_cycles=1
    )
    assert legacy.chi2 == pytest.approx(1.0)  # 【確認内容】: 既存生成経路が壊れない 🔵
    assert parse_param(param_name(0, "scale")) == (0, "scale")  # 【確認内容】: phase 文法が不変 🔵

    # 【新規追加面】: absorption モジュールと RefinementResult 新フィールドが非破壊追加されている
    # (全体 477 collected の無退行維持は tdd-verify-complete / CI の `uv run pytest` で最終確認する)
    from tsumugin.absorption.model import AbsorptionConfig, transmission_factor

    assert callable(transmission_factor)  # 【確認内容】: 透過因子関数が追加済み 🔵
    assert AbsorptionConfig().restraint_weight == pytest.approx(100.0)  # 【確認内容】: 設定 dataclass 追加済み 🔵
    assert legacy.globals == {}  # 【確認内容】: 末尾追加フィールド globals の既定 {} 🔵
    assert legacy.warnings == ()  # 【確認内容】: 末尾追加フィールド warnings の既定 () 🔵


def test_absorption_config_restraint_width_default_and_explicit():
    # 【テスト目的】: restraint_width が既定 0.3 で保持され明示上書きできることを確認 (T-B09)
    # 【テスト内容】: 既定生成と明示生成で restraint_width フィールド値を検証 (末尾フィールド非破壊追加)
    # 【期待される動作】: 既定 0.3 / 明示値を保持。REQ-103 字義の許容幅を設定として明示保持する
    # 🟡 信頼性: REQ-103 の許容幅を保持するフィールド (既定 0.3 は設計裁量)

    from tsumugin.absorption.model import AbsorptionConfig

    assert AbsorptionConfig().restraint_width == pytest.approx(0.3)  # 【確認内容】: 既定 0.3 🟡
    assert AbsorptionConfig(restraint_width=0.15).restraint_width == pytest.approx(
        0.15
    )  # 【確認内容】: 明示上書きを保持 🟡
