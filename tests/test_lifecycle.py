"""TASK-0016 LifecycleTracker (sequential/lifecycle.py) の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/sequential/lifecycle.py``: ``LifecycleConfig`` (frozen dataclass) /
  ``LifecycleTracker`` (ステートフル。``observe()`` で相ごとの present/absent ランを蓄積し、
  ``finalize()`` で ``Mapping[str, PhaseLifecycle]`` を返す)。
- ``src/tsumugin/sequential/__init__.py``: 上記 2 シンボルの re-export (``__all__`` 昇順追加)。

ヒステリシスの意味論 (requirements §2 / interfaces.py L118-133 / TC-103 系で固定):
- birth 確定: 連続 hysteresis(=3) フレーム present → ``birth_frame`` は連続の**最初のフレーム**。
- death 確定: birth 済みの相が連続 hysteresis フレーム absent → ``death_frame`` は不在連続の**最初のフレーム**。
- death 取り消し (REQ-201): 不在ランが hysteresis 未満のうちに再出現 → 不在ランをリセット・連続扱い (death なし)。
- 点滅抑制 (TC-103-03): 連続 present が hysteresis 未満の偽出現は birth 未確定 (基本線: 相キーを含めない)。
- ``confidence`` = 存在フレーム率 = present フレーム数 / 総観測フレーム数 (全存在で 1.0)。

書式は ``tests/test_changepoint.py`` (TASK-0015) を範とし、決定論・整数は ``==``、浮動小数は ``pytest.approx``、
frozen 検証は ``pytest.raises(FrozenInstanceError)`` を用いる。テストケース定義 (lifecycle 13 件:
正常系 6 / 異常系 3 / 境界値 4) に対応する。

対象モジュール未実装のため import が collection 時に失敗し、本ファイルの全テストがエラー(=失敗)になる想定 (Red)。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import tsumugin.sequential as sequential_pkg
from tsumugin.sequential.lifecycle import LifecycleConfig, LifecycleTracker

# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_birth_confirmed_after_hysteresis():
    # 【テスト目的】: frame 10 からの連続出現で birth_frame=10 が確定することを確認 (N-01 / TC-103-01)
    # 【テスト内容】: hysteresis=3 で frame 10,11,12,... を連続 present("B") にする
    # 【期待される動作】: 連続開始フレーム 10 が birth_frame に記録され、death は None
    # 🔵 信頼性レベル: 完了条件① / TC-103-01 / interfaces.py L118-133 に直接依拠

    # 【テストデータ準備】: frame 0..9 を B 不在、10 以降を present("B") にして明確な出現点を作る
    # 【初期条件設定】: hysteresis=3 のトラッカーを構築 (連続 3 フレームで確定)
    tracker = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    for f in range(10):
        tracker.observe(f, ())
    for f in range(10, 15):
        tracker.observe(f, ("B",))

    # 【実際の処理実行】: 全フレーム observe 後に finalize で相ライフサイクル辞書を確定
    result = tracker.finalize()

    # 【結果検証】: birth は「N フレーム目 (12)」でなく「連続開始 (10)」であること
    # 【期待値確認】: 連続 3 フレーム到達で birth 成立、記録は連続開始フレーム 10
    assert result["B"].birth_frame == 10  # 【確認内容】: birth_frame が連続開始フレーム 🔵
    assert result["B"].death_frame is None  # 【確認内容】: 消滅していない 🔵


def test_death_confirmed_after_absent_hysteresis():
    # 【テスト目的】: 相 A が frame 15 から連続不在で death_frame=15 が確定することを確認 (N-02 / TC-103-02)
    # 【テスト内容】: frame 0..14 present("A")、frame 15 以降 absent () にする
    # 【期待される動作】: 連続 3 フレーム不在で death 成立、記録は不在連続の先頭 15
    # 🔵 信頼性レベル: 完了条件② / TC-103-02 に直接依拠

    # 【テストデータ準備】: A を十分長く存在させ birth 確定後、frame 15 から明確に不在化させる
    # 【初期条件設定】: hysteresis=3。frame 15,16,17 の連続不在で death を成立させる
    tracker = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    for f in range(15):
        tracker.observe(f, ("A",))
    for f in range(15, 21):
        tracker.observe(f, ())

    # 【実際の処理実行】: finalize で A のライフサイクルを確定
    result = tracker.finalize()

    # 【結果検証】: death_frame は不在連続の先頭 (15)、birth_frame は 0
    # 【期待値確認】: 連続 3 フレーム不在 (15,16,17) で death 成立、記録は不在開始 15
    assert result["A"].death_frame == 15  # 【確認内容】: death_frame が不在連続の先頭 🔵
    assert result["A"].birth_frame == 0  # 【確認内容】: birth は最初の連続開始フレーム 🔵


def test_death_cancelled_on_reappear_within_window():
    # 【テスト目的】: death 判定に至る前 (窓内) に A が再出現し death 取り消し・連続扱いを確認 (N-03 / REQ-201)
    # 【テスト内容】: frame 0..14 present("A")、frame 15,16 不在、frame 17 で再 present("A")
    # 【期待される動作】: 不在ランが hysteresis(3) 未満のうちに present へ戻り不在ランをリセット
    # 🔵 信頼性レベル: 完了条件④ / TC-103-04 / REQ-201 に直接依拠

    # 【テストデータ準備】: 2 フレームだけの不在 (< N=3) の後に再出現 = 点滅的欠落を再現
    # 【初期条件設定】: hysteresis=3。不在 15,16 (=2 フレーム) は窓を満たさない
    tracker = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    for f in range(15):
        tracker.observe(f, ("A",))
    tracker.observe(15, ())
    tracker.observe(16, ())
    for f in range(17, 21):
        tracker.observe(f, ("A",))

    # 【実際の処理実行】: finalize で A のライフサイクルを確定
    result = tracker.finalize()

    # 【結果検証】: 窓 (2 < 3) を満たさない不在で death が立たないこと
    # 【期待値確認】: 窓内再出現で death 取り消し、A は連続存続扱い
    assert result["A"].death_frame is None  # 【確認内容】: 窓内再出現で death 未確定 🔵


def test_all_frames_present_confidence_one():
    # 【テスト目的】: 全フレーム present の相は birth=最初/death=None/confidence=1.0 を確認 (N-04)
    # 【テスト内容】: frame 0..9 をすべて present_refs=("C",) にする
    # 【期待される動作】: 一度も不在にならない相は存在フレーム率 1.0 (10/10)
    # 🟡 信頼性レベル: 完了条件⑤ / confidence 算出式 (存在フレーム率) は実装時確定

    # 【テストデータ準備】: 常在相 (背景相) を代表。全 10 フレーム present で不在ゼロ
    # 【初期条件設定】: hysteresis=3。連続 present で birth 確定、不在なしで death None
    tracker = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    for f in range(10):
        tracker.observe(f, ("C",))

    # 【実際の処理実行】: finalize で C のライフサイクルを確定
    lc = tracker.finalize()["C"]

    # 【結果検証】: birth=最初(0) / death=None / confidence=1.0 (存在フレーム率 10/10)
    # 【期待値確認】: 存在フレーム率の分母/分子が全存在で 1.0 になること
    assert lc.birth_frame == 0  # 【確認内容】: birth は最初のフレーム 🟡
    assert lc.death_frame is None  # 【確認内容】: 未消滅は None 🟡
    assert lc.confidence == pytest.approx(1.0)  # 【確認内容】: 全存在で存在フレーム率 1.0 🟡


def test_multiple_phases_tracked_independently():
    # 【テスト目的】: A (存在→消滅) と B (途中出現) を同一トラッカーで独立追跡することを確認 (N-05)
    # 【テスト内容】: frame 0..14 present("A")、frame 10.. で "B" 追加、frame 15.. で A を外す
    # 【期待される動作】: 相ごとに独立した present/absent ランを保持し相数分の PhaseLifecycle を返す
    # 🔵 信頼性レベル: interfaces.py 契約 Mapping[str, PhaseLifecycle] / 複数相はシーケンシャルの基本

    # 【テストデータ準備】: 相の入れ替わり (operando の相転移) を代表するフレーム列
    # 【初期条件設定】: hysteresis=3。A は 0..14 存在、B は 10 以降存在、A は 15 以降不在
    tracker = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    for f in range(10):
        tracker.observe(f, ("A",))
    for f in range(10, 15):
        tracker.observe(f, ("A", "B"))
    for f in range(15, 25):
        tracker.observe(f, ("B",))

    # 【実際の処理実行】: finalize で 2 相のライフサイクルを一括確定
    result = tracker.finalize()

    # 【結果検証】: key 網羅と相間の非干渉 (A は消滅、B は途中出現・存続)
    # 【期待値確認】: A.birth=0 / A.death=15 / B.birth=10 が独立に確定
    assert set(result.keys()) == {"A", "B"}  # 【確認内容】: 戻り値 key が全相を網羅 🔵
    assert result["A"].birth_frame == 0  # 【確認内容】: A は最初から存在 🔵
    assert result["A"].death_frame == 15  # 【確認内容】: A は frame 15 で消滅 🔵
    assert result["B"].birth_frame == 10  # 【確認内容】: B は frame 10 で出現 🔵
    assert result["B"].death_frame is None  # 【確認内容】: B は存続 (未消滅) 🔵


def test_lifecycle_config_defaults_frozen_and_reexport():
    # 【テスト目的】: LifecycleConfig の既定値・frozen 性・パッケージ公開を確認 (N-06)
    # 【テスト内容】: 引数なし LifecycleConfig() の既定値と再代入拒否、sequential からの re-export を検証
    # 【期待される動作】: hysteresis=3 / presence_wt_frac=1e-3、再代入で FrozenInstanceError、__all__ に登録
    # 🔵 信頼性レベル: interfaces.py L118-121 / CLAUDE.md frozen 規約 / __init__.py 公開様式に依拠

    # 【テストデータ準備】: 既定値変更 (リグレッション) 検出のため引数なしで構築
    # 【初期条件設定】: 引数なしで LifecycleConfig を構築
    cfg = LifecycleConfig()

    # 【結果検証】: 既定値・frozen・後続 TASK-0019 が import できる公開面
    # 【期待値確認】: interfaces.py L119-121 の既定値と CLAUDE.md の不変性
    assert cfg.hysteresis == 3  # 【確認内容】: ヒステリシス窓の既定は 3 🔵
    assert cfg.presence_wt_frac == pytest.approx(1e-3)  # 【確認内容】: 存在判定下限の既定は 1e-3 🔵
    with pytest.raises(FrozenInstanceError):
        cfg.hysteresis = 5  # type: ignore[misc]  # 【確認内容】: config が frozen で再代入不可 🔵
    # 【期待値確認】: sequential パッケージから 2 シンボルが解決し __all__ に昇順登録される
    assert sequential_pkg.LifecycleConfig is LifecycleConfig  # 【確認内容】: Config が re-export 🔵
    assert sequential_pkg.LifecycleTracker is LifecycleTracker  # 【確認内容】: Tracker が re-export 🔵
    assert "LifecycleConfig" in sequential_pkg.__all__  # 【確認内容】: __all__ に Config 登録 🔵
    assert "LifecycleTracker" in sequential_pkg.__all__  # 【確認内容】: __all__ に Tracker 登録 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（縮退・偽入力）
# ---------------------------------------------------------------------------


def test_single_frame_flicker_not_birth():
    # 【テスト目的】: 1 フレームだけ (< N=3) の偽出現が birth 非認定になることを確認 (E-01 / TC-103-03)
    # 【テスト内容】: hysteresis=3。frame 5 のみ present("X")、他フレームは不在
    # 【期待される動作】: 連続 1 フレーム < N のため birth 条件を満たさず、相キーに含めない
    # 🔵 信頼性レベル: 完了条件③ / TC-103-03 (ヒステリシス中核) に直接依拠

    # 【テストデータ準備】: フレーム間ノイズで wt_frac が一瞬だけ閾値を超える偽出現を再現
    # 【初期条件設定】: hysteresis=3。X の連続 present は最大 1 フレーム
    tracker = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    for f in range(10):
        tracker.observe(f, ("X",) if f == 5 else ())

    # 【実際の処理実行】: finalize で確定した相のみ返す
    result = tracker.finalize()

    # 【結果検証】: 偽出現 X は無視され、確定相キーに含まれないこと
    # 【期待値確認】: birth 未確定の相はキーに含めない (基本線の意味論)
    assert "X" not in result  # 【確認内容】: 点滅の偽出現は birth 非認定でキーなし 🔵


def test_empty_observation_returns_empty_mapping():
    # 【テスト目的】: observe を一度も呼ばず finalize すると空 Mapping を返すことを確認 (E-02 / EDGE-001)
    # 【テスト内容】: LifecycleTracker() 直後に finalize() を呼ぶ (空フレーム列)
    # 【期待される動作】: 空 Mapping を返し例外を送出しない (M0/M1 の縮退規約踏襲)
    # 🟡 信頼性レベル: EDGE-001 の踏襲 / 要件定義 4 章に依拠

    # 【テストデータ準備】: フレーム 0 件のデータセット (EDGE-001) を再現
    # 【初期条件設定】: 既定 Config でトラッカーのみ構築
    tracker = LifecycleTracker()

    # 【実際の処理実行】: observe なしで finalize を呼ぶ
    result = tracker.finalize()

    # 【結果検証】: 上位エンジンが空トラジェクトリを安全に構築できること
    # 【期待値確認】: 空 Mapping (例外なし)
    assert result == {}  # 【確認内容】: 空観測は空 Mapping に縮退 🟡


def test_absent_run_reaching_window_confirms_death():
    # 【テスト目的】: 不在が窓 (=N) を満たすと再出現しても death が確定することを確認 (E-03 / N-03 の対偶)
    # 【テスト内容】: frame 0..14 present("A")、frame 15,16,17 不在 (=N=3)、frame 18 で再出現
    # 【期待される動作】: 窓を満たした時点で death 確定 (窓を超えた不在は取り消さない)
    # 🔵 信頼性レベル: REQ-201 の境界 / TC-103-02 と整合

    # 【テストデータ準備】: 真に消滅した相が後で別要因で再出現するシナリオを再現
    # 【初期条件設定】: hysteresis=3。不在 15,16,17 が窓 (3) を満たす
    tracker = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    for f in range(15):
        tracker.observe(f, ("A",))
    tracker.observe(15, ())
    tracker.observe(16, ())
    tracker.observe(17, ())
    tracker.observe(18, ("A",))

    # 【実際の処理実行】: finalize で A のライフサイクルを確定
    result = tracker.finalize()

    # 【結果検証】: 窓を満たした不在は取り消されず、death が不在開始 (15) に確定すること
    # 【期待値確認】: REQ-201 の過剰適用を防ぎ、真の消滅を検出
    assert result["A"].death_frame == 15  # 【確認内容】: 窓充足で death 確定・取り消されない 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（ヒステリシス等号境界）
# ---------------------------------------------------------------------------


def test_birth_boundary_exactly_n_frames():
    # 【テスト目的】: birth 確定は連続 N フレームで、N-1 では未確定 (off-by-one 防止) を確認 (B-01)
    # 【テスト内容】: (a) frame 10,11 のみ present("B") → N-1=2、(b) frame 10,11,12 present("B") → N=3
    # 【期待される動作】: (a) birth 未確定でキーなし、(b) birth_frame==10
    # 🔵 信頼性レベル: 完了条件① / TC-103-01/03 の等号境界に直接依拠

    # 【テストデータ準備】: (a) 確定閾値直前 (2 フレーム) — 以降不在で連続を断つ
    # 【初期条件設定】: hysteresis=3。連続 present が 2 フレームで止まる
    tracker_a = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    for f in range(10):
        tracker_a.observe(f, ())
    tracker_a.observe(10, ("B",))
    tracker_a.observe(11, ("B",))
    for f in range(12, 15):
        tracker_a.observe(f, ())
    result_a = tracker_a.finalize()

    # 【結果検証】: N-1=2 フレームでは birth 確定してはならない
    # 【期待値確認】: 連続 2 フレームは閾値未満でキーなし
    assert "B" not in result_a  # 【確認内容】: N-1 では birth 未確定 (off-by-one 防止) 🔵

    # 【テストデータ準備】: (b) 確定閾値直後 (3 フレーム) — ちょうど窓を満たす
    # 【初期条件設定】: hysteresis=3。連続 present が 3 フレーム到達
    tracker_b = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    for f in range(10):
        tracker_b.observe(f, ())
    for f in range(10, 13):
        tracker_b.observe(f, ("B",))
    result_b = tracker_b.finalize()

    # 【結果検証】: ちょうど N=3 で birth 確定し、記録は連続開始 (10)
    # 【期待値確認】: 等号境界で birth 成立
    assert result_b["B"].birth_frame == 10  # 【確認内容】: N で birth 確定・連続開始フレーム 🔵


def test_death_cancelled_at_window_minus_one():
    # 【テスト目的】: 不在 N-1 フレームで再出現すると death 取り消し (窓内境界) を確認 (B-02)
    # 【テスト内容】: frame 0..14 present("A")、frame 15,16 不在 (=N-1=2)、frame 17 present("A")
    # 【期待される動作】: 不在ランがちょうど hysteresis-1 のとき再出現で取り消す
    # 🔵 信頼性レベル: REQ-201 / TC-103-04 の等号境界 (E-03 と対) に直接依拠

    # 【テストデータ準備】: 取り消し可能な最大の不在長 (N-1=2) を再現
    # 【初期条件設定】: hysteresis=3。不在 15,16 は N-1 で窓を満たさない
    tracker = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    for f in range(15):
        tracker.observe(f, ("A",))
    tracker.observe(15, ())
    tracker.observe(16, ())
    tracker.observe(17, ("A",))

    # 【実際の処理実行】: finalize で A のライフサイクルを確定
    result = tracker.finalize()

    # 【結果検証】: N-1 の不在は取り消され death が立たない (N は E-03 で確定と対)
    # 【期待値確認】: death 窓の等号境界 (N-1 は取り消し)
    assert result["A"].death_frame is None  # 【確認内容】: 不在 N-1 で再出現→death 未確定 🔵


def test_single_frame_observation_no_birth():
    # 【テスト目的】: 単一フレーム観測では hysteresis 未達で birth 未確定・例外なしを確認 (B-03 / EDGE-101)
    # 【テスト内容】: frame 0 のみ present("A")、以降 observe せず finalize、hysteresis=3
    # 【期待される動作】: 観測列長 1 は hysteresis(3) 未達で birth 未確定 (キーなし)、例外を送出しない
    # 🟡 信頼性レベル: EDGE-101 / 要件定義 4 章に依拠

    # 【テストデータ準備】: 最小の非空観測 (フレーム 1 件) = 単発解析と等価
    # 【初期条件設定】: hysteresis=3。連続 present は 1 フレームのみ
    tracker = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    tracker.observe(0, ("A",))

    # 【実際の処理実行】: 1 フレームのみで finalize (縮退安全性を検証)
    result = tracker.finalize()

    # 【結果検証】: 空 (E-02) と複数フレームの中間で破綻せず birth 未確定であること
    # 【期待値確認】: hysteresis 未達で相キーを含めない
    assert "A" not in result  # 【確認内容】: 1 フレームは hysteresis 未達で birth 未確定 🟡


def test_confidence_is_presence_fraction():
    # 【テスト目的】: 部分存在の相の confidence が存在フレーム率になることを確認 (B-04)
    # 【テスト内容】: hysteresis=3。frame 0..6 present("D") (7/10)、frame 7..9 不在
    # 【期待される動作】: confidence = 存在フレーム数 / 総観測フレーム数 = 7/10 = 0.7 (0<c<1)
    # 🟡 信頼性レベル: 完了条件⑤の裏 / confidence 算出式 (総観測フレーム分母) は実装時確定

    # 【テストデータ準備】: confidence が 0 でも 1 でもない中間値になる代表ケース
    # 【初期条件設定】: hysteresis=3。D は 7 フレーム連続 present で birth 確定後 3 フレーム不在
    tracker = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    for f in range(7):
        tracker.observe(f, ("D",))
    for f in range(7, 10):
        tracker.observe(f, ())

    # 【実際の処理実行】: finalize で D のライフサイクルを確定
    lc = tracker.finalize()["D"]

    # 【結果検証】: 存在フレーム率の分母 (総観測 10) / 分子 (present 7) を固定
    # 【期待値確認】: 7/10=0.7 かつ [0,1] 範囲内 (0<c<1)
    assert lc.confidence == pytest.approx(0.7)  # 【確認内容】: 存在フレーム率 7/10=0.7 🟡
    assert 0.0 < lc.confidence < 1.0  # 【確認内容】: 部分存在で confidence は開区間 (0,1) 🟡
