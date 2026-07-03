"""TASK-0011 model 拡張 (PhaseLifecycle / ExternalChannel / frame_range) の失敗テスト (TDD Red)。

対象実装:
- ``src/tsumugin/model/phase.py``: ``PhaseLifecycle`` 新設 + ``PhaseInstance.lifecycle`` 追加 (未実装)
- ``src/tsumugin/model/hypothesis.py``: ``Hypothesis.frame_range`` 追加 (未実装)
- ``src/tsumugin/model/channel.py``: ``ExternalChannel`` 新設 (未実装)
- ``src/tsumugin/model/__init__.py``: ``PhaseLifecycle`` / ``ExternalChannel`` の re-export (未実装)

すべて既定値付きの非破壊追加 (REQ-404) で、既存モデルの位置引数・比較・生成を壊さない。
書式は ``tests/test_model.py`` を範とし、frozen 検証は ``FrozenInstanceError``、
近似は ``pytest.approx`` を用いる。テストケース定義 (15 件: 正常系 7 / 異常系 3 / 境界値 5) に 1:1 対応する。

未実装のため ``PhaseLifecycle`` / ``ExternalChannel`` の import が collection 時に失敗し、
本ファイルの全テストがエラー(=失敗)になる想定 (Red フェーズ)。
"""

from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError

from tsumugin.model import (
    ExternalChannel,
    Hypothesis,
    LatticeParams,
    PhaseInstance,
    PhaseLifecycle,
)


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_phase_lifecycle_explicit_construction_holds_attributes():
    # 【テスト目的】: PhaseLifecycle が指定値で生成でき各属性を独立に読み出せることを確認 (N-01)
    # 【テスト内容】: birth_frame/death_frame/confidence を明示指定して生成し属性値を検証
    # 【期待される動作】: frozen dataclass として生成され 3 フィールドが指定どおり保持される
    # 🔵 信頼性: 要件定義 2.1 / interfaces.py L31-37 に依拠

    # 【テストデータ準備】: 相 B が frame 10 出現・frame 15 消滅・確信度 0.8 という代表的ライフサイクル
    # 【初期条件設定】: 3 フィールドすべてを明示指定した状態を再現
    lc = PhaseLifecycle(birth_frame=10, death_frame=15, confidence=0.8)

    # 【結果検証】: 各フィールドが指定値どおり独立に保持されること
    # 【期待値確認】: interfaces.py のフィールド定義に一致する値を保持
    assert lc.birth_frame == 10  # 【確認内容】: 出現フレームが指定どおり保持される 🔵
    assert lc.death_frame == 15  # 【確認内容】: 消滅フレームが指定どおり保持される 🔵
    assert lc.confidence == pytest.approx(0.8)  # 【確認内容】: 存在確信度が指定どおり保持される 🔵


def test_phase_lifecycle_equality_is_structural():
    # 【テスト目的】: 同一フィールド値は ==、異なる値は != となる値等価を確認 (N-02)
    # 【テスト内容】: birth_frame のみ指定した 2 インスタンスの等価/不等価を検証
    # 【期待される動作】: dataclass 自動生成の __eq__ が既定値込みで構造的に比較する
    # 🔵 信頼性: 要件定義 2.1 に依拠

    # 【テストデータ準備】: 値オブジェクトとしての等価性 (M0/M1 不変値オブジェクト規約) を代表
    # 【初期条件設定】: birth_frame 以外は既定 (death_frame=None, confidence=1.0) のまま比較
    same_a = PhaseLifecycle(birth_frame=3)
    same_b = PhaseLifecycle(birth_frame=3)
    other = PhaseLifecycle(birth_frame=4)

    # 【結果検証】: 構造的等価と不等価が成立すること
    # 【期待値確認】: dataclass eq=True (既定) による値比較
    assert same_a == same_b  # 【確認内容】: 同値インスタンスが等価 (既定値も比較に含む) 🔵
    assert same_a != other  # 【確認内容】: birth_frame が異なれば不等価 🔵


