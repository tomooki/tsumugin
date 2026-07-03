"""TASK-0015 FrameSeries (sequential/series.py) の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/sequential/series.py``: ``FrameSeries`` (frozen dataclass + ``n_frames`` + 形状検証)
- ``src/tsumugin/sequential/__init__.py``: ``FrameSeries`` の re-export

時系列 (時間/温度軸) の粉末回折フレーム列を保持する不変値オブジェクト ``FrameSeries`` を検証する。
``two_theta`` (共通グリッド) / ``intensities`` ((n_frames, n_points)) / ``axis_values`` / ``axis_kind`` /
``channels`` (TASK-0011 の ``ExternalChannel``) を保持し、``__post_init__`` で形状不一致を明示エラーにする。

書式は ``tests/test_model_m2.py`` (TASK-0011) を範とし、frozen 検証は ``FrozenInstanceError``、
近似は ``pytest.approx`` を用いる。テストケース定義 (FrameSeries 9 件: 正常系 3 / 異常系 3 / 境界値 3) に 1:1 対応する。

対象モジュール未実装のため ``FrameSeries`` の import が collection 時に失敗し、
本ファイルの全テストがエラー(=失敗)になる想定 (Red フェーズ)。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from tsumugin.model import ExternalChannel
from tsumugin.sequential.series import FrameSeries

# 共通の観測グリッド (全フレーム共通の 2θ)。状態を持たないためモジュールレベルで一度だけ構築。
TWO_THETA = np.arange(15.0, 80.0, 0.02)
N_POINTS = len(TWO_THETA)


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_frameseries_holds_fields_and_n_frames():
    # 【テスト目的】: FrameSeries を全フィールド明示で生成し各属性と n_frames を確認 (TC-S-N01)
    # 【テスト内容】: 3 フレームの温度シーケンシャル入力を生成し n_frames == intensities.shape[0] を検証
    # 【期待される動作】: frozen 値オブジェクトとして生成され n_frames が強度行列の行数を返す
    # 🔵 信頼性レベル: interfaces.py L62-73 (FrameSeries 契約) に直接依拠

    # 【テストデータ準備】: 3 フレーム・共通グリッドの温度シーケンシャル入力という代表ケースを再現
    # 【初期条件設定】: intensities は (3, N_POINTS) の 2D 配列、軸値は温度 3 点
    intensities = np.zeros((3, N_POINTS))
    fs = FrameSeries(
        two_theta=TWO_THETA,
        intensities=intensities,
        axis_values=(300.0, 310.0, 320.0),
        axis_kind="temperature",
        channels=(),
    )

    # 【結果検証】: 各フィールドが保持され n_frames が axis_values 長ではなく行数由来であること
    # 【期待値確認】: interfaces.py のフィールド定義と n_frames = intensities.shape[0] に一致
    assert fs.n_frames == 3  # 【確認内容】: n_frames が intensities 行数を返す 🔵
    assert fs.axis_kind == "temperature"  # 【確認内容】: 軸種別が保持される 🔵
    assert fs.axis_values == (300.0, 310.0, 320.0)  # 【確認内容】: フレーム軸値が保持される 🔵
    assert fs.two_theta is TWO_THETA  # 【確認内容】: 共通グリッドが参照保持される 🔵
    assert fs.intensities.shape == (3, N_POINTS)  # 【確認内容】: 強度行列形状が保持される 🔵


def test_frameseries_retains_external_channels():
    # 【テスト目的】: channels に温度 ExternalChannel を紐付けて保持できることを確認 (TC-S-N02 / REQ-006)
    # 【テスト内容】: channels に温度チャネルを渡し tuple 保持と value_for の再利用を検証
    # 【期待される動作】: TASK-0011 の ExternalChannel が無改変でそのまま格納される
    # 🔵 信頼性レベル: REQ-006 / interfaces.py L72 / model/channel.py に直接依拠

    # 【テストデータ準備】: 高温モードで温度ログをフレームへ同期する中核経路 (REQ-006 / FR-321) を再現
    # 【初期条件設定】: 2 フレーム・温度チャネル (frame0→300, frame1→310) を紐付け
    channel = ExternalChannel("temperature", {0: 300.0, 1: 310.0})
    fs = FrameSeries(
        two_theta=TWO_THETA,
        intensities=np.zeros((2, N_POINTS)),
        axis_values=(300.0, 310.0),
        axis_kind="temperature",
        channels=(channel,),
    )

    # 【結果検証】: channels が tuple[ExternalChannel, ...] として保持され value_for が引けること
    # 【期待値確認】: REQ-006 (ExternalChannel をフレームへ紐付け) / interfaces.py L72
    assert len(fs.channels) == 1  # 【確認内容】: channels が 1 件保持される 🔵
    assert fs.channels[0].value_for(1) == pytest.approx(310.0)  # 【確認内容】: 既存モデル再利用 🔵
    assert fs.channels[0].kind == "temperature"  # 【確認内容】: チャネル種別が保持される 🔵


def test_frameseries_axis_kind_and_values():
    # 【テスト目的】: axis_kind="time" と対応 axis_values の明示保持を確認 (TC-S-N03)
    # 【テスト内容】: 時間軸シーケンシャル (4 フレーム) を生成し軸メタデータの独立保持を検証
    # 【期待される動作】: Literal 軸種別と float タプル軸値が独立に保持される
    # 🔵 信頼性レベル: interfaces.py L70-71 に直接依拠

    # 【テストデータ準備】: 時間軸シーケンシャル (§4 sequence_axis) の代表を再現
    # 【初期条件設定】: intensities は (4, N_POINTS)、時間軸値 (0,1,2,3)
    fs = FrameSeries(
        two_theta=TWO_THETA,
        intensities=np.zeros((4, N_POINTS)),
        axis_values=(0.0, 1.0, 2.0, 3.0),
        axis_kind="time",
    )

    # 【結果検証】: axis_kind と axis_values が独立に保持され n_frames と整合すること
    # 【期待値確認】: interfaces.py L70-71 の軸メタデータ定義に一致
    assert fs.axis_kind == "time"  # 【確認内容】: 軸種別 time が保持される 🔵
    assert fs.axis_values == (0.0, 1.0, 2.0, 3.0)  # 【確認内容】: 時間軸値が保持される 🔵
    assert fs.n_frames == 4  # 【確認内容】: axis_values 長と n_frames が整合 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（形状検証の明示エラー・非破壊契約）
# ---------------------------------------------------------------------------


def test_frameseries_column_mismatch_raises():
    # 【テスト目的】: intensities 列数 != two_theta 長で明示エラーになることを確認 (TC-S-E01 / 完了条件①)
    # 【テスト内容】: 列数 10 (!= N_POINTS) の強度行列で生成し ValueError 送出を検証
    # 【期待される動作】: 強度行列とグリッドの不整合を生成時点で弾く (縮退 None ではなく明示エラー)
    # 🟡 信頼性レベル: 完了条件① に依拠。エラー型 ValueError は backends/base.py:61 の入力検証慣習に準拠

    # 【テストデータ準備】: 別グリッドで測定したフレームを誤って束ねる不正入力を再現
    # 【初期条件設定】: intensities 列数 10 がグリッド長 N_POINTS と一致しない
    with pytest.raises(ValueError):
        FrameSeries(
            two_theta=TWO_THETA,
            intensities=np.zeros((3, 10)),
        )  # 【確認内容】: 列数不一致は生成時に明示エラー (副作用なし) 🟡


def test_frameseries_axis_values_length_mismatch_raises():
    # 【テスト目的】: 非空 axis_values の長さ != n_frames で明示エラーを確認 (TC-S-E02 / 完了条件①)
    # 【テスト内容】: 3 フレームに対し軸値 2 点を渡し ValueError 送出を検証
    # 【期待される動作】: 軸値とフレームのずれを生成時点で弾く
    # 🟡 信頼性レベル: 完了条件① / interfaces.py L69-70 に依拠 (妥当な推測)

    # 【テストデータ準備】: 温度ログの行数と測定フレーム数の食い違いを再現
    # 【初期条件設定】: intensities 3 行に対し axis_values は 2 点 (長さ不一致)
    with pytest.raises(ValueError):
        FrameSeries(
            two_theta=TWO_THETA,
            intensities=np.zeros((3, N_POINTS)),
            axis_values=(300.0, 310.0),
        )  # 【確認内容】: 軸値長 != n_frames は明示エラー 🟡


def test_frameseries_is_frozen():
    # 【テスト目的】: FrameSeries が frozen でフィールド再代入不可であることを確認 (TC-S-E03)
    # 【テスト内容】: 生成後に axis_kind へ再代入し FrozenInstanceError を検証
    # 【期待される動作】: dataclasses.FrozenInstanceError が送出される (P2 不変値オブジェクト)
    # 🔵 信頼性レベル: CLAUDE.md frozen 規約 / test_model_m2.py の frozen 検証パターンに直接依拠

    # 【テストデータ準備】: 共有された FrameSeries が事後改変されない保証を検証する対象を用意
    # 【初期条件設定】: 正常な 2 フレーム FrameSeries を生成
    fs = FrameSeries(
        two_theta=TWO_THETA,
        intensities=np.zeros((2, N_POINTS)),
    )

    # 【結果検証】: フィールド再代入で FrozenInstanceError が送出されること
    # 【期待値確認】: frozen=True では属性再代入が禁止される
    with pytest.raises(FrozenInstanceError):
        fs.axis_kind = "time"  # type: ignore[misc]  # 【確認内容】: frozen のため再代入不可 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（単一フレーム・空軸値・形状ちょうど一致）
# ---------------------------------------------------------------------------


def test_frameseries_single_frame():
    # 【テスト目的】: 単一フレーム (n_frames=1) で構築でき形状検証を通ることを確認 (TC-S-B01)
    # 【テスト内容】: (1, N_POINTS) の強度行列と 1 点軸値で生成し n_frames==1 を検証
    # 【期待される動作】: 1 行の 2D 形状が 1D と誤解されず n_frames==1 を返す
    # 🔵 信頼性レベル: EDGE-101 (単一フレーム) / interfaces.py に依拠

    # 【テストデータ準備】: 静的単一パターン解析を逐次 API で扱う最小非空ケースを再現
    # 【初期条件設定】: intensities は (1, N_POINTS)、温度軸値 1 点
    fs = FrameSeries(
        two_theta=TWO_THETA,
        intensities=np.zeros((1, N_POINTS)),
        axis_values=(300.0,),
        axis_kind="temperature",
    )

    # 【結果検証】: 生成成功かつ n_frames==1 (intensities.shape[0] 由来)
    # 【期待値確認】: 最小フレーム数でも複数フレームと同一検証ロジックが通る
    assert fs.n_frames == 1  # 【確認内容】: 単一フレームで n_frames==1 🔵


def test_frameseries_empty_axis_values_is_index():
    # 【テスト目的】: 空 axis_values (既定) が index 軸として検証免除されることを確認 (TC-S-B02)
    # 【テスト内容】: axis_values / axis_kind を省略して生成し既定値と検証免除を検証
    # 【期待される動作】: 空軸値では長さ検証をスキップし n_frames は intensities 由来
    # 🔵 信頼性レベル: interfaces.py L70「空なら index」に直接依拠

    # 【テストデータ準備】: 軸メタデータのない生フレーム列 (5 フレーム) を再現
    # 【初期条件設定】: axis_values / axis_kind を一切指定しない (既定 () / "index")
    fs = FrameSeries(
        two_theta=TWO_THETA,
        intensities=np.zeros((5, N_POINTS)),
    )

    # 【結果検証】: 生成成功かつ既定値が保たれ空軸値が長さ不一致と誤判定されないこと
    # 【期待値確認】: interfaces.py の既定 () / "index" と検証免除規則
    assert fs.axis_values == ()  # 【確認内容】: axis_values 既定は空 tuple 🔵
    assert fs.axis_kind == "index"  # 【確認内容】: axis_kind 既定は index 🔵
    assert fs.n_frames == 5  # 【確認内容】: 空軸値でも n_frames は intensities 由来 🔵


def test_frameseries_exact_shape_ok():
    # 【テスト目的】: 形状ちょうど一致で構築成功することを確認 (TC-S-B03 / 検証の許可側境界)
    # 【テスト内容】: intensities.shape==(3,N_POINTS) かつ len(axis_values)==3 で例外なし生成を検証
    # 【期待される動作】: 「等しい」を「不一致」と誤判定しない (off-by-one 検出)
    # 🔵 信頼性レベル: 完了条件① / interfaces.py に依拠 (TC-S-E01/E02 と境界を挟んで対称)

    # 【テストデータ準備】: 正しく整形された標準入力 (3 フレーム) を再現
    # 【初期条件設定】: 列数・フレーム数ともグリッド/軸値とちょうど一致
    fs = FrameSeries(
        two_theta=TWO_THETA,
        intensities=np.zeros((3, N_POINTS)),
        axis_values=(0.0, 1.0, 2.0),
    )

    # 【結果検証】: 例外なく生成され n_frames==3 であること
    # 【期待値確認】: 検証条件が厳密不一致 (!=) で許可側 (==) を弾かないこと
    assert fs.n_frames == 3  # 【確認内容】: 形状ちょうど一致で構築成功 🔵
