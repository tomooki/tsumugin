"""TASK-0015 changepoint 検出 (sequential/changepoint.py) の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/sequential/changepoint.py``: ``ChangepointConfig`` / ``ChangepointSignal`` /
  ``detect_changepoint()`` (直近 W=5 窓の中央値/MAD ロバスト z を 3 指標 OR で判定する純関数・決定論)
- ``src/tsumugin/sequential/__init__.py``: 上記シンボルの re-export

判定ロジック (D-Q3 / dataflow.md 複合指標 / requirements §2.4 で Red 較正・固定):
- 修正 z スコア ``0.6745 * (x - median) / MAD`` (MAD = median(|x - median|))、窓 = 末尾 ``window`` 要素。
- 閾値判定は ``z > z_threshold`` (strict)。``z_lattice`` は a/b/c 各軸のフレーム間差分の robust z の最大絶対値。
- ``new_peaks`` は ``new_unmatched >= min_new_peaks`` の単純カウント閾値。
- warm-up (``len(rwp_history) < window``) と MAD=0 縮退は例外化せず z=0.0 / triggered=False に縮退。
- ``frame_index`` は履歴末尾インデックス ``len(rwp_history) - 1``。

書式は ``tests/test_model_m2.py`` (TASK-0011) を範とし、決定論は ``==``、z 値近似は ``pytest.approx``、
非有限漏洩検査は ``math.isfinite`` を用いる。テストケース定義 (changepoint 14 件: 正常系 6 / 異常系 3 / 境界値 5) に対応する。

対象モジュール未実装のため import が collection 時に失敗し、本ファイルの全テストがエラー(=失敗)になる想定 (Red)。
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from tsumugin.sequential.changepoint import (
    ChangepointConfig,
    ChangepointSignal,
    detect_changepoint,
)

# 代表的な履歴パターン (末尾が現フレーム)。純関数のため状態を持たずモジュールレベルで一度だけ構築。
# flat_rwp: 微小ノイズの滑らかな Rwp (末尾が窓の median 近傍 → z<5)。末尾 z_rwp は 0.0 に較正済み。
FLAT_RWP = [10.0, 10.1, 9.95, 10.05, 9.98, 10.02]
# spike_rwp: 末尾に急上昇 (z_rwp≈201.68 ≫ 5)。
SPIKE_RWP = [10.0, 10.1, 9.9, 10.0, 10.05, 25.0]
# flat_lattice: 完全同値 → 差分全 0 → MAD=0 縮退 (z_lattice=0, 非発火)。
FLAT_LATTICE = [{"a": 5.0}] * 6
# linear_lattice: 線形熱膨張 → 差分一定 0.01 → MAD=0 → z_lattice=0 (非発火, TC-102-04 の要)。
LINEAR_LATTICE = [{"a": 5.00 + 0.01 * i} for i in range(6)]
# jump_lattice: 末尾で急ジャンプ (差分 0.5 vs 微小ベースライン → z_lattice≈168.29 ≫ 5)。
JUMP_LATTICE = [
    {"a": 5.0},
    {"a": 5.001},
    {"a": 5.002},
    {"a": 5.001},
    {"a": 5.0},
    {"a": 5.5},
]


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_rwp_jump_alone_triggers():
    # 【テスト目的】: Rwp 系列末尾の跳ねのみで rwp_jump が単独発火することを確認 (TC-C-N01 / TC-102-06)
    # 【テスト内容】: spike_rwp + 同値格子 + new_unmatched=0 で detect_changepoint を呼ぶ
    # 【期待される動作】: triggered=True, reasons=("rwp_jump",), z_rwp>5, z_lattice≈0
    # 🔵 信頼性レベル: TC-102-06 / dataflow.md 複合指標 / REQ-003(a) に直接依拠 (exact z は Red 較正)

    # 【テストデータ準備】: 直近窓が安定 (~10) で末尾のみ 25 に跳ねる Rwp (相転移初期を代表)
    # 【初期条件設定】: 格子は全同値 (MAD=0 縮退で非発火)、新規ピーク 0 で rwp を単離
    # 【前提条件確認】: 履歴長 6 >= window 5 (warm-up を抜けている)
    sig = detect_changepoint(SPIKE_RWP, FLAT_LATTICE, 0)

    # 【結果検証】: rwp_jump 単独発火・格子/新規は非発火・reasons の説明可能性
    # 【期待値確認】: z_rwp が閾値超過、格子は MAD=0 縮退で z_lattice≈0
    assert sig.triggered is True  # 【確認内容】: 変化点として発火 🔵
    assert sig.reasons == ("rwp_jump",)  # 【確認内容】: rwp 指標のみ (説明可能性) 🔵
    assert sig.z_rwp > 5.0  # 【確認内容】: z が閾値超過 🟡(exact は Red 較正)
    assert sig.z_lattice == pytest.approx(0.0)  # 【確認内容】: 格子は MAD=0 縮退で非発火 🟡
    assert sig.new_unmatched == 0  # 【確認内容】: 新規ピーク指標は非発火 🔵


def test_lattice_jump_alone_triggers():
    # 【テスト目的】: 格子 a のフレーム間差分の急変のみで lattice_jump が単独発火することを確認 (TC-C-N02)
    # 【テスト内容】: flat_rwp + jump_lattice + new_unmatched=0 で detect_changepoint を呼ぶ
    # 【期待される動作】: triggered=True, reasons=("lattice_jump",), z_lattice>5, z_rwp<=5
    # 🔵 信頼性レベル: TC-102-06 / dataflow.md「格子 a/b/c のフレーム間差分」に直接依拠

    # 【テストデータ準備】: 格子定数が不連続にジャンプする構造相転移 (差分 0.5) を代表
    # 【初期条件設定】: Rwp は滑らか (z_rwp=0)、新規ピーク 0 で格子指標を単離
    sig = detect_changepoint(FLAT_RWP, JUMP_LATTICE, 0)

    # 【結果検証】: lattice_jump 単独発火・差分ベース判定であること
    # 【期待値確認】: 生値でなく差分に robust z を適用 (TC-C-N04 と対)
    assert sig.triggered is True  # 【確認内容】: 変化点として発火 🔵
    assert sig.reasons == ("lattice_jump",)  # 【確認内容】: 格子指標のみ (説明可能性) 🔵
    assert sig.z_lattice > 5.0  # 【確認内容】: 格子差分 z が閾値超過 🟡(exact は Red 較正)
    assert sig.z_rwp <= 5.0  # 【確認内容】: Rwp は非発火 🔵
    assert sig.new_unmatched == 0  # 【確認内容】: 新規ピーク指標は非発火 🔵


def test_new_peaks_alone_triggers():
    # 【テスト目的】: 新規未マッチピークだけが下限以上のとき new_peaks が単独発火することを確認 (TC-C-N03)
    # 【テスト内容】: flat_rwp + flat_lattice + new_unmatched=2 で detect_changepoint を呼ぶ
    # 【期待される動作】: new_unmatched>=min_new_peaks で発火、z 系は非発火
    # 🟡 信頼性レベル: TC-102-06 は 🔵 だが「new_peaks の z 非依存カウント解釈」は妥当な推測

    # 【テストデータ準備】: 新相の未知ピークが現れ始めた瞬間 (残差/格子はまだ動かない) を代表
    # 【初期条件設定】: Rwp 滑らか (z_rwp=0)・格子同値 (z_lattice=0) で new_peaks を単離
    sig = detect_changepoint(FLAT_RWP, FLAT_LATTICE, 2)

    # 【結果検証】: new_peaks は z を持たず単純カウント (new_unmatched>=1) で発火すること
    # 【期待値確認】: dataflow「z 超過」注記に対し min_new_peaks カウント閾値を採用
    assert sig.triggered is True  # 【確認内容】: 変化点として発火 🟡
    assert sig.reasons == ("new_peaks",)  # 【確認内容】: 新規ピーク指標のみ (説明可能性) 🟡
    assert sig.new_unmatched == 2  # 【確認内容】: 新規未マッチピーク数が保持される 🔵
    assert sig.z_rwp <= 5.0  # 【確認内容】: Rwp は非発火 🔵
    assert sig.z_lattice == pytest.approx(0.0)  # 【確認内容】: 格子は MAD=0 縮退で非発火 🟡


def test_smooth_series_no_trigger():
    # 【テスト目的】: 滑らかな系列 (Rwp 安定+格子線形膨張+新規0) で変化点が検出されないことを確認 (TC-C-N04)
    # 【テスト内容】: flat_rwp + linear_lattice + new_unmatched=0 で detect_changepoint を呼ぶ
    # 【期待される動作】: 全 3 指標が閾値未満 → triggered=False, reasons=()
    # 🔵 信頼性レベル: 受け入れ基準 TC-102-04 (変化のない滑らかなシーケンスで changepoint ゼロ) に直接依拠

    # 【テストデータ準備】: 変化のない安定加熱区間 (線形熱膨張は「正常」で変化点ではない) を代表
    # 【初期条件設定】: 線形膨張は差分一定 → MAD=0 → z_lattice=0 (差分ベース判定の正しさを検証)
    sig = detect_changepoint(FLAT_RWP, LINEAR_LATTICE, 0)

    # 【結果検証】: false-positive 抑制 (最重要)。線形膨張を「変化点」と誤検出しないこと
    # 【期待値確認】: 差分ベース + MAD=0 縮退により線形トレンドを誤発火させない
    assert sig.triggered is False  # 【確認内容】: 滑らかな系列で非発火 🔵
    assert sig.reasons == ()  # 【確認内容】: 発火指標なし 🔵
    assert sig.z_lattice == pytest.approx(0.0)  # 【確認内容】: 線形膨張は差分一定で z_lattice≈0 🔵
    assert sig.z_rwp <= 5.0  # 【確認内容】: Rwp も閾値未満 🔵


def test_multiple_indicators_or_combined():
    # 【テスト目的】: 3 指標同時発火で reasons に複数入り OR で発火することを確認 (TC-C-N05)
    # 【テスト内容】: spike_rwp + jump_lattice + new_unmatched=3 で detect_changepoint を呼ぶ
    # 【期待される動作】: triggered=True、reasons が発火した全指標を含む
    # 🔵 信頼性レベル: dataflow.md「E/F/G --or--> H」(3 指標 OR) に直接依拠

    # 【テストデータ準備】: 明確な相転移フレーム (3 指標すべてが同時に動く) を代表
    # 【初期条件設定】: Rwp 跳ね + 格子ジャンプ + 新規ピーク 3 を同時付与
    sig = detect_changepoint(SPIKE_RWP, JUMP_LATTICE, 3)

    # 【結果検証】: OR 結合で単一指標に潰れず全発火指標が記録されること (説明可能性)
    # 【期待値確認】: reasons に 3 指標すべてが集約される (順序は決定論的)
    assert sig.triggered is True  # 【確認内容】: OR 結合で発火 🔵
    assert set(sig.reasons) == {"rwp_jump", "lattice_jump", "new_peaks"}  # 【確認内容】: 全指標集約 🔵
    assert len(sig.reasons) == 3  # 【確認内容】: 3 指標が重複なく記録される 🔵


def test_signal_fields_populated():
    # 【テスト目的】: ChangepointSignal のフィールドが判定内容と整合して埋まることを確認 (TC-C-N06)
    # 【テスト内容】: spike_rwp(長さ6) + flat_lattice + new_unmatched=0 で signal 内容を検査
    # 【期待される動作】: frame_index/z_rwp/new_unmatched/reasons が判定過程を反映 (説明可能性)
    # 🟡 信頼性レベル: interfaces.py L90-99 は 🔵 だが frame_index=len-1 の由来は妥当な推測

    # 【テストデータ準備】: 発火時の signal 内容を検査する代表 (履歴長 6)
    # 【初期条件設定】: frame_index が履歴末尾由来 (len-1=5) となることを固定
    sig = detect_changepoint(SPIKE_RWP, FLAT_LATTICE, 0)

    # 【結果検証】: どの指標がどれだけ逸脱したかを説明可能なフィールドが埋まること
    # 【期待値確認】: frame_index=len(rwp_history)-1、z_rwp>5、reasons=("rwp_jump",)
    assert isinstance(sig, ChangepointSignal)  # 【確認内容】: 戻り値が ChangepointSignal 型 🔵
    assert sig.frame_index == 5  # 【確認内容】: frame_index は履歴末尾インデックス由来 🟡
    assert sig.z_rwp > 5.0  # 【確認内容】: 逸脱量 z_rwp が定量的に埋まる 🔵
    assert sig.new_unmatched == 0  # 【確認内容】: 新規ピーク数が保持される 🔵
    assert sig.reasons == ("rwp_jump",)  # 【確認内容】: 発火指標名が記録される (完了条件⑤) 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（縮退の非例外化・非破壊契約）
# ---------------------------------------------------------------------------


def test_warmup_below_window_no_detection():
    # 【テスト目的】: warm-up (履歴 < window) では末尾が跳ねても検出しないことを確認 (TC-C-E01 / 完了条件④)
    # 【テスト内容】: 長さ 3 (< window 5) の履歴で detect_changepoint を呼ぶ
    # 【期待される動作】: 例外なし・triggered=False・z 系 0.0 (母数不足の安全側縮退)
    # 🟡 信頼性レベル: 完了条件④ / design-interview D-Q3「warm-up (W 未満) は検出スキップ」に依拠

    # 【テストデータ準備】: シーケンス最初の数フレーム (末尾 30.0 は大きく跳ねている) を再現
    # 【初期条件設定】: rwp/lattice とも長さ 3 で窓 5 を満たさない (縮退であり不正入力ではない)
    rwp_history = [10.0, 30.0, 8.0]
    lattice_history = [{"a": 5.0}, {"a": 5.0}, {"a": 5.0}]
    sig = detect_changepoint(rwp_history, lattice_history, 0)

    # 【結果検証】: 末尾が跳ねていても窓未満なら発火せず inf/nan も漏らさないこと
    # 【期待値確認】: warm-up は例外でなく縮退値 (triggered=False, z=0.0) に一元化
    assert sig.triggered is False  # 【確認内容】: 窓未満は検出スキップ 🟡
    assert sig.reasons == ()  # 【確認内容】: 発火指標なし 🟡
    assert sig.z_rwp == pytest.approx(0.0)  # 【確認内容】: z_rwp は縮退値 0.0 🟡
    assert sig.z_lattice == pytest.approx(0.0)  # 【確認内容】: z_lattice は縮退値 0.0 🟡


def test_mad_zero_degeneracy_no_false_trigger():
    # 【テスト目的】: MAD=0 縮退 (全同値履歴) で 0 除算せず誤発火しないことを確認 (TC-C-E02 / 完了条件⑥)
    # 【テスト内容】: rwp 全同値 [10.0]*6 + 格子全同値で detect_changepoint を呼ぶ
    # 【期待される動作】: 例外なし・inf/nan なし・triggered=False・z 系 0.0
    # 🟡 信頼性レベル: 完了条件⑥ / CLAUDE.md「非有限値を漏らさない」(M1 教訓) に依拠

    # 【テストデータ準備】: 完全に安定した平衡区間 / 定数入力 (分散ゼロで z が定義できない縮退) を再現
    # 【初期条件設定】: 窓内 Rwp が全同値 → MAD=0 → robust z が 0 除算になる境界
    sig = detect_changepoint([10.0] * 6, FLAT_LATTICE, 0)

    # 【結果検証】: 全同値=変化なし → 発火しない (安全側縮退)。inf/nan を下流へ伝播しないこと
    # 【期待値確認】: MAD=0 ガードにより z=0.0、math.isfinite が True
    assert sig.triggered is False  # 【確認内容】: 全同値で非発火 🟡
    assert sig.z_rwp == pytest.approx(0.0)  # 【確認内容】: z_rwp は 0.0 に縮退 🟡
    assert sig.z_lattice == pytest.approx(0.0)  # 【確認内容】: z_lattice は 0.0 に縮退 🟡
    assert math.isfinite(sig.z_rwp)  # 【確認内容】: z_rwp に inf/nan を漏らさない 🔵
    assert math.isfinite(sig.z_lattice)  # 【確認内容】: z_lattice に inf/nan を漏らさない 🔵


def test_changepoint_dataclasses_are_frozen():
    # 【テスト目的】: ChangepointConfig / ChangepointSignal が frozen で再代入不可を確認 (TC-C-E03)
    # 【テスト内容】: config.window と signal.triggered へ再代入し FrozenInstanceError を検証
    # 【期待される動作】: 両者とも FrozenInstanceError (設定・判定結果の不変性 = 決定論の前提)
    # 🔵 信頼性レベル: interfaces.py L81/L90 (frozen) / test_model_m2.py パターンに直接依拠

    # 【テストデータ準備】: 設定/結果を実行中に書き換える誤用の防御を検証する対象を用意
    # 【初期条件設定】: 既定 config と発火する signal を生成
    cfg = ChangepointConfig()
    sig = detect_changepoint(SPIKE_RWP, FLAT_LATTICE, 0)

    # 【結果検証】: 設定・判定結果の事後改変が禁止されること
    # 【期待値確認】: frozen=True のため両者とも再代入で FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        cfg.window = 10  # type: ignore[misc]  # 【確認内容】: config が frozen 🔵
    with pytest.raises(FrozenInstanceError):
        sig.triggered = False  # type: ignore[misc]  # 【確認内容】: signal が frozen 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（窓境界・閾値境界・下限境界・決定論・既定値）
# ---------------------------------------------------------------------------


def test_history_exactly_window_detects():
    # 【テスト目的】: 履歴長ちょうど window(=5) で検出が実行されることを確認 (TC-C-B01 / warm-up 許可側境界)
    # 【テスト内容】: 長さ 5 (==window) の末尾跳ね履歴で detect_changepoint を呼ぶ
    # 【期待される動作】: warm-up スキップされず判定実行、末尾の跳ねで triggered=True
    # 🟡 信頼性レベル: D-Q3「W 未満はスキップ」に依拠 (境界の厳密解釈 len<window を Red で確定)

    # 【テストデータ準備】: warm-up を抜けた最初の判定フレーム (末尾 30.0 が跳ね) を再現
    # 【初期条件設定】: rwp 長さ 5 == window、格子は同値 5 フレーム (TC-C-E01 長さ3スキップと対称)
    rwp_history = [10.0, 10.1, 9.9, 10.0, 30.0]
    lattice_history = FLAT_LATTICE[:5]
    sig = detect_changepoint(rwp_history, lattice_history, 0)

    # 【結果検証】: warm-up 条件が len<window (<= でない) であること (off-by-one 検出)
    # 【期待値確認】: 履歴長が窓に達したフレームで検出が有効化される
    assert sig.triggered is True  # 【確認内容】: len==window で検出実行 🟡
    assert "rwp_jump" in sig.reasons  # 【確認内容】: 末尾跳ねで rwp_jump 発火 🟡


def test_z_exactly_threshold_not_triggered():
    # 【テスト目的】: z がちょうど閾値のとき非発火 (strict > 境界) を確認 (TC-C-B02)
    # 【テスト内容】: robust z が閾値 5.0 ちょうど (以下) になる入力と、閾値超過の入力で発火境界を検証
    # 【期待される動作】: z<=5.0 で triggered=False、z>5.0 で triggered=True (dataflow「z>5」の strict 解釈)
    # 🟡 信頼性レベル: dataflow.md の > 表記に依拠。strict/非 strict は Red で確定 (妥当な推測)

    # 【テストデータ準備】: 窓 [m-2u, m-u, m, m+u, x] は median=m / MAD=u で末尾 x の z を評価。
    # 【初期条件設定】: x_at は z==5.0 になるよう median/MAD から逆算 (0.6745*(x-m)/u=5.0)。
    #   浮動小数の round-trip 揺らぎを避け z<=5.0 側 (z=4.9999999999999) に較正済み。
    #   x_above は z=5.1 (>5.0) の明確な超過側。
    rwp_at_threshold = [9.8, 9.9, 10.0, 10.1, 10.74128984432913]
    rwp_above_threshold = [9.8, 9.9, 10.0, 10.1, 10.756115641215713]
    cfg = ChangepointConfig(z_threshold=5.0)

    sig_at = detect_changepoint(rwp_at_threshold, FLAT_LATTICE, 0, config=cfg)
    sig_above = detect_changepoint(rwp_above_threshold, FLAT_LATTICE, 0, config=cfg)

    # 【結果検証】: 閾値ちょうど (z<=5.0) は非発火、明確な超過 (z>5.0) は発火すること
    # 【期待値確認】: 判定式が > (strict) であり浮動小数の等号境界で揺れないこと
    assert sig_at.z_rwp <= 5.0  # 【確認内容】: 較正入力の z が閾値以下 🟡
    assert sig_at.triggered is False  # 【確認内容】: 閾値ちょうどは非発火 (strict >) 🟡
    assert "rwp_jump" not in sig_at.reasons  # 【確認内容】: rwp_jump が入らない 🟡
    assert sig_above.triggered is True  # 【確認内容】: 閾値超過は発火 🟡
    assert "rwp_jump" in sig_above.reasons  # 【確認内容】: 超過側で rwp_jump 発火 🟡


@pytest.mark.parametrize(
    ("new_unmatched", "expect_triggered"),
    [(1, True), (0, False)],
)
def test_new_peaks_threshold_boundary(new_unmatched, expect_triggered):
    # 【テスト目的】: new_unmatched が min_new_peaks 境界 (=1) で発火/非発火することを確認 (TC-C-B03)
    # 【テスト内容】: new_unmatched=1 (発火) と =0 (非発火) を parametrize で検証
    # 【期待される動作】: new_unmatched>=min_new_peaks (下限包含 >=) で発火
    # 🔵 信頼性レベル: interfaces.py L88 min_new_peaks:int=1 に直接依拠 (>= は 🟡)

    # 【テストデータ準備】: 新規ピークが 1 本だけ現れた瞬間 (下限ちょうど) と直下 (0) を再現
    # 【初期条件設定】: Rwp/格子は滑らか (z 非発火) で new_peaks 指標を単離
    sig = detect_changepoint(FLAT_RWP, FLAT_LATTICE, new_unmatched)

    # 【結果検証】: 下限包含規則 (>=) が実装されていること (TC-C-N03 new=2 と連続)
    # 【期待値確認】: new_unmatched==1 で発火、==0 で非発火
    assert sig.triggered is expect_triggered  # 【確認内容】: 下限境界で発火/非発火が切替わる 🔵
    if expect_triggered:
        assert sig.reasons == ("new_peaks",)  # 【確認内容】: 下限ちょうどで new_peaks 発火 🔵
    else:
        assert "new_peaks" not in sig.reasons  # 【確認内容】: 直下では非発火 🔵


def test_deterministic_bit_identical():
    # 【テスト目的】: 同一入力 2 回でビット同一の ChangepointSignal を確認 (TC-C-B04 / REQ-402)
    # 【テスト内容】: 複数キー格子を含む入力で detect_changepoint を 2 回独立に呼び == を検証
    # 【期待される動作】: 純関数で乱数・Mapping 反復順依存がなく 2 回呼び出しが ==
    # 🔵 信頼性レベル: REQ-402 / NFR-102 (決定論/ビット同一) に直接依拠

    # 【テストデータ準備】: 再解析・監査での結果再現 (a/b/c 複数キーで dict 反復順の影響も検査)
    # 【初期条件設定】: 決定論は「ほぼ同じ」不可 — pytest.approx 禁止、== 比較
    lattice_history = [
        {"a": 5.0, "b": 6.0, "c": 7.0},
        {"a": 5.001, "b": 6.001, "c": 7.0},
        {"a": 5.002, "b": 6.0, "c": 7.001},
        {"a": 5.001, "b": 6.001, "c": 7.0},
        {"a": 5.0, "b": 6.0, "c": 7.0},
        {"a": 5.5, "b": 6.5, "c": 7.5},
    ]
    sig1 = detect_changepoint(SPIKE_RWP, lattice_history, 3)
    sig2 = detect_changepoint(SPIKE_RWP, lattice_history, 3)

    # 【結果検証】: float フィールド含め全フィールドがビット同一 (丸め揺らぎゼロ)
    # 【期待値確認】: frozen dataclass の構造的等価 == と reasons タプル順序の一致
    assert sig1 == sig2  # 【確認内容】: 2 回呼び出しが構造的に等価 (決定論) 🔵
    assert sig1.reasons == sig2.reasons  # 【確認内容】: reasons 順序も同一 (Mapping 順序非依存) 🔵


def test_changepoint_config_defaults():
    # 【テスト目的】: ChangepointConfig の既定値 (window=5/z_threshold=5.0/min_new_peaks=1) を確認 (TC-C-B05)
    # 【テスト内容】: 引数なし ChangepointConfig() の各既定値と frozen を検証
    # 【期待される動作】: interfaces.py / D-Q3 の仕様値と一致し frozen
    # 🔵 信頼性レベル: interfaces.py L81-88 / design-interview D-Q3 既定値に直接依拠

    # 【テストデータ準備】: config 省略でのデフォルト検出 (既定値変更はリグレッション) を検証
    # 【初期条件設定】: 引数なしで ChangepointConfig を構築
    cfg = ChangepointConfig()

    # 【結果検証】: 全 3 既定値が仕様どおりで frozen であること
    # 【期待値確認】: D-Q3 (W=5 / 閾値 5.0 / 下限 1) の仕様値
    assert cfg.window == 5  # 【確認内容】: 窓の既定は 5 🔵
    assert cfg.z_threshold == pytest.approx(5.0)  # 【確認内容】: z 閾値の既定は 5.0 🔵
    assert cfg.min_new_peaks == 1  # 【確認内容】: 新規ピーク下限の既定は 1 🔵
    with pytest.raises(FrozenInstanceError):
        cfg.window = 3  # type: ignore[misc]  # 【確認内容】: config が frozen で再代入不可 🔵