def test_external_channel_value_for_existing_frame_returns_value():
    # 【テスト目的】: ExternalChannel を生成し value_for(存在フレーム) が対応値を返すことを確認 (N-03)
    # 【テスト内容】: 温度チャネルを生成し既存キーの value_for と kind/label 既定を検証
    # 【期待される動作】: sync_map に存在するキーで float 値を返す (TC-105-01)
    # 🔵 信頼性: 要件定義 2.4 / TC-105-01 / interfaces.py L44-54 に依拠

    # 【テストデータ準備】: frame 0→300.0, frame 1→310.0 の温度同期 (高温モードの中核) を代表
    # 【初期条件設定】: 位置必須引数 kind/sync_map で生成し label は既定 None
    channel = ExternalChannel(kind="temperature", sync_map={0: 300.0, 1: 310.0})

    # 【実際の処理実行】: 存在フレーム 1 の同期値を要求
    # 【処理内容】: sync_map.get(1) 相当
    result = channel.value_for(1)

    # 【結果検証】: 対応 float 値と生成時の属性を確認
    # 【期待値確認】: value_for 契約 (sync_map.get) と位置引数生成の結果
    assert result == pytest.approx(310.0)  # 【確認内容】: 存在フレームは対応値を返す 🔵
    assert channel.kind == "temperature"  # 【確認内容】: kind が位置引数どおり保持される 🔵
    assert channel.label is None  # 【確認内容】: label が既定 None 🔵


def test_external_channel_equality_with_mapping_field():
    # 【テスト目的】: 同一 kind/sync_map/label の 2 インスタンスが == となることを確認 (N-04)
    # 【テスト内容】: Mapping フィールドを含む frozen 値オブジェクトの等価比較を検証
    # 【期待される動作】: dict の == が要素比較するため Mapping 込みで等価が成立
    # 🔵 信頼性: 要件定義 2.4 / 3 に依拠

    # 【テストデータ準備】: Mapping を持つ frozen 値オブジェクト (既存 LatticeParams.sigma と同扱い) を代表
    # 【初期条件設定】: 同一内容の time チャネルを 2 つ生成 (ハッシュ化はしない)
    ch_a = ExternalChannel("time", {0: 0.0})
    ch_b = ExternalChannel("time", {0: 0.0})

    # 【結果検証】: Mapping フィールドを含んで構造的に等価であること
    # 【期待値確認】: dict の == が要素比較する
    assert ch_a == ch_b  # 【確認内容】: 同一 kind/sync_map/label は等価 (set/dict キー化はしない) 🔵


def test_phase_instance_lifecycle_with_updates_is_nondestructive():
    # 【テスト目的】: with_updates(lifecycle=...) で lifecycle を非破壊付与できることを確認 (N-05)
    # 【テスト内容】: 既存 PhaseInstance に lifecycle を差し替え元インスタンスの不変性を検証
    # 【期待される動作】: replace により新インスタンスが返り元は lifecycle is None のまま (完了条件④)
    # 🔵 信頼性: 要件定義 2.2 / 完了条件④ / phase.py L43-45 に依拠

    # 【テストデータ準備】: 逐次精密化で確定した lifecycle を相へ紐付ける実運用フローを再現
    # 【初期条件設定】: lifecycle 未設定 (既定 None) の相 A を用意
    p = PhaseInstance("A", LatticeParams(5, 5, 5))
    q = p.with_updates(lifecycle=PhaseLifecycle(birth_frame=3))

    # 【結果検証】: 新インスタンスにのみ lifecycle が付与され元は不変であること
    # 【期待値確認】: with_updates が dataclasses.replace 実装のため追加フィールドで自動対応
    assert q.lifecycle == PhaseLifecycle(birth_frame=3)  # 【確認内容】: 新インスタンスに lifecycle 付与 🔵
    assert p.lifecycle is None  # 【確認内容】: 元インスタンスは lifecycle 未変更 (P2 不変性) 🔵
    assert q is not p  # 【確認内容】: 非破壊更新で別インスタンスが返る 🔵


