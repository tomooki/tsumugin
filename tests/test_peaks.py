"""TASK-0002 観測ピーク検出 find_peaks の失敗テスト (TDD Red フェーズ)。

対象実装: ``src/tsumugin/search/peaks.py``（未実装）。
`Peak` frozen dataclass と `find_peaks(two_theta, intensity, *, min_height_frac=0.05)` を検証する。
テストデータは `SimulatedBackend`（決定論・乱数不使用）で生成し、真のピーク位置と照合する。
書式は `tests/test_simulated_backend.py` を範とする（モジュールレベルヘルパ + pytest.approx）。
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance

# 未実装のため、この import が collection 時に失敗し全テストがエラー(=失敗)になる想定。
from tsumugin.search.peaks import Peak, find_peaks


# 【テストデータ準備】: 単相 PhaseInstance を最小構成で生成（既存テストの _phase を踏襲）
def _phase(a: float = 5.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


# 【初期条件設定】: 合成 2θ 軸（15〜80°, 0.02° 刻み）。既存テストの _grid と同一
def _grid() -> np.ndarray:
    return np.arange(15.0, 80.0, 0.02)


# 【前提条件確認】: FWHM=0.2° 固定の決定論バックエンド（乱数不使用）
def _backend() -> SimulatedBackend:
    return SimulatedBackend(peak_fwhm=0.2)


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_single_phase_peak_count_matches_truth():
    # 【テスト目的】: 単相合成パターンの検出ピーク数が真のピーク数と一致することを確認
    # 【テスト内容】: simulate 出力に find_peaks を適用し、件数を peak_positions と比較
    # 【期待される動作】: 各反射につき 1 個ずつ、過不足なく検出される
    # 🔵 信頼性レベル: 完了条件1・既存テスト test_simulate_produces_one_maximum_per_... に依拠

    # 【テストデータ準備】: 既知ピークを持つ決定論バックエンドと単相パターン
    backend = _backend()
    phase = _phase(a=5.0)
    tt = _grid()

    # 【実際の処理実行】: 合成パターンを生成し find_peaks を実行
    y = backend.simulate((phase,), tt)
    peaks = find_peaks(tt, y)

    # 【結果検証】: 真の反射位置数と検出数が一致
    positions = backend.peak_positions(phase, tt)
    assert len(positions) > 0  # 【確認内容】: 前提として範囲内に反射が存在する 🔵
    assert len(peaks) == len(positions)  # 【確認内容】: 検出件数が真の件数と一致 🔵


def test_single_phase_peak_positions_within_one_grid():
    # 【テスト目的】: 各検出ピーク位置が真の 2θ 位置から ±1 グリッド以内であることを確認
    # 【テスト内容】: 検出位置と最寄りの真位置の差がグリッド刻み以下かを検証
    # 【期待される動作】: 局所極大が真のガウシアン中心に最接近するグリッド点に立つ
    # 🔵 信頼性レベル: 完了条件1（±1グリッド）・要件定義4章に依拠

    # 【テストデータ準備】: グリッド刻み 0.02° の単相パターン
    backend = _backend()
    phase = _phase(a=5.0)
    tt = _grid()
    y = backend.simulate((phase,), tt)
    step = float(tt[1] - tt[0])

    # 【実際の処理実行】: find_peaks で検出位置を取得
    peaks = find_peaks(tt, y)
    positions = backend.peak_positions(phase, tt)

    # 【結果検証】: 各検出位置が最寄りの真位置から 1 グリッド以内
    assert len(peaks) > 0  # 【確認内容】: 検出結果が空でない（比較の前提）🔵
    for p in peaks:
        nearest = min(abs(p.position - t) for t in positions)
        assert nearest <= step + 1e-9  # 【確認内容】: 位置誤差が 1 グリッド以内 🔵


def test_multi_phase_increases_peak_count():
    # 【テスト目的】: 複数相を重ねると検出ピーク数が単相より増加することを確認
    # 【テスト内容】: 格子定数の異なる 2 相を重ね、単相ケースとピーク数を比較
    # 【期待される動作】: 位置の異なる新規ピーク群が加わり総数が増える
    # 🔵 信頼性レベル: 要件定義4章「多相合成パターン」に依拠

    # 【テストデータ準備】: a=5.0 単相と、a=5.0 + a=4.3 の 2 相パターン（位置が縮退しない）
    backend = _backend()
    tt = _grid()
    y1 = backend.simulate((_phase(a=5.0, ref="A"),), tt)
    y2 = backend.simulate((_phase(a=5.0, ref="A"), _phase(a=4.3, ref="B")), tt)

    # 【実際の処理実行】: 単相・多相それぞれで検出
    n1 = len(find_peaks(tt, y1))
    n2 = len(find_peaks(tt, y2))

    # 【結果検証】: 多相の検出数が単相を上回る
    assert n2 > n1  # 【確認内容】: 相を重ねると検出ピーク数が増加する 🔵


def test_peak_height_equals_intensity_and_above_threshold():
    # 【テスト目的】: Peak.height がその位置の観測強度に一致し、全ピークが高さ閾値を超えることを確認
    # 【テスト内容】: height が実測強度（閾値そのものではない）であること、閾値超過を検証
    # 【期待される動作】: Peak(position=x[i], height=y[i]) 生成、height > min_height_frac*max
    # 🟡 信頼性レベル: 要件定義2章のデータフローからの妥当な推測（実装式に依存）

    # 【テストデータ準備】: scale=2.0 でピーク高さを底上げした単相パターン
    backend = _backend()
    tt = _grid()
    y = backend.simulate((_phase(a=5.0, scale=2.0),), tt)
    threshold = 0.05 * float(y.max())

    # 【実際の処理実行】: 既定 min_height_frac=0.05 で検出
    peaks = find_peaks(tt, y)

    # 【結果検証】: 各 height が対応グリッド点の強度に一致し、閾値を超える
    assert len(peaks) > 0  # 【確認内容】: 検出結果が空でない（比較の前提）🔵
    for p in peaks:
        idx = int(np.argmin(np.abs(tt - p.position)))
        assert p.height == pytest.approx(float(y[idx]))  # 【確認内容】: height=実測強度 🟡
        assert p.height > threshold - 1e-12  # 【確認内容】: 全ピークが高さ閾値を超過 🟡


def test_returns_sorted_immutable_tuple_of_peaks():
    # 【テスト目的】: 戻り値の型・順序・不変性を確認
    # 【テスト内容】: (a) tuple、(b) 要素は Peak、(c) position 昇順、(d) frozen dataclass
    # 【期待される動作】: 決定論のため順序が昇順固定。属性再代入で FrozenInstanceError
    # 🟡 信頼性レベル: 型は interfaces.py(🔵)、昇順は要件定義2章の妥当な推測(🟡)

    # 【テストデータ準備】: 複数ピークを持つ通常パターン
    backend = _backend()
    tt = _grid()
    y = backend.simulate((_phase(a=5.0),), tt)

    # 【実際の処理実行】: find_peaks を実行
    peaks = find_peaks(tt, y)

    # 【結果検証】: 型・昇順・不変性を検証
    assert isinstance(peaks, tuple)  # 【確認内容】: tuple を返す 🔵
    assert len(peaks) > 0  # 【確認内容】: 昇順・不変検証の前提として非空 🔵
    assert all(isinstance(p, Peak) for p in peaks)  # 【確認内容】: 要素は Peak 🔵
    pos = [p.position for p in peaks]
    assert pos == sorted(pos)  # 【確認内容】: position 昇順 🟡
    with pytest.raises(dataclasses.FrozenInstanceError):
        peaks[0].position = 0.0  # 【確認内容】: Peak は frozen で再代入不可 🔵


def test_deterministic_same_input_returns_equal():
    # 【テスト目的】: 同一入力に対する find_peaks の戻り値がビット同一であることを確認
    # 【テスト内容】: 2 回呼び出して位置・高さ・順序が完全一致するかを検証
    # 【期待される動作】: 乱数・状態を持たない純関数のためタプル全体が等価
    # 🔵 信頼性レベル: 完了条件4・REQ-403・既存 test_deterministic に依拠

    # 【テストデータ準備】: 通常の合成パターン（複数ピーク）
    backend = _backend()
    tt = _grid()
    y = backend.simulate((_phase(a=5.0, scale=1.5),), tt)

    # 【実際の処理実行】: 同一入力で 2 回呼び出す
    r1 = find_peaks(tt, y)
    r2 = find_peaks(tt, y)

    # 【結果検証】: frozen dataclass の値等価によりタプル全体が一致
    assert r1 == r2  # 【確認内容】: 位置・高さ・順序が完全一致（決定論）🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（エラーハンドリング / EDGE-003）
# ---------------------------------------------------------------------------


def test_all_zero_returns_empty_tuple_no_exception():
    # 【テスト目的】: 全ゼロ強度で空タプルを返し例外を出さないことを確認（EDGE-003）
    # 【テスト内容】: y.max()==0 の縮退入力でゼロ除算・比較破綻を起こさないかを検証
    # 【期待される動作】: 例外を送出せず空タプル () を返す
    # 🔵 信頼性レベル: 完了条件2・EDGE-003・要件定義4章に依拠

    # 【テストデータ準備】: 完全フラット（全ゼロ）パターン
    tt = _grid()
    y = np.zeros_like(tt)

    # 【実際の処理実行】: 縮退入力に find_peaks を適用（例外が出れば失敗）
    peaks = find_peaks(tt, y)

    # 【結果検証】: 空タプルを返す
    assert peaks == ()  # 【確認内容】: 空タプルを返す（ゼロ除算・例外なし）🔵


def test_constant_nonzero_returns_empty():
    # 【テスト目的】: 一定の非ゼロ値強度で空タプルを返すことを確認（EDGE-003）
    # 【テスト内容】: max>0 だが厳密不等号 > により極大が 1 つも立たない分岐を検証
    # 【期待される動作】: 過検出せず空タプルを返す
    # 🔵 信頼性レベル: EDGE-003・要件定義4章「一定値 → 空タプル」に依拠

    # 【テストデータ準備】: 全域が同じ正値（100.0）のフラットパターン
    tt = _grid()
    y = np.full_like(tt, 100.0)

    # 【実際の処理実行】: find_peaks を適用
    peaks = find_peaks(tt, y)

    # 【結果検証】: > を >= と誤実装すると全点検出するため空を確認
    assert peaks == ()  # 【確認内容】: 一定値でも空タプル（厳密不等号）🔵


def test_all_negative_returns_empty():
    # 【テスト目的】: 全負値（max<=0）で空タプルを返し比較破綻しないことを確認
    # 【テスト内容】: 高さ閾値が非正になる縮退ケースの安全処理を検証
    # 【期待される動作】: 閾値が負になっても除算・比較で破綻せず空タプルを返す
    # 🟡 信頼性レベル: note.md6章・要件定義3章「max<=0 で例外を出さず空」からの妥当な推測

    # 【テストデータ準備】: 過補正で負に振れた全負値パターン
    tt = _grid()
    y = np.full_like(tt, -5.0)

    # 【実際の処理実行】: find_peaks を適用（例外が出れば失敗）
    peaks = find_peaks(tt, y)

    # 【結果検証】: 空タプルを返す
    assert peaks == ()  # 【確認内容】: max<=0 でも安全に空タプル 🟡


def test_monotonic_increasing_returns_empty():
    # 【テスト目的】: 単調増加配列で内部極大が存在せず空タプルとなることを確認
    # 【テスト内容】: 端点除外仕様により右端の最大値を極大に含めないかを検証
    # 【期待される動作】: 内部点はいずれも極大にならず、端点は判定除外で空タプル
    # 🟡 信頼性レベル: 要件定義3章「端点は極大判定から除外」からの妥当な推測

    # 【テストデータ準備】: 山が存在しない単調増加パターン（最大値は右端＝検出対象外）
    tt = _grid()
    y = np.linspace(1.0, 100.0, tt.size)

    # 【実際の処理実行】: find_peaks を適用
    peaks = find_peaks(tt, y)

    # 【結果検証】: 端点処理のオフバイワンがなければ空タプル
    assert peaks == ()  # 【確認内容】: 単調増加で右端を誤検出せず空 🟡


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（最小値・閾値境界等）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "x,y",
    [
        (np.array([]), np.array([])),  # 長さ0
        (np.array([20.0]), np.array([5.0])),  # 長さ1
        (np.array([20.0, 20.02]), np.array([5.0, 9.0])),  # 長さ2
    ],
)
def test_too_short_returns_empty(x, y):
    # 【テスト目的】: 内部点が存在しない極小入力（長さ<3）で空タプルを返すことを確認
    # 【テスト内容】: y[1:-1] が空スライスとなり空配列 max() 等で例外を出さないかを検証
    # 【期待される動作】: 長さ 0/1/2 のいずれも例外なく空タプルを返す
    # 🟡 信頼性レベル: 要件定義4章「配列長<3→空」・note.md6章からの妥当な推測

    # 【実際の処理実行】: 極小入力に find_peaks を適用（例外が出れば失敗）
    peaks = find_peaks(x, y)

    # 【結果検証】: 空タプルを返す
    assert peaks == ()  # 【確認内容】: 空配列 max() 等で例外を出さず空を返す 🟡


def test_single_interior_maximum_returns_one():
    # 【テスト目的】: 内部に単一の山を持つ最小配列（N=3）で 1 個の Peak を返すことを確認
    # 【テスト内容】: 検出が起こる最小構成の position/height の正確性を検証
    # 【期待される動作】: index 1 が唯一の極大として 1 件検出される
    # 🟡 信頼性レベル: 検出アルゴリズム（局所極大式）からの妥当な推測

    # 【テストデータ準備】: 三角形 [1, 9, 1]。閾値=0.05*9=0.45 で頂点 9.0 は明確に超過
    x = np.array([20.0, 20.02, 20.04])
    y = np.array([1.0, 9.0, 1.0])

    # 【実際の処理実行】: find_peaks を適用
    peaks = find_peaks(x, y)

    # 【結果検証】: 1 件のみ、位置は頂点グリッド、height は頂点強度
    assert len(peaks) == 1  # 【確認内容】: 内部単一極大で 1 件検出 🟡
    assert peaks[0].position == pytest.approx(20.02)  # 【確認内容】: 位置は頂点グリッド 🟡
    assert peaks[0].height == pytest.approx(9.0)  # 【確認内容】: height は頂点強度 🟡


def _two_peak_pattern(tt: np.ndarray, big: float = 10.0, small: float = 0.3) -> np.ndarray:
    # 【テストデータ準備】: 主ピーク(高10, center=30)と微小ピーク(高0.3, center=50)を重ねた合成
    def g(center: float, h: float) -> np.ndarray:
        return h * np.exp(-0.5 * ((tt - center) / 0.08) ** 2)

    return g(30.0, big) + g(50.0, small)


def test_higher_threshold_drops_small_peaks():
    # 【テスト目的】: min_height_frac を上げると微小ピークが検出から落ちることを確認
    # 【テスト内容】: 主ピーク+微小ピーク合成で閾値上昇に対する検出件数の単調非増加を検証
    # 【期待される動作】: 低閾値では副ピーク採用、高閾値では脱落。主ピークは残る
    # 🟡 信頼性レベル: 完了条件3「閾値未満は検出しない」からの妥当な推測

    # 【テストデータ準備】: 副ピーク高さ 0.3 は 0.01*10=0.1(採用) と 0.1*10=1.0(不採用) の間
    tt = _grid()
    y = _two_peak_pattern(tt)

    # 【実際の処理実行】: 低閾値・高閾値で検出件数を比較
    n_low = len(find_peaks(tt, y, min_height_frac=0.01))  # 微小ピーク採用
    n_high = len(find_peaks(tt, y, min_height_frac=0.1))  # 微小ピーク脱落

    # 【結果検証】: 閾値上昇で件数が減り、主ピークは残る
    assert n_low > n_high  # 【確認内容】: 閾値上昇で件数が減る（単調非増加）🟡
    assert n_high >= 1  # 【確認内容】: 主ピークは閾値上昇後も残る 🟡


def test_height_equal_to_threshold_excluded_strict():
    # 【テスト目的】: 極大の高さが閾値と厳密に等しいとき検出されないことを確認（> の境界）
    # 【テスト内容】: 検出条件 y[i] > min_height の厳密不等号（等値は不採用）を検証
    # 【期待される動作】: 閾値同値の副ピークは含まれず、主ピークのみ検出される
    # 🟡 信頼性レベル: 検出式 y[1:-1] > min_height（厳密不等号）からの妥当な推測

    # 【テストデータ準備】: 副ピーク高さ=1.0=閾値ちょうど（min_height=0.5*max(=2.0)=1.0）
    x = np.array([20.0, 20.02, 20.04, 20.06, 20.08])
    y = np.array([0.0, 2.0, 0.0, 1.0, 0.0])

    # 【実際の処理実行】: min_height_frac=0.5 で検出
    peaks = find_peaks(x, y, min_height_frac=0.5)
    positions = [p.position for p in peaks]

    # 【結果検証】: 主ピークのみ 1 件、閾値同値の副ピーク(20.06)は含まれない
    assert len(peaks) == 1  # 【確認内容】: 閾値同値は不採用で主ピークのみ 🟡
    assert peaks[0].position == pytest.approx(20.02)  # 【確認内容】: 検出は主ピーク 🟡
    assert all(abs(p - 20.06) > 1e-9 for p in positions)  # 【確認内容】: 20.06 を含まない 🟡


def test_plateau_peak_not_detected():
    # 【テスト目的】: 頂点が 2 点以上の等値プラトーになっている山を検出しないことを確認
    # 【テスト内容】: 厳密不等号 > によりプラトー頂点が極大条件を満たさないかを検証
    # 【期待される動作】: プラトー型の山は保守的に不検出（過検出しない）で空タプル
    # 🟡 信頼性レベル: note.md6章・要件定義4章「プラトー頂点は極大とみなされない」からの推測

    # 【テストデータ準備】: index 1,2 が等値(9.0)の平坦頂点。どの内部点も > 条件を満たさない
    x = np.array([20.0, 20.02, 20.04, 20.06, 20.08])
    y = np.array([1.0, 9.0, 9.0, 1.0, 1.0])

    # 【実際の処理実行】: find_peaks を適用（NaN/例外/多重検出が出れば失敗）
    peaks = find_peaks(x, y)

    # 【結果検証】: プラトーは極大とみなさず空タプル
    assert peaks == ()  # 【確認内容】: プラトー頂点は不検出（保守的挙動）🟡
