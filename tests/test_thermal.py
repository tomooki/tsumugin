"""TASK-0018 thermal (sequential/thermal.py) の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/sequential/thermal.py``:
  - ``fit_thermal_baseline(temperatures, values, *, degree=1) -> ThermalBaseline``
    格子-温度曲線の熱膨張ベースラインを多項式 (既定 1 次) でフィットし、残差の中央値/MAD
    ロバスト z 超過フレームを ``outlier_frames`` (転移候補) として分離する純関数。
  - ``estimate_transition(temperatures, fractions, *, phase_ref) -> TransitionEstimate | None``
    相分率シグモイド遷移から転移温度を onset (10%) / midpoint (50% 線形補間) ± σ で推定する
    純関数。遷移が無い場合 (定数分率・交差なし・点数不足) は ``None`` を返す。
  - 値オブジェクト ``ThermalBaseline`` / ``TransitionEstimate`` (frozen dataclass)。
- ``src/tsumugin/sequential/__init__.py``: 上記シンボルの re-export。

書式は ``tests/test_changepoint.py`` (TASK-0015) を範とし、決定論検証は ``==`` (pytest.approx 禁止)、
係数/温度近似は ``pytest.approx``、非有限漏洩検査は ``math.isfinite``、frozen は ``FrozenInstanceError``。
テストケース定義 (thermal 18 件: 正常系 7 / 異常系 6 / 境界値 5) に対応する。

対象モジュール未実装のため import が collection 時に失敗し、本ファイルの全テストがエラー(=失敗)になる想定 (Red)。
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from tsumugin.sequential.thermal import (
    ThermalBaseline,
    TransitionEstimate,
    estimate_transition,
    fit_thermal_baseline,
)

# 純関数のため状態を持たず、合成データはモジュールレベルで一度だけ構築する。

# 20 フレーム・10 K 刻みの温度軸 (300..490 K)。TB-N01 / TE-N01 系で共有。
TEMPS_20 = [300.0 + 10.0 * i for i in range(20)]

# TB-N01 / TC-105-03: 線形熱膨張 a = 5.0 + 1e-4*(T-300) に、構造相転移 (格子ジャンプ) を表す
# +0.02 をフレーム 12・13 へ付与した合成格子列。
# 【Red 較正】: 素の polyfit で 1 次係数が真値近傍 (≈1.18e-4, rel<0.3) に復元でき、残差ロバスト z が
#   転移フレームを明瞭に分離 (z[12]≈12 ≫ 正常フレーム z≤1) できるよう、ジャンプ幅と対象フレーム数を較正。
LINEAR_BASE_20 = [5.0 + 1e-4 * (t - 300.0) for t in TEMPS_20]
JUMP_FRAMES = (12, 13)
JUMP_VALUES_20 = [LINEAR_BASE_20[i] + (0.02 if i in JUMP_FRAMES else 0.0) for i in range(20)]

# TB-N02 / N03 / E01 / E03: 純線形 values = 2.0 + 0.5*T (切片 2.0 ≠ 傾き 0.5 で係数順序を判別可能)。
PURE_LINEAR_TEMPS = [0.0, 1.0, 2.0, 3.0, 4.0]
PURE_LINEAR_VALUES = [2.0 + 0.5 * t for t in PURE_LINEAR_TEMPS]

# TB-N04: 二次多項式 values = 1.0 + 0.2*T + 0.01*T^2 (degree=2 の汎用性検証)。
QUAD_TEMPS = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
QUAD_VALUES = [1.0 + 0.2 * t + 0.01 * t * t for t in QUAD_TEMPS]

# TE-N01 / B02 / B03 / E03: 中心 400 K・幅 15 の増加シグモイド (0→1)。midpoint 真値 = 400 K。
SIGMOID_UP = [1.0 / (1.0 + math.exp(-(t - 400.0) / 15.0)) for t in TEMPS_20]
# TE-N02: 減少シグモイド (1→0)。相が昇温で消滅する遷移の代表。
SIGMOID_DOWN = [1.0 / (1.0 + math.exp((t - 400.0) / 15.0)) for t in TEMPS_20]


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_baseline_linear_with_jump_separates_outliers():
    # 【テスト目的】: 線形熱膨張+ジャンプで 1 次係数真値近傍・逸脱フレーム分離を確認 (TB-N01 / TC-105-03)
    # 【テスト内容】: 20 フレーム線形格子 + フレーム 12・13 ジャンプで fit_thermal_baseline を呼ぶ
    # 【期待される動作】: 1 次係数 (傾き) が真値 1e-4 近傍、ジャンプフレームが outlier_frames に入る
    # 🔵 信頼性レベル: 受け入れ基準 TC-105-03 / REQ-007 に直接依拠 (合成値は Red 較正)

    # 【テストデータ準備】: 線形熱膨張 (5.0+1e-4*ΔT) にフレーム 12・13 で +0.02 ジャンプを付与
    # 【初期条件設定】: temperatures は 300..490 の 10 K 刻み、degree 既定 1
    baseline = fit_thermal_baseline(TEMPS_20, JUMP_VALUES_20)

    # 【結果検証】: 係数が真値近傍かつ逸脱フレームが正しく分離され、正常フレームを誤検出しないこと
    # 【期待値確認】: 傾き ≈1e-4 (rel 0.3)、ジャンプフレーム 12 が逸脱、滑らかフレーム 0 は非逸脱
    assert isinstance(baseline, ThermalBaseline)  # 【確認内容】: 戻り値が ThermalBaseline 型 🔵
    assert baseline.coefficients[1] == pytest.approx(1e-4, rel=0.3)  # 【確認内容】: 傾きが真値近傍 🔵
    assert 12 in baseline.outlier_frames  # 【確認内容】: ジャンプフレームが逸脱判定される 🔵
    assert 0 not in baseline.outlier_frames  # 【確認内容】: 正常フレームは誤検出しない 🔵


def test_baseline_coefficients_low_to_high_order():
    # 【テスト目的】: coefficients が低次→高次の順で格納されること (polyfit 反転) を確認 (TB-N02)
    # 【テスト内容】: 純線形 values=2.0+0.5*T で fit_thermal_baseline を呼び係数順序を検査
    # 【期待される動作】: coefficients = (切片 2.0, 傾き 0.5)。numpy.polyfit の高次→低次を反転して格納
    # 🟡 信頼性レベル: interfaces.py L178「低次から」注記 (🟡) に依拠

    # 【テストデータ準備】: 切片 2.0 ≠ 傾き 0.5 で係数の順序を明確に判別できる純線形入力
    # 【初期条件設定】: temperatures=[0..4]、degree 既定 1
    baseline = fit_thermal_baseline(PURE_LINEAR_TEMPS, PURE_LINEAR_VALUES)

    # 【結果検証】: polyfit の返り順を鵜呑みにせず「低次から」の契約を守っていること (off-by-order 検出)
    # 【期待値確認】: coefficients[0]=切片 2.0、coefficients[1]=傾き 0.5
    assert baseline.coefficients[0] == pytest.approx(2.0)  # 【確認内容】: 低次 (切片) が先頭 🟡
    assert baseline.coefficients[1] == pytest.approx(0.5)  # 【確認内容】: 高次 (傾き) が後 🟡


def test_baseline_residuals_pointwise_length_and_finite():
    # 【テスト目的】: residuals が点毎 (実測-フィット値) で values と同長・同順・有限であること (TB-N03)
    # 【テスト内容】: 純線形入力で fit_thermal_baseline を呼び residuals の定義・長さ・有限性を検査
    # 【期待される動作】: len(residuals)==len(values)、完全線形なので全残差ほぼ 0、非有限漏洩なし
    # 🔵 信頼性レベル: interfaces.py L179 residuals 契約 + CLAUDE.md 非有限漏洩に依拠

    # 【テストデータ準備】: 残差の定義 (SSR 単一値でなく点毎残差) を明確に検証できる純線形入力
    # 【初期条件設定】: temperatures=[0..4]、degree 既定 1
    baseline = fit_thermal_baseline(PURE_LINEAR_TEMPS, PURE_LINEAR_VALUES)

    # 【結果検証】: 逸脱判定は点毎残差列に対して行うため、点毎の残差が values と同長で有限であること
    # 【期待値確認】: 長さ一致・全残差 |r|<1e-9・全て math.isfinite
    assert len(baseline.residuals) == len(PURE_LINEAR_VALUES)  # 【確認内容】: 点毎残差で同長 🔵
    assert all(abs(r) < 1e-9 for r in baseline.residuals)  # 【確認内容】: 完全線形で残差ほぼ 0 🔵
    assert all(math.isfinite(r) for r in baseline.residuals)  # 【確認内容】: inf/nan を漏らさない 🔵


def test_baseline_degree_two_quadratic_fit():
    # 【テスト目的】: degree=2 指定で 2 次多項式がフィットされ係数 3 要素になること (TB-N04)
    # 【テスト内容】: values=1.0+0.2*T+0.01*T^2 を degree=2 でフィットし係数と長さを検査
    # 【期待される動作】: len(coefficients)==3、係数が真値 (1.0,0.2,0.01) 近傍、低次から
    # 🟡 信頼性レベル: interfaces.py の degree 引数から妥当な推測

    # 【テストデータ準備】: 高次熱膨張 (非線形) を表す二次曲線。degree を 1 に固定していないことを検証
    # 【初期条件設定】: temperatures=[0..5]、degree=2 (キーワード専用)
    baseline = fit_thermal_baseline(QUAD_TEMPS, QUAD_VALUES, degree=2)

    # 【結果検証】: degree=n で係数 n+1 個、低次から真値近傍に復元されること
    # 【期待値確認】: 係数長 3、(1.0, 0.2, 0.01) に一致
    assert len(baseline.coefficients) == 3  # 【確認内容】: degree=2 で係数 3 要素 🟡
    assert baseline.coefficients == pytest.approx((1.0, 0.2, 0.01), rel=1e-3)  # 【確認内容】: 真値近傍 🟡


def test_transition_sigmoid_up_midpoint_onset_sigma():
    # 【テスト目的】: 増加シグモイド遷移で midpoint±1 間隔・onset<midpoint・σ>0 を確認 (TE-N01 / TC-105-04)
    # 【テスト内容】: 中心 400 K のシグモイド分率 (0→1) で estimate_transition を呼ぶ
    # 【期待される動作】: midpoint≈400 (±10 K=±1 間隔)、onset<midpoint、σ>0、direction="appearing"
    # 🔵 信頼性レベル: 受け入れ基準 TC-105-04 / REQ-008 に直接依拠 (合成値は Red 較正)

    # 【テストデータ準備】: 相が昇温で出現する 50% 交差 400 K のシグモイド遷移 (TC-105-04 の合成データ)
    # 【初期条件設定】: temperatures 300..490 の 10 K 刻み、phase_ref 指定
    est = estimate_transition(TEMPS_20, SIGMOID_UP, phase_ref="phase_A")

    # 【結果検証】: 50% 交差の線形補間で midpoint≈400、10% 交差の onset は低温側、σ は遷移幅で正
    # 【期待値確認】: 転移が検出され (None でない)、midpoint±10K・onset<midpoint・σ>0・appearing
    assert est is not None  # 【確認内容】: 遷移が検出される 🔵
    assert isinstance(est, TransitionEstimate)  # 【確認内容】: 戻り値が TransitionEstimate 型 🔵
    assert abs(est.midpoint - 400.0) <= 10.0  # 【確認内容】: midpoint が真値 ±1 フレーム間隔 🔵
    assert est.onset < est.midpoint  # 【確認内容】: onset(10%) は midpoint(50%) より低温側 🔵
    assert est.sigma > 0.0  # 【確認内容】: σ が正 🔵
    assert est.direction == "appearing"  # 【確認内容】: 増加基調は出現方向 🟡
    assert math.isfinite(est.midpoint)  # 【確認内容】: midpoint に inf/nan を漏らさない 🔵


def test_transition_sigmoid_down_direction_disappearing():
    # 【テスト目的】: 減少シグモイド (1→0) で direction="disappearing"・onset=遷移開始側 (TE-N02 / TC-T-N02)
    # 【テスト内容】: 中心 400 K の減少シグモイド分率で estimate_transition を呼ぶ
    # 【期待される動作】: direction="disappearing"、midpoint≈400 (方向非依存に 50% 交差)、σ>0、onset<midpoint
    # 🔵 信頼性レベル: TASK-0024 要件定義 §2 真理値表 / D-Q8 (L44-48) / interfaces.py L372-373 に依拠

    # 【テストデータ準備】: 相が昇温で消滅する 1→0 の減少シグモイド遷移 (方向判定・onset 意味論の検証)
    # 【初期条件設定】: temperatures 300..490、phase_ref 指定
    est = estimate_transition(TEMPS_20, SIGMOID_DOWN, phase_ref="phase_A")

    # 【結果検証】: 分率が減少基調なら disappearing、midpoint は 50% 交差で方向非依存に推定されること
    # 【期待値確認】: direction="disappearing"、midpoint≈400、σ>0
    assert est is not None  # 【確認内容】: 遷移が検出される 🔵
    assert est.direction == "disappearing"  # 【確認内容】: 減少基調は消滅方向 🟡
    assert est.midpoint == pytest.approx(400.0, abs=10.0)  # 【確認内容】: midpoint は方向非依存 🟡
    assert est.sigma > 0.0  # 【確認内容】: σ が正 🟡

    # TASK-0024 (Issue #4): disappearing の onset は 90% 交差=遷移開始側 (低温側) を指すべき。
    # 旧実装は direction 非依存に 10% 交差 (≈433.54 K, onset>midpoint) を返し「遷移開始温度」を誤読させた。
    # 90% 交差 (≈366.46 K) へ切り替わり onset<midpoint となることを追加固定する (TC-T-N02, 理由コメント付き最小修正)。
    assert est.onset is not None  # 【確認内容】: disappearing でも onset が縮退せず算出される 🔵
    assert est.onset < est.midpoint  # 【確認内容】: onset は遷移開始側 (低温側, < midpoint) 🔵
    assert math.isfinite(est.onset)  # 【確認内容】: onset に inf/nan を漏らさない 🔵


def test_transition_phase_ref_preserved():
    # 【テスト目的】: 入力 phase_ref が TransitionEstimate.phase_ref にそのまま保持されること (TE-N03)
    # 【テスト内容】: phase_ref="phase_B" を渡して結果の phase_ref を検査
    # 【期待される動作】: 任意識別子が加工・上書きされず透過的に保持される
    # 🔵 信頼性レベル: interfaces.py L187 phase_ref に直接依拠

    # 【テストデータ準備】: 複数相の推定結果を区別する識別子の透過性を検証
    # 【初期条件設定】: TE-N01 と同じ増加シグモイド、phase_ref="phase_B"
    est = estimate_transition(TEMPS_20, SIGMOID_UP, phase_ref="phase_B")

    # 【結果検証】: 識別子が加工されずそのまま格納されること
    # 【期待値確認】: est.phase_ref == "phase_B"
    assert est is not None  # 【確認内容】: 遷移が検出される 🔵
    assert est.phase_ref == "phase_B"  # 【確認内容】: phase_ref が透過保持される 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（縮退の非例外化・非破壊契約）
# ---------------------------------------------------------------------------


def test_baseline_perfect_fit_no_outliers_no_nonfinite():
    # 【テスト目的】: 完全フィット (残差 MAD=0) で outlier_frames=() ・非有限漏洩なしを確認 (TB-E01)
    # 【テスト内容】: 残差が全 0 になる純線形入力で fit_thermal_baseline を呼ぶ
    # 【期待される動作】: 例外なし・outlier_frames=()・全残差が有限 (MAD=0 の 0 除算を縮退で回避)
    # 🔵 信頼性レベル: CLAUDE.md 非有限漏洩禁止 / changepoint.py MAD=0 縮退パターンに依拠

    # 【テストデータ準備】: 熱膨張が完全に線形で逸脱が一切ない安定加熱区間 (残差全 0 の縮退)
    # 【初期条件設定】: 純線形 values=2.0+0.5*T、degree 既定 1
    baseline = fit_thermal_baseline(PURE_LINEAR_TEMPS, PURE_LINEAR_VALUES)

    # 【結果検証】: 散布度ゼロ (MAD=0) でクラッシュ・誤検出せず、inf/nan を下流へ漏らさないこと
    # 【期待値確認】: outlier_frames が空タプル、全残差が math.isfinite
    assert baseline.outlier_frames == ()  # 【確認内容】: 逸脱なしは空タプルに縮退 🔵
    assert all(math.isfinite(r) for r in baseline.residuals)  # 【確認内容】: inf/nan を漏らさない 🔵


def test_baseline_insufficient_points_degrades_without_exception():
    # 【テスト目的】: 点数不足 (len < degree+1) で例外化せず縮退すること (TB-E02)
    # 【テスト内容】: 1 点 (degree=1 は 2 点必要) で fit_thermal_baseline を呼ぶ
    # 【期待される動作】: 例外を送出せず ThermalBaseline を返し、outlier_frames=()・非有限を含まない
    # 🟡 信頼性レベル: changepoint.py warm-up 縮退思想からの妥当な推測 (縮退値は Green で確定)

    # 【テストデータ準備】: 単一フレーム区間・欠損後の断片 (最小二乗解が一意でない縮退)
    # 【初期条件設定】: temperatures=[300.0]、values=[5.0]、degree=1 (2 点必要に対し 1 点)
    baseline = fit_thermal_baseline([300.0], [5.0], degree=1)

    # 【結果検証】: 母数不足を例外化せず安全側縮退へ一元化し、非有限を漏らさないこと
    # 【期待値確認】: ThermalBaseline を返す・outlier_frames=()・係数/残差が全て有限
    assert isinstance(baseline, ThermalBaseline)  # 【確認内容】: 縮退でも値オブジェクトを返す 🟡
    assert baseline.outlier_frames == ()  # 【確認内容】: 逸脱なしに縮退 🟡
    assert all(math.isfinite(c) for c in baseline.coefficients)  # 【確認内容】: 係数に inf/nan なし 🔵
    assert all(math.isfinite(r) for r in baseline.residuals)  # 【確認内容】: 残差に inf/nan なし 🔵


def test_thermal_baseline_is_frozen():
    # 【テスト目的】: ThermalBaseline が frozen で再代入不可を確認 (TB-E03)
    # 【テスト内容】: 生成した ThermalBaseline の coefficients へ再代入し FrozenInstanceError を検証
    # 【期待される動作】: frozen=True のため属性再代入で FrozenInstanceError (不変性=再現性の担保)
    # 🔵 信頼性レベル: interfaces.py L173 @dataclass(frozen=True) / CLAUDE.md frozen 規約に依拠

    # 【テストデータ準備】: 結果オブジェクトの事後改変 (実行中の誤った書き換え) の防御を検証
    # 【初期条件設定】: 純線形入力で ThermalBaseline を生成
    baseline = fit_thermal_baseline(PURE_LINEAR_TEMPS, PURE_LINEAR_VALUES)

    # 【結果検証】: 状態改変が型レベルで禁止されていること
    # 【期待値確認】: coefficients への再代入が FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        baseline.coefficients = (0.0,)  # type: ignore[misc]  # 【確認内容】: baseline が frozen 🔵


def test_transition_constant_fraction_returns_none():
    # 【テスト目的】: 定数分率 (遷移なし) で None を返すこと (TE-E01)
    # 【テスト内容】: 全フレーム 0.5 の定数分率で estimate_transition を呼ぶ
    # 【期待される動作】: 50% 交差の遷移が起きない → None (偽の転移温度を出さない)
    # 🔵 信頼性レベル: interfaces.py L201「遷移が無い場合は None」/ 完了条件「定数分率で None 🔵」に依拠

    # 【テストデータ準備】: 相が全区間で安定 (等温セグメント) を表す定数分率
    # 【初期条件設定】: fractions=[0.5]*20、temperatures 300..490、phase_ref="A"
    result = estimate_transition(TEMPS_20, [0.5] * 20, phase_ref="A")

    # 【結果検証】: 交差なしを None で表現し、偽の onset/midpoint を返さないこと (false-positive 抑制)
    # 【期待値確認】: 戻り値が None
    assert result is None  # 【確認内容】: 遷移なしは None に縮退 🔵


def test_transition_empty_or_single_frame_returns_none():
    # 【テスト目的】: 空入力・単一フレームで None を返すこと (TE-E02)
    # 【テスト内容】: (a) 空 (b) 単一フレームで estimate_transition を呼ぶ
    # 【期待される動作】: 補間に必要な隣接対 (点数>=2) が作れない → 両ケースとも None・例外なし
    # 🟡 信頼性レベル: 受け入れ基準 EDGE-001/101 (空・単一) の思想からの妥当な推測

    # 【テストデータ準備】: 空トラジェクトリ・単一フレーム区間 (端末フレーム) を再現
    # 【初期条件設定】: (a) 空リスト、(b) 単一温度 400 K + 分率 0.5
    empty_result = estimate_transition([], [], phase_ref="A")
    single_result = estimate_transition([400.0], [0.5], phase_ref="A")

    # 【結果検証】: 母数不足を None へ一元化し、端末フレームでクラッシュしないこと
    # 【期待値確認】: 空・単一とも None
    assert empty_result is None  # 【確認内容】: 空入力は None に縮退 🟡
    assert single_result is None  # 【確認内容】: 単一フレームは None に縮退 🟡


def test_transition_estimate_is_frozen():
    # 【テスト目的】: TransitionEstimate が frozen で再代入不可を確認 (TE-E03)
    # 【テスト内容】: 生成した TransitionEstimate の midpoint へ再代入し FrozenInstanceError を検証
    # 【期待される動作】: frozen=True のため属性再代入で FrozenInstanceError (不変性=再現性の担保)
    # 🔵 信頼性レベル: interfaces.py L183 @dataclass(frozen=True) に依拠

    # 【テストデータ準備】: 推定結果オブジェクトの事後改変 (実行中の誤った書き換え) の防御を検証
    # 【初期条件設定】: 増加シグモイドで TransitionEstimate を生成
    est = estimate_transition(TEMPS_20, SIGMOID_UP, phase_ref="phase_A")

    # 【結果検証】: 状態改変が型レベルで禁止されていること
    # 【期待値確認】: midpoint への再代入が FrozenInstanceError
    assert est is not None  # 【確認内容】: 遷移が検出される (frozen 検証の前提) 🔵
    with pytest.raises(FrozenInstanceError):
        est.midpoint = 0.0  # type: ignore[misc]  # 【確認内容】: est が frozen 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（最小点数・交差境界・決定論）
# ---------------------------------------------------------------------------


def test_baseline_minimum_points_equal_degree_plus_one():
    # 【テスト目的】: 最小点数 (len == degree+1) でフィット可能なこと (TB-B01)
    # 【テスト内容】: 2 点 (degree=1) で fit_thermal_baseline を呼び、縮退でなくフィット実行を検証
    # 【期待される動作】: 例外なし・len(coefficients)==2・2 点直線を完全に通す (残差ほぼ 0)・逸脱なし
    # 🟡 信頼性レベル: polyfit の数学的要件 (len==degree+1 が解ける下限) からの妥当な推測

    # 【テストデータ準備】: 最短の有効トラジェクトリ (TB-E02 の点数不足と対称な下限境界)
    # 【初期条件設定】: temperatures=[300,310]、values=[5.0,5.001]、degree=1 (2 点==degree+1)
    baseline = fit_thermal_baseline([300.0, 310.0], [5.0, 5.001], degree=1)

    # 【結果検証】: len==degree+1 は縮退でなくフィット実行され、2 点直線を正しく通すこと
    # 【期待値確認】: 係数長 2・残差ほぼ 0・outlier_frames=()
    assert len(baseline.coefficients) == 2  # 【確認内容】: degree=1 で係数 2 要素 🟡
    assert all(abs(r) < 1e-9 for r in baseline.residuals)  # 【確認内容】: 2 点直線は完全フィット 🟡
    assert baseline.outlier_frames == ()  # 【確認内容】: 逸脱なし 🟡


def test_baseline_deterministic_bit_identical():
    # 【テスト目的】: fit_thermal_baseline が同一入力 2 回でビット同一 (TB-B02 / TC-105-05)
    # 【テスト内容】: 逸脱分離を含む TB-N01 合成データで 2 回独立に呼び == を検証
    # 【期待される動作】: 純関数で乱数・順序依存がなく、coefficients/residuals/outlier_frames 全一致
    # 🔵 信頼性レベル: 受け入れ基準 TC-105-05 / NFR-102 / REQ-402 に直接依拠

    # 【テストデータ準備】: 逸脱分離を含む複雑な入力で丸め揺らぎゼロを検証 (監査・再現)
    # 【初期条件設定】: 決定論は「ほぼ同じ」不可 — pytest.approx 禁止、== 比較
    baseline1 = fit_thermal_baseline(TEMPS_20, JUMP_VALUES_20)
    baseline2 = fit_thermal_baseline(TEMPS_20, JUMP_VALUES_20)

    # 【結果検証】: float フィールド含め全フィールドが構造的に等価であること
    # 【期待値確認】: frozen dataclass の == と outlier_frames タプルの一致
    assert baseline1 == baseline2  # 【確認内容】: 2 回呼び出しがビット同一 (決定論) 🔵
    assert baseline1.outlier_frames == baseline2.outlier_frames  # 【確認内容】: 逸脱集合も同一 🔵


def test_transition_crossing_on_grid_point():
    # 【テスト目的】: 50% 交差がフレーム端点ちょうどに一致する補間境界を確認 (TE-B01)
    # 【テスト内容】: index 2 の分率が正確に 0.5 になる分率列で estimate_transition を呼ぶ
    # 【期待される動作】: 端点一致でも一意な midpoint≈400 を返し、0 除算・重複補間しない
    # 🟡 信頼性レベル: 線形補間 (interfaces.py midpoint 契約) からの妥当な推測

    # 【テストデータ準備】: 分率がグリッド上で丁度 50% になるフレーム (補間端点一致の罠)
    # 【初期条件設定】: fractions=[0,0.25,0.5,0.75,1.0]、temperatures=[300,350,400,450,500]
    est = estimate_transition(
        [300.0, 350.0, 400.0, 450.0, 500.0], [0.0, 0.25, 0.5, 0.75, 1.0], phase_ref="A"
    )

    # 【結果検証】: 交差点がグリッド上にあっても補間が破綻せず一意な温度を返すこと
    # 【期待値確認】: midpoint==400、非有限漏洩なし
    assert est is not None  # 【確認内容】: 遷移が検出される 🟡
    assert est.midpoint == pytest.approx(400.0)  # 【確認内容】: 端点一致でも midpoint=400 🟡
    assert math.isfinite(est.midpoint)  # 【確認内容】: midpoint に inf/nan を漏らさない 🟡


def test_transition_onset_before_midpoint_and_sigma_positive():
    # 【テスト目的】: onset<midpoint の順序と σ が隣接フレーム間隔ベースで正であること (TE-B02)
    # 【テスト内容】: 増加シグモイド (0→1) で onset(10%)/midpoint(50%)/σ の相対関係を検査
    # 【期待される動作】: onset<midpoint、σ>0 かつ有限、σ が隣接フレーム間隔 (10 K) のオーダー
    # 🟡 信頼性レベル: interfaces.py onset=10%/σ=隣接間隔 (🟡 interview Q6) に依拠

    # 【テストデータ準備】: 転移の立ち上がり幅を評価する解析 (10%/50% 交差の相対位置と σ 定義)
    # 【初期条件設定】: TE-N01 のシグモイド (中心 400 K, 幅 15)
    est = estimate_transition(TEMPS_20, SIGMOID_UP, phase_ref="A")

    # 【結果検証】: onset は必ず midpoint より遷移前側、σ は正の間隔ベース値で非有限を返さないこと
    # 【期待値確認】: onset<midpoint・σ>0・σ が有限
    assert est is not None  # 【確認内容】: 遷移が検出される 🟡
    assert est.onset < est.midpoint  # 【確認内容】: onset(10%) < midpoint(50%) 🟡
    assert est.sigma > 0.0  # 【確認内容】: σ が正 🟡
    assert math.isfinite(est.sigma)  # 【確認内容】: σ に 0/負/非有限を返さない 🟡


def test_transition_deterministic_bit_identical():
    # 【テスト目的】: estimate_transition が同一入力 2 回でビット同一 (TE-B03 / TC-105-05)
    # 【テスト内容】: 補間・方向判定を含む増加シグモイドで 2 回独立に呼び == を検証
    # 【期待される動作】: 純関数で乱数・順序依存がなく onset/midpoint/sigma/direction/phase_ref 全一致
    # 🔵 信頼性レベル: 受け入れ基準 TC-105-05 / NFR-102 / REQ-402 に直接依拠

    # 【テストデータ準備】: 補間・方向判定を含む推定で丸め揺らぎゼロを検証 (監査・再現)
    # 【初期条件設定】: 決定論は「ほぼ同じ」不可 — pytest.approx 禁止、== 比較
    est1 = estimate_transition(TEMPS_20, SIGMOID_UP, phase_ref="A")
    est2 = estimate_transition(TEMPS_20, SIGMOID_UP, phase_ref="A")

    # 【結果検証】: float フィールド含め全フィールドが構造的に等価であること
    # 【期待値確認】: frozen dataclass の == で全フィールド一致
    assert est1 == est2  # 【確認内容】: 2 回呼び出しがビット同一 (決定論) 🔵


# ---------------------------------------------------------------------------
# 4. TASK-0024: onset 意味論修正 (Issue #4) — disappearing の onset を 90% 交差=遷移開始側へ
#    ⚠️ 期待順序: 90% 交差メカニズム + 数値検証により両方向とも onset < midpoint (遷移開始側=低温側)。
#       TASK-0024.md/TC-208-01 の「disappearing: onset > midpoint」表記は誤記のため onset < midpoint で固定。
#       SIGMOID_DOWN 実測交差: 90% ≈ 366.46 K < 50% = 400 K < 10% ≈ 433.54 K。
# ---------------------------------------------------------------------------

# 【onset 交差レベルの具体温度 (SIGMOID_DOWN, 中心 400 K・幅 15・線形補間の実測値)】:
#   90% 交差 ≈ 366.46 K (新: disappearing onset=遷移開始側) / 10% 交差 ≈ 433.54 K (旧: 誤って高温側)。
_DISAPPEARING_ONSET_90PCT = 366.46  # disappearing の正しい onset (90% 交差=低温側) 🔵
_DISAPPEARING_ONSET_10PCT_OLD = 433.54  # 旧実装の誤 onset (10% 交差=高温側)。修正後は返してはならない 🔵


def test_transition_disappearing_onset_is_ninety_pct_value():
    # 【テスト目的】: disappearing の onset が 90% 交差の具体値 (≈366.46 K) で、旧 10% 交差 (≈433.54 K) でないこと (TC-T-N03)
    # 【テスト内容】: 減少シグモイド (1→0) で estimate_transition を呼び onset の値レベルを固定検証
    # 【期待される動作】: onset ≈ 366.46 K (90% 交差=低温側)、onset < midpoint。旧値 433.54 K を返さない
    # 🔵 信頼性レベル: 要件定義 §2 具体値表 / 数値検証 (90% 交差=366.46 K) に直接依拠

    # 【テストデータ準備】: onset が「10%→90% 交差」へ切り替わったことを具体値で明示的に固定 (回帰防止)
    # 【初期条件設定】: TEMPS_20 (300..490 K)、SIGMOID_DOWN、phase_ref 指定
    est = estimate_transition(TEMPS_20, SIGMOID_DOWN, phase_ref="phase_A")

    # 【結果検証】: 90% 交差レベルを使ったこと (旧実装は 433.54 K を返し本 assert が落ちる) を値レベルで固定
    # 【期待値確認】: onset≈366.46 K、旧 433.54 K でない、onset<midpoint
    assert est is not None and est.direction == "disappearing"  # 【確認内容】: disappearing 遷移 🔵
    assert est.onset == pytest.approx(_DISAPPEARING_ONSET_90PCT, abs=1.0)  # 【確認内容】: onset=90% 交差値 🔵
    assert est.onset != pytest.approx(_DISAPPEARING_ONSET_10PCT_OLD, abs=1.0)  # 【確認内容】: 旧 10% 値でない 🔵
    assert est.onset < est.midpoint  # 【確認内容】: onset は遷移開始側 (低温側) 🔵


def test_transition_disappearing_shallow_below_ninety_returns_none():
    # 【テスト目的】: 90%/50% を横切らない浅い disappearing 遷移は例外化せず None へ縮退 (TC-T-E01)
    # 【テスト内容】: 分率が 0.90/0.50 を割らない微減トラジェクトリ (1.0→0.924) で estimate_transition を呼ぶ
    # 【期待される動作】: midpoint (50%) 交差が無いため None。onset レベル変更は縮退の前段を壊さない
    # 🟡 信頼性レベル: 要件定義 §4 エッジ (90% 未達→None) / 既存 _interpolate_crossing の None 経路に依拠

    # 【テストデータ準備】: 相がわずかに減るだけで消滅しない区間 (0.9 を割らない微減=遷移未確定)
    # 【初期条件設定】: fractions=[1.0-0.004*i] (1.0→0.924)、TEMPS_20、phase_ref="A"
    shallow = [1.0 - 0.004 * i for i in range(20)]
    result = estimate_transition(TEMPS_20, shallow, phase_ref="A")

    # 【結果検証】: 交差なしを None で表現し、偽の onset/midpoint・非有限を漏らさないこと
    # 【期待値確認】: 戻り値が None
    assert result is None  # 【確認内容】: 90%/50% 未達は None に縮退 (非例外化) 🟡


def test_transition_disappearing_ninety_pct_on_grid_point():
    # 【テスト目的】: disappearing で分率がちょうど 90% の端点一致でも一意な onset・0 除算なし (TC-T-B01)
    # 【テスト内容】: index 1 の分率が丁度 0.90、index 2 が丁度 0.50 の分率列で estimate_transition を呼ぶ
    # 【期待される動作】: onset=350 K (90% 端点一致)、midpoint=400 K (50% 端点一致)、onset<midpoint、有限
    # 🟡 信頼性レベル: 既存 _interpolate_crossing の端点一致契約 / 要件定義 §4 エッジに依拠

    # 【テストデータ準備】: 分率がグリッド上で丁度 90%/50% になるフレーム (端点一致の罠を突く)
    # 【初期条件設定】: temperatures=[300,350,400,450,500]、fractions=[1.0,0.9,0.5,0.1,0.0]
    est = estimate_transition(
        [300.0, 350.0, 400.0, 450.0, 500.0], [1.0, 0.9, 0.5, 0.1, 0.0], phase_ref="A"
    )

    # 【結果検証】: 90% 端点一致で onset=350、50% 端点一致で midpoint=400、0 除算・NaN なし
    # 【期待値確認】: onset≈350、midpoint≈400、onset<midpoint、onset 有限
    assert est is not None and est.direction == "disappearing"  # 【確認内容】: disappearing 遷移 🟡
    assert est.onset == pytest.approx(350.0)  # 【確認内容】: 90% 端点一致 onset=350 K 🟡
    assert est.midpoint == pytest.approx(400.0)  # 【確認内容】: 50% 端点一致 midpoint=400 K 🟡
    assert est.onset < est.midpoint and math.isfinite(est.onset)  # 【確認内容】: 遷移開始側・有限 🟡


def test_transition_direction_tie_is_appearing_with_ten_pct_onset():
    # 【テスト目的】: direction 判定の等号境界 (fractions[-1]==fractions[0]) は appearing 側で onset=10% レベル (TC-T-B02)
    # 【テスト内容】: 始終端が等値 (0.0) の山型分率で estimate_transition を呼び direction/onset を検査
    # 【期待される動作】: direction="appearing" (等号は appearing 側)、onset<midpoint (前半上昇の 10% 交差)
    # 🟡 信頼性レベル: 既存 direction 判定式 (fractions[-1]>=fractions[0]) / 要件定義 §2 真理値表に依拠

    # 【テストデータ準備】: 出現後に再消滅する山型分率 (始終端 0.0 で等号境界に当たる)
    # 【初期条件設定】: temperatures=[300,350,400,450,500]、fractions=[0.0,0.5,1.0,0.5,0.0]
    est = estimate_transition(
        [300.0, 350.0, 400.0, 450.0, 500.0], [0.0, 0.5, 1.0, 0.5, 0.0], phase_ref="A"
    )

    # 【結果検証】: 等号で appearing に確定し、onset は 10% 交差 (前半の低温側) で midpoint より前側
    # 【期待値確認】: direction="appearing"、onset<midpoint
    assert est is not None  # 【確認内容】: 遷移が検出される 🟡
    assert est.direction == "appearing"  # 【確認内容】: 始終端等値は appearing 側に倒れる 🟡
    assert est.onset < est.midpoint  # 【確認内容】: appearing の onset は 10% 交差=低温側 🟡


def test_transition_disappearing_deterministic_bit_identical():
    # 【テスト目的】: disappearing 経路 (90% 交差) の決定論ビット同一 (TC-T-B03)
    # 【テスト内容】: 減少シグモイドで 2 回独立に estimate_transition を呼び == を検証
    # 【期待される動作】: onset レベル選択を含め同一入力 2 回で TransitionEstimate が == (ビット同一)
    # 🔵 信頼性レベル: 要件定義 §3 (決定論 NFR-102) / 既存 test_transition_deterministic_bit_identical の disappearing 版

    # 【テストデータ準備】: 90% 交差経路の丸め揺らぎゼロを検証 (監査・再現性)。決定論は pytest.approx 禁止・== 比較
    # 【初期条件設定】: TEMPS_20、SIGMOID_DOWN、phase_ref="A" を 2 回
    e1 = estimate_transition(TEMPS_20, SIGMOID_DOWN, phase_ref="A")
    e2 = estimate_transition(TEMPS_20, SIGMOID_DOWN, phase_ref="A")

    # 【結果検証】: onset/midpoint/sigma/direction/phase_ref の全フィールドが構造的に等価であること
    # 【期待値確認】: frozen dataclass の == で全フィールド一致
    assert e1 == e2  # 【確認内容】: 2 回呼び出しがビット同一 (disappearing 経路も決定論) 🔵


@pytest.mark.parametrize("fractions", [SIGMOID_DOWN, SIGMOID_UP])
def test_transition_no_nonfinite_leak_both_directions(fractions):
    # 【テスト目的】: onset レベル変更後も inf/nan を下流へ漏らさない (両方向, TC-T-B04)
    # 【テスト内容】: disappearing/appearing 双方で onset/midpoint/sigma の有限性 (or None) を検査
    # 【期待される動作】: onset は有限 or None、midpoint は有限、sigma は有限 or None。inf/nan を返さない
    # 🔵 信頼性レベル: 要件定義 §3 (非有限漏洩なし) / CLAUDE.md / 既存 math.isfinite 検査方針に依拠

    # 【テストデータ準備】: JSON/CSV 配信前の値純化前提 (非有限禁止)。90% 交差経路も対象に含める
    # 【初期条件設定】: TEMPS_20、SIGMOID_DOWN / SIGMOID_UP をパラメータ化、phase_ref="A"
    est = estimate_transition(TEMPS_20, fractions, phase_ref="A")

    # 【結果検証】: 有限値は math.isfinite、交差なしは None のみ。inf/nan を一切下流へ渡さないこと
    # 【期待値確認】: onset (有限 or None)・midpoint 有限・sigma (有限 or None)
    assert est is not None  # 【確認内容】: 遷移が検出される 🔵
    assert est.onset is None or math.isfinite(est.onset)  # 【確認内容】: onset は有限 or None 🔵
    assert math.isfinite(est.midpoint)  # 【確認内容】: midpoint に inf/nan なし 🔵
    assert est.sigma is None or math.isfinite(est.sigma)  # 【確認内容】: sigma は有限 or None 🔵