def test_hypothesis_frame_range_explicit_construction():
    # 【テスト目的】: Hypothesis(..., frame_range=(10,20)) が生成でき値を保持することを確認 (N-06)
    # 【テスト内容】: frame_range を明示付与した仮説を生成し値と既存既定の維持を検証
    # 【期待される動作】: frozen 維持で frame_range が tuple として保持される
    # 🔵 信頼性: 要件定義 2.3 / interfaces.py L41 に依拠

    # 【テストデータ準備】: changepoint 後に採択された仮説の有効フレーム区間を代表
    # 【初期条件設定】: 既存フィールドは既定のまま frame_range のみ明示指定
    h = Hypothesis(id="h", phases=(), frame_range=(10, 20))

    # 【結果検証】: frame_range が保持され既存フィールドの既定が変わっていないこと
    # 【期待値確認】: interfaces.py L41 の追加フィールド定義に一致
    assert h.frame_range == (10, 20)  # 【確認内容】: 有効フレーム区間が tuple で保持される 🔵
    assert h.status == "candidate"  # 【確認内容】: 既存フィールドの既定値が不変 🔵


def test_model_reexports_new_symbols_in_dunder_all():
    # 【テスト目的】: model パッケージから新シンボルが re-export され __all__ に収載されることを確認 (N-07)
    # 【テスト内容】: from tsumugin.model import PhaseLifecycle, ExternalChannel の解決と __all__ を検証
    # 【期待される動作】: model/__init__.py で import + __all__ 追加済み
    # 🔵 信頼性: 要件定義 2.5 / __init__.py に依拠

    # 【テストデータ準備】: 後続タスクが公開 API 経由で参照する経路を代表
    # 【初期条件設定】: model パッケージをモジュールとして取得
    import tsumugin.model as m

    # 【結果検証】: 両シンボルが解決可能かつ __all__ に収載されていること
    # 【期待値確認】: 要件定義 2.5 の re-export スコープ (top-level 昇格はテストしない)
    assert m.PhaseLifecycle is PhaseLifecycle  # 【確認内容】: PhaseLifecycle が解決可能 🔵
    assert m.ExternalChannel is ExternalChannel  # 【確認内容】: ExternalChannel が解決可能 🔵
    assert "PhaseLifecycle" in m.__all__  # 【確認内容】: PhaseLifecycle が __all__ に収載 🔵
    assert "ExternalChannel" in m.__all__  # 【確認内容】: ExternalChannel が __all__ に収載 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（エラーハンドリング）
# ---------------------------------------------------------------------------


def test_phase_lifecycle_is_frozen():
    # 【テスト目的】: frozen dataclass のフィールド再代入が禁止されることを確認 (E-01)
    # 【テスト内容】: PhaseLifecycle の confidence へ再代入を試みる
    # 【期待される動作】: dataclasses.FrozenInstanceError が送出される
    # 🔵 信頼性: 要件定義 3 frozen 制約 / test_model.py の frozen 検証パターンに依拠

    # 【テストデータ準備】: 不変値オブジェクト (P2) の不変性保証を検証する対象を用意
    # 【初期条件設定】: 全既定値で生成した lifecycle
    lc = PhaseLifecycle()

    # 【結果検証】: 再代入で FrozenInstanceError が送出されること
    # 【期待値確認】: frozen=True では属性再代入が禁止される
    with pytest.raises(FrozenInstanceError):
        lc.confidence = 0.5  # type: ignore[misc]  # 【確認内容】: frozen のため再代入不可 🔵


def test_external_channel_is_frozen():
    # 【テスト目的】: ExternalChannel のフィールド再代入が禁止されることを確認 (E-02)
    # 【テスト内容】: ExternalChannel の label へ再代入を試みる
    # 【期待される動作】: dataclasses.FrozenInstanceError が送出される
    # 🔵 信頼性: 要件定義 3 frozen 制約に依拠

    # 【テストデータ準備】: チャネル設定を後から書き換える誤用の防御を検証する対象を用意
    # 【初期条件設定】: frame 0 のみ持つ温度チャネル
    ch = ExternalChannel("temperature", {0: 300.0})

    # 【結果検証】: 再代入で FrozenInstanceError が送出されること
    # 【期待値確認】: frozen=True のため再代入不可で sync_map 同期の一貫性を破壊しない
    with pytest.raises(FrozenInstanceError):
        ch.label = "x"  # type: ignore[misc]  # 【確認内容】: frozen のため再代入不可 🔵


def test_value_for_missing_frame_returns_none():
    # 【テスト目的】: value_for が欠損フレームで None を返し例外を出さないことを確認 (E-03 / EDGE-102)
    # 【テスト内容】: sync_map に無い frame_index を value_for に渡す
    # 【期待される動作】: None を返し KeyError 等を送出しない
    # 🔵 信頼性: 要件定義 2.4/4.3 / EDGE-102 / TC-105-02 / interfaces.py L52-54 に依拠

    # 【テストデータ準備】: frame 0 のみ持つ温度チャネルを用意 (frame 5 は欠損)
    # 【初期条件設定】: 温度ログとフレーム数の不一致という実運用状況を再現
    channel = ExternalChannel(kind="temperature", sync_map={0: 300.0})

    # 【実際の処理実行】: 欠損フレーム 5 の値を要求
    # 【処理内容】: sync_map.get(5) 相当
    result = channel.value_for(5)

    # 【結果検証】: None が返り例外が出ないこと
    # 【期待値確認】: 欠損は None を返し上位が軸値 None + 警告として扱う (P5 縮退規約)
    assert result is None  # 【確認内容】: 欠損フレームは None (例外なし) 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（最小値、最大値、null 等）
# ---------------------------------------------------------------------------


def test_phase_lifecycle_all_defaults():
    # 【テスト目的】: 引数なし生成 PhaseLifecycle() が既定 (None/None/1.0) で成立することを確認 (B-01)
    # 【テスト内容】: 全フィールド既定値での縮退生成を検証
    # 【期待される動作】: すべて既定値でも frozen 値オブジェクトとして生成可能
    # 🔵 信頼性: 要件定義 2.1/4.3 / interfaces.py L35-37 に依拠

    # 【テストデータ準備】: 未追跡・未確定の相に付与される初期状態を代表
    # 【初期条件設定】: 引数を一切指定せず生成 (REQ-404 非破壊追加の前提)
    lc = PhaseLifecycle()

    # 【結果検証】: 既定値が interfaces.py の定義どおりであること
    # 【期待値確認】: birth_frame/death_frame は None、confidence は 1.0
    assert lc.birth_frame is None  # 【確認内容】: 出現フレーム既定 None 🔵
    assert lc.death_frame is None  # 【確認内容】: 消滅フレーム既定 None 🔵
    assert lc.confidence == pytest.approx(1.0)  # 【確認内容】: 確信度既定 1.0 🔵


def test_phase_instance_positional_construction_lifecycle_default_none():
    # 【テスト目的】: 既存の位置引数生成が新フィールド追加後も lifecycle 既定 None で通ることを確認 (B-02)
    # 【テスト内容】: 位置引数のみで PhaseInstance を生成し後方互換と既定を検証
    # 【期待される動作】: 追加フィールドが末尾・既定 None のため既存呼び出しを壊さない
    # 🔵 信頼性: 要件定義 2.2/4.3 / REQ-404 / phase.py L34-41 に依拠

    # 【テストデータ準備】: M0/M1 コードが従来どおり PhaseInstance を構築する経路を再現
    # 【初期条件設定】: 既存テスト同型の位置引数呼び出し
    p = PhaseInstance("x", LatticeParams(5, 5, 5))

    # 【結果検証】: 生成成功かつ lifecycle 既定 None、既存フィールドが不変であること
    # 【期待値確認】: 位置引数の並びが変わっておらず既存 226 テストと同じ生成が通る
    assert p.lifecycle is None  # 【確認内容】: 追加フィールド lifecycle が既定 None 🔵
    assert p.scale == pytest.approx(1.0)  # 【確認内容】: 既存フィールド scale の既定が不変 🔵


def test_hypothesis_minimal_construction_frame_range_default_none():
    # 【テスト目的】: 既存キーワード生成が新フィールド追加後も frame_range 既定 None で通ることを確認 (B-03)
    # 【テスト内容】: 最小引数で Hypothesis を生成し後方互換と既存既定の維持を検証
    # 【期待される動作】: 追加フィールドが末尾・既定 None のため既存呼び出しを壊さない
    # 🔵 信頼性: 要件定義 2.3/4.3 / REQ-404 / hypothesis.py L25-34 に依拠

    # 【テストデータ準備】: 木探索・裁定が Hypothesis を構築する既存経路を再現 (test_defaults 同型)
    # 【初期条件設定】: id と空 phases のみ指定
    h = Hypothesis(id="h", phases=())

    # 【結果検証】: 生成成功かつ frame_range 既定 None、既存既定が維持されること
    # 【期待値確認】: 既存の既定値が変わっていない
    assert h.frame_range is None  # 【確認内容】: 追加フィールド frame_range が既定 None 🔵
    assert h.status == "candidate"  # 【確認内容】: 既存フィールド status の既定が不変 🔵
    assert h.accepted_by is None  # 【確認内容】: 既存フィールド accepted_by の既定が不変 🔵


def test_empty_sync_map_value_for_always_none():
    # 【テスト目的】: 空 sync_map の ExternalChannel が value_for で常に None を返すことを確認 (B-04)
    # 【テスト内容】: 空写像 {} のチャネルへ value_for を呼び出す
    # 【期待される動作】: 空写像でも例外なく None を返す (EDGE-102 の下限)
    # 🟡 信頼性: 要件定義 3/4.3 からの妥当な推測 (EDGE-102 下限ケースの明示化)

    # 【テストデータ準備】: チャネルは定義されたが同期データ未投入というケースを代表
    # 【初期条件設定】: 全フレーム欠損という極端条件 (空 sync_map)
    channel = ExternalChannel("custom", {})

    # 【実際の処理実行】: frame 0 の値を要求
    # 【処理内容】: 空辞書に対する dict.get(0) 相当
    result = channel.value_for(0)

    # 【結果検証】: None が返り例外が出ないこと
    # 【期待値確認】: dict.get の空辞書挙動と一致し E-03 (部分欠損) と同じ縮退挙動
    assert result is None  # 【確認内容】: 空写像でも None (例外なし) 🟡


def test_phase_lifecycle_confidence_boundary_values():
    # 【テスト目的】: confidence の境界端点 [0.0, 1.0] をそのまま保持することを確認 (B-05)
    # 【テスト内容】: confidence=0.0 と confidence=1.0 の保持を検証
    # 【期待される動作】: 器のみのため範囲バリデーションせず渡した値をそのまま保持
    # 🟡 信頼性: 要件定義 4.4 / interfaces.py L37 の [0,1] 注記からの妥当な推測

    # 【テストデータ準備】: 後続 LifecycleTracker が算出した確信度 (0〜1) を保持する場面を代表
    # 【初期条件設定】: 下限 0.0 と上限 1.0 の 2 インスタンスを生成
    lower = PhaseLifecycle(confidence=0.0)
    upper = PhaseLifecycle(confidence=1.0)

    # 【結果検証】: 境界端点が丸め・クランプなくそのまま保持されること
    # 【期待値確認】: 範囲外バリデーションは本タスクでは行わない (要件定義 4.4 注意)
    assert lower.confidence == pytest.approx(0.0)  # 【確認内容】: 下限 0.0 を保持 🟡
    assert upper.confidence == pytest.approx(1.0)  # 【確認内容】: 上限 1.0 を保持 🟡
