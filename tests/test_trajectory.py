"""TASK-0017 Trajectory + FrameRecord + to_csv (sequential/trajectory.py) の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/sequential/trajectory.py``: ``FrameRecord`` / ``Trajectory`` (両 frozen dataclass)。
  ``Trajectory.to_csv(path)`` は stdlib ``csv`` で CSV を書き出し、書き出したパスを ``str`` で返す。
- ``src/tsumugin/sequential/__init__.py``: ``FrameRecord`` / ``Trajectory`` の re-export (``__all__`` 昇順追加)。

このファイルで凍結する CSV レイアウト契約 (要件 §2.3 / テストケース定義で確定):
- フレーム共通列 (固定・先頭順): frame_index, axis_value, temperature, rwp, chi2,
  changepoint, changepoint_reasons, refine_failed。
- 相ごと列: 全 records の phase_ref と lifecycles キーの和集合を ``sorted()`` 昇順で確定し、
  各 ref につき ``<ref>.a, <ref>.b, <ref>.c, <ref>.scale, <ref>.wt_frac,
  <ref>.birth_frame, <ref>.death_frame, <ref>.confidence`` を出力。
- bool 表現は ``str(bool)`` = "True"/"False"。数値は ``str(v)``。
- changepoint_reasons (tuple) は "|" 区切りで 1 セル化。空 tuple は空欄。
- None / 非有限 (inf/-inf/NaN) の数値セルは空文字列。有限端点 (0.0/負値/極小) は保持。

対象モジュール未実装のため import が collection 時に失敗し、本ファイル全テストがエラー(=失敗)になる (Red)。
書式は tests/test_lifecycle.py / test_changepoint.py に準拠。
"""

from __future__ import annotations

import csv
import dataclasses
import os

import pytest

from tsumugin.model import LatticeParams, PhaseInstance, PhaseLifecycle
from tsumugin.sequential import FrameRecord, Trajectory

# ---------------------------------------------------------------------------
# 凍結する列レイアウト定数 (テスト側で契約を固定)
# ---------------------------------------------------------------------------

FRAME_COMMON_COLUMNS = [
    "frame_index",
    "axis_value",
    "temperature",
    "rwp",
    "chi2",
    "changepoint",
    "changepoint_reasons",
    "refine_failed",
]
PHASE_FIELD_SUFFIXES = [
    "a",
    "b",
    "c",
    "scale",
    "wt_frac",
    "birth_frame",
    "death_frame",
    "confidence",
]
REASONS_DELIMITER = "|"


# ---------------------------------------------------------------------------
# 共通ヘルパ (Given の土台)
# ---------------------------------------------------------------------------


def _phase(ref="A", a=5.0, b=6.0, c=7.0, scale=1.0, wt_frac=0.5):
    """相 PhaseInstance を組む簡易ヘルパ (model/phase.py 既存型を再利用)。"""
    return PhaseInstance(
        phase_ref=ref,
        lattice=LatticeParams(a=a, b=b, c=c),
        scale=scale,
        wt_frac=wt_frac,
    )


def _record(
    frame_index=0,
    axis_value=None,
    temperature=None,
    phases=(),
    rwp=None,
    chi2=None,
    changepoint=False,
    changepoint_reasons=(),
    refine_failed=False,
):
    """FrameRecord を既定値付きで組む簡易ヘルパ (契約フィールド順に対応)。"""
    return FrameRecord(
        frame_index=frame_index,
        axis_value=axis_value,
        temperature=temperature,
        phases=phases,
        rwp=rwp,
        chi2=chi2,
        changepoint=changepoint,
        changepoint_reasons=changepoint_reasons,
        refine_failed=refine_failed,
    )


def _phase_columns(ref):
    """指定 ref の相ごと列名 (<ref>.a ... <ref>.confidence) を凍結順で返す。"""
    return [f"{ref}.{suffix}" for suffix in PHASE_FIELD_SUFFIXES]


def _read_rows(path):
    """csv.reader で全行 (ヘッダ含む) を読み戻す。newline/utf-8 を固定。"""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def _read_dicts(path):
    """csv.DictReader でデータ行を辞書列として読み戻す。"""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# 1. 正常系テストケース
# ---------------------------------------------------------------------------


def test_header_contains_required_columns(tmp_path):
    # 【テスト目的】: 生成 CSV のヘッダに必須列が全て含まれることを確認 (T-N01 / TC-104-01)
    # 【テスト内容】: 共通列 + 相 A の格子/scale/wt_frac/lifecycle 列がヘッダに現れるか検証
    # 【期待される動作】: 必須列がヘッダの部分集合として欠落なく存在する
    # 🔵 信頼性レベル: TC-104-01 / interfaces.py L141-165 / 完了条件① に直接依拠

    # 【テストデータ準備】: 相 A を含むフレーム 2 件 + lifecycles={"A": ...} を用意
    # 【初期条件設定】: 最小構成で必須列の存在を確認する
    traj = Trajectory(
        records=(_record(frame_index=0, phases=(_phase(),)),
                 _record(frame_index=1, phases=(_phase(),))),
        lifecycles={"A": PhaseLifecycle(birth_frame=0, death_frame=None, confidence=1.0)},
    )
    path = str(tmp_path / "traj.csv")

    # 【実際の処理実行】: to_csv で CSV を書き出す
    traj.to_csv(path)
    header = _read_rows(path)[0]

    # 【結果検証】: 共通列と相 A 列がヘッダに含まれること
    # 【期待値確認】: 完了条件①「必須列」を列の存在で担保
    for column in FRAME_COMMON_COLUMNS:
        assert column in header  # 【確認内容】: フレーム共通列が欠落しない 🔵
    for column in _phase_columns("A"):
        assert column in header  # 【確認内容】: 相 A の格子/scale/wt_frac/lifecycle 列が存在 🔵


def test_row_count_equals_frame_count(tmp_path):
    # 【テスト目的】: データ行数 (ヘッダ除く) == len(records) を確認 (T-N02 / TC-104-02)
    # 【テスト内容】: records 長 3 の Trajectory を to_csv し行数を検証
    # 【期待される動作】: ヘッダ 1 行 + フレーム 3 行 = 計 4 行
    # 🔵 信頼性レベル: TC-104-02 / 完了条件② に直接依拠

    # 【テストデータ準備】: 相 A を含む 3 フレームを用意
    # 【初期条件設定】: 「1 フレーム 1 行」を複数フレームで検証
    records = tuple(_record(frame_index=i, phases=(_phase(),)) for i in range(3))
    traj = Trajectory(records=records, lifecycles={"A": PhaseLifecycle()})
    path = str(tmp_path / "traj.csv")

    # 【実際の処理実行】: to_csv 後に csv.reader / DictReader で読み戻す
    traj.to_csv(path)
    rows = _read_rows(path)
    dicts = _read_dicts(path)

    # 【結果検証】: 総行数とデータ行数がフレーム数に一致すること
    # 【期待値確認】: ヘッダを二重カウントしない
    assert len(rows) == 1 + 3  # 【確認内容】: ヘッダ 1 + データ 3 行 🔵
    assert len(dicts) == 3  # 【確認内容】: DictReader レコード数 = フレーム数 🔵


def test_common_columns_roundtrip(tmp_path):
    # 【テスト目的】: フレーム共通列の各値が CSV セルに正しく反映されることを確認 (T-N03)
    # 【テスト内容】: frame_index/axis_value/temperature/rwp/chi2/changepoint/refine_failed の往復
    # 【期待される動作】: 数値は str 化、bool は "True"/"False" で往復する
    # 🔵 信頼性レベル: interfaces.py L141-153 / 完了条件① に依拠

    # 【テストデータ準備】: 全共通列に有限・非 None 値を与える
    # 【初期条件設定】: changepoint=True / refine_failed=False で真偽表現を確認
    rec = _record(
        frame_index=5,
        axis_value=300.0,
        temperature=305.0,
        phases=(_phase(),),
        rwp=2.5,
        chi2=1.3,
        changepoint=True,
        changepoint_reasons=("rwp_jump",),
        refine_failed=False,
    )
    traj = Trajectory(records=(rec,), lifecycles={"A": PhaseLifecycle()})
    path = str(tmp_path / "traj.csv")

    # 【実際の処理実行】: to_csv 後に DictReader で 1 行目を取得
    traj.to_csv(path)
    row = _read_dicts(path)[0]

    # 【結果検証】: 各共通列の文字列表現が期待どおりであること
    # 【期待値確認】: 完了条件①「軸値/Rwp/changepoint」を値レベルで担保
    assert row["frame_index"] == "5"  # 【確認内容】: int の str 化 🔵
    assert row["axis_value"] == "300.0"  # 【確認内容】: 軸値の str 化 🔵
    assert row["temperature"] == "305.0"  # 【確認内容】: 温度の str 化 🔵
    assert row["rwp"] == "2.5"  # 【確認内容】: Rwp の str 化 🔵
    assert row["chi2"] == "1.3"  # 【確認内容】: chi2 の str 化 🔵
    assert row["changepoint"] == "True"  # 【確認内容】: bool 真表現を凍結 🔵
    assert row["refine_failed"] == "False"  # 【確認内容】: bool 偽表現を凍結 🔵


def test_phase_columns_values(tmp_path):
    # 【テスト目的】: 相 A の格子/scale/wt_frac と lifecycle 列の値が正しいことを確認 (T-N04)
    # 【テスト内容】: lattice.a/b/c・scale・wt_frac と lifecycles["A"] の birth/death/confidence
    # 【期待される動作】: 相の存在行に格子値、lifecycle 列は相メタとして全行一貫
    # 🔵 信頼性レベル: 完了条件① / interfaces.py L31-45,141-153 に依拠

    # 【テストデータ準備】: A=lattice(5,6,7),scale=1.0,wt_frac=0.5 / lifecycle(2,8,0.75)
    # 【初期条件設定】: death_frame=None でない (=8) ケースを確認
    a = _phase(ref="A", a=5.0, b=6.0, c=7.0, scale=1.0, wt_frac=0.5)
    traj = Trajectory(
        records=(_record(frame_index=0, phases=(a,)),),
        lifecycles={"A": PhaseLifecycle(birth_frame=2, death_frame=8, confidence=0.75)},
    )
    path = str(tmp_path / "traj.csv")

    # 【実際の処理実行】: to_csv 後に DictReader で 1 行目を取得
    traj.to_csv(path)
    row = _read_dicts(path)[0]

    # 【結果検証】: 相ごと列の格子/scale/wt_frac/lifecycle が対応
    # 【期待値確認】: 完了条件①「相ごと格子 abc/scale/wt_frac + lifecycle」
    assert row["A.a"] == "5.0"  # 【確認内容】: lattice.a 🔵
    assert row["A.b"] == "6.0"  # 【確認内容】: lattice.b 🔵
    assert row["A.c"] == "7.0"  # 【確認内容】: lattice.c 🔵
    assert row["A.scale"] == "1.0"  # 【確認内容】: scale 🔵
    assert row["A.wt_frac"] == "0.5"  # 【確認内容】: wt_frac 🔵
    assert row["A.birth_frame"] == "2"  # 【確認内容】: lifecycle birth 🔵
    assert row["A.death_frame"] == "8"  # 【確認内容】: lifecycle death (非 None) 🔵
    assert float(row["A.confidence"]) == pytest.approx(0.75)  # 【確認内容】: confidence 🔵


def test_to_csv_returns_input_path(tmp_path):
    # 【テスト目的】: to_csv(path) の戻り値が入力 path と等しくファイルが実在すること (T-N05)
    # 【テスト内容】: 戻り値の型・値とファイル存在を確認 (export_gpx 同一契約)
    # 【期待される動作】: 戻り値 == path (str) かつ os.path.exists(path) が True
    # 🔵 信頼性レベル: interfaces.py L163-165 / gpx.py 契約に依拠

    # 【テストデータ準備】: 相 A を含む単一フレーム
    # 【初期条件設定】: tmp_path 配下の書き出し先パスを用意
    traj = Trajectory(
        records=(_record(frame_index=0, phases=(_phase(),)),),
        lifecycles={"A": PhaseLifecycle()},
    )
    path = str(tmp_path / "out.csv")

    # 【実際の処理実行】: to_csv を呼び戻り値を取得
    result = traj.to_csv(path)

    # 【結果検証】: 戻り値が入力パスと一致しファイルが存在すること
    # 【期待値確認】: 書き出しパス返却契約 (export_gpx 同一)
    assert result == path  # 【確認内容】: 戻り値 == 入力 path 🔵
    assert isinstance(result, str)  # 【確認内容】: 戻り値型が str 🔵
    assert os.path.exists(path)  # 【確認内容】: CSV ファイルが実在 🔵


def test_changepoint_reasons_joined_single_cell(tmp_path):
    # 【テスト目的】: changepoint_reasons(tuple) が 1 セルへ決定論区切りで連結されること (T-N06)
    # 【テスト内容】: ("rwp_jump","new_peaks") が "rwp_jump|new_peaks" になるか検証
    # 【期待される動作】: 連結順は tuple 順、区切りは "|" で CSV デリミタと衝突しない
    # 🟡 信頼性レベル: 要件 §2.3 の 1 セル化は実装確定事項 (妥当な推測)

    # 【テストデータ準備】: 複数理由を持つ changepoint フレーム
    # 【初期条件設定】: 説明可能性 (FR-303) を 1 セルに落とす
    rec = _record(
        frame_index=0,
        phases=(_phase(),),
        changepoint=True,
        changepoint_reasons=("rwp_jump", "new_peaks"),
    )
    traj = Trajectory(records=(rec,), lifecycles={"A": PhaseLifecycle()})
    path = str(tmp_path / "traj.csv")

    # 【実際の処理実行】: to_csv 後に DictReader で 1 行目を取得
    traj.to_csv(path)
    row = _read_dicts(path)[0]

    # 【結果検証】: 区切り連結された 1 セル値であること
    # 【期待値確認】: tuple 順で決定論に連結
    assert row["changepoint_reasons"] == "rwp_jump" + REASONS_DELIMITER + "new_peaks"
    # 【確認内容】: 複数理由が 1 セルに "|" 連結される 🟡


# ---------------------------------------------------------------------------
# 2. 異常系テストケース
# ---------------------------------------------------------------------------


def test_failed_frame_blanks_and_no_nonfinite_leak(tmp_path):
    # 【テスト目的】: 失敗フレームで rwp/chi2 が空欄・非有限が漏れないこと (T-E01 / TC-104-03)
    # 【テスト内容】: rwp=None,chi2=inf,refine_failed=True の CSV 化を検証
    # 【期待される動作】: rwp/chi2 セルは空文字、inf/nan 文字列がファイルに出ない
    # 🔵 信頼性レベル: TC-104-03 / 完了条件③ / M1 教訓に直接依拠

    # 【テストデータ準備】: 精密化失敗フレーム (chi2=inf)
    # 【初期条件設定】: inf/nan が CSV に文字列として漏れないことを保証する
    rec = _record(
        frame_index=0,
        phases=(_phase(),),
        rwp=None,
        chi2=float("inf"),
        refine_failed=True,
    )
    traj = Trajectory(records=(rec,), lifecycles={"A": PhaseLifecycle()})
    path = str(tmp_path / "traj.csv")

    # 【実際の処理実行】: to_csv 後に行辞書とファイル全文を取得
    traj.to_csv(path)
    row = _read_dicts(path)[0]
    with open(path, encoding="utf-8") as f:
        text = f.read()

    # 【結果検証】: 非有限セルは空欄・真偽は真表現・inf/nan 文字列が全文に無い
    # 【期待値確認】: 完了条件③ の直接検証
    assert row["rwp"] == ""  # 【確認内容】: None は空欄 🔵
    assert row["chi2"] == ""  # 【確認内容】: inf は空欄 🔵
    assert row["refine_failed"] == "True"  # 【確認内容】: 失敗フラグ真表現 🔵
    for token in ("inf", "nan", "Infinity", "NaN"):
        assert token not in text  # 【確認内容】: 非有限文字列がファイルに漏れない 🔵


def test_phase_nonfinite_wt_frac_blank(tmp_path):
    # 【テスト目的】: 相の wt_frac が非有限のとき空欄化されることを確認 (T-E02)
    # 【テスト内容】: PhaseInstance(wt_frac=nan) の相列を検証
    # 【期待される動作】: A.wt_frac セルは空文字、nan/inf 文字列がファイルに出ない
    # 🟡 信頼性レベル: 完了条件③ を相列へ拡張した妥当な推測

    # 【テストデータ準備】: 相 A の wt_frac=nan (精密化縮退)
    # 【初期条件設定】: 非有限純化が相列にも適用されることを担保
    a = _phase(ref="A", wt_frac=float("nan"))
    traj = Trajectory(records=(_record(frame_index=0, phases=(a,)),),
                      lifecycles={"A": PhaseLifecycle()})
    path = str(tmp_path / "traj.csv")

    # 【実際の処理実行】: to_csv 後に行辞書とファイル全文を取得
    traj.to_csv(path)
    row = _read_dicts(path)[0]
    with open(path, encoding="utf-8") as f:
        text = f.read()

    # 【結果検証】: 相列の非有限が空欄化されること
    # 【期待値確認】: 相列も純化を経由する保証
    assert row["A.wt_frac"] == ""  # 【確認内容】: 非有限 wt_frac は空欄 🟡
    for token in ("inf", "nan", "Infinity", "NaN"):
        assert token not in text  # 【確認内容】: 相列の非有限も漏れない 🟡


def test_none_axis_and_temperature_blank(tmp_path):
    # 【テスト目的】: axis_value/temperature が None のとき空欄になることを確認 (T-E03)
    # 【テスト内容】: index 軸/チャネル欠損フレームの CSV 化を検証
    # 【期待される動作】: 両セルが空文字で例外は発生しない
    # 🔵 信頼性レベル: interfaces.py L143-147 / EDGE-102 に依拠

    # 【テストデータ準備】: axis_value=None, temperature=None のフレーム
    # 【初期条件設定】: None(欠損) と非有限(縮退) を同じ空欄で表現する一貫性
    rec = _record(frame_index=0, axis_value=None, temperature=None, phases=(_phase(),))
    traj = Trajectory(records=(rec,), lifecycles={"A": PhaseLifecycle()})
    path = str(tmp_path / "traj.csv")

    # 【実際の処理実行】: to_csv 後に 1 行目を取得
    traj.to_csv(path)
    row = _read_dicts(path)[0]

    # 【結果検証】: None 値の共通列が空欄であること
    # 【期待値確認】: None を空欄化し読み戻しで欠損として扱える
    assert row["axis_value"] == ""  # 【確認内容】: axis_value=None は空欄 🔵
    assert row["temperature"] == ""  # 【確認内容】: temperature=None は空欄 🔵


def test_phaseless_frame_blank_phase_columns(tmp_path):
    # 【テスト目的】: phases=() のフレームで相列が空欄・例外なしを確認 (T-E04)
    # 【テスト内容】: phases=() と phases=(A,) を混在させ列構造の頑健性を検証
    # 【期待される動作】: 空フレーム行の相 A 列は空欄、A フレーム行は値、共通列は両行埋まる
    # 🟡 信頼性レベル: 要件 §4.3 EC-3 に依拠

    # 【テストデータ準備】: frame0 = phases=(), frame1 = phases=(A,)
    # 【初期条件設定】: 相集合が行ごとに欠けても列構造(和集合)が崩れない
    records = (
        _record(frame_index=0, axis_value=1.0, phases=()),
        _record(frame_index=1, axis_value=2.0, phases=(_phase(),)),
    )
    traj = Trajectory(records=records, lifecycles={"A": PhaseLifecycle()})
    path = str(tmp_path / "traj.csv")

    # 【実際の処理実行】: to_csv 後に全データ行を取得
    traj.to_csv(path)
    rows = _read_dicts(path)

    # 【結果検証】: 空フレーム行の相列は空欄、A フレーム行は値
    # 【期待値確認】: フレーム間の相の出入りに頑健
    assert rows[0]["A.a"] == ""  # 【確認内容】: 相なしフレームの相列は空欄 🟡
    assert rows[0]["frame_index"] == "0"  # 【確認内容】: 共通列は埋まる 🟡
    assert rows[1]["A.a"] == "5.0"  # 【確認内容】: 相ありフレームは値 🟡


# ---------------------------------------------------------------------------
# 3. 境界値テストケース
# ---------------------------------------------------------------------------


def test_empty_trajectory_no_data_rows(tmp_path):
    # 【テスト目的】: 空トラジェクトリ (records=()) でも例外なく CSV を出せること (T-B01)
    # 【テスト内容】: records=(), lifecycles={} の to_csv を検証
    # 【期待される動作】: 例外なし・to_csv 成功・データ行数 0
    # 🟡 信頼性レベル: EDGE-001 / TC-101-05 の CSV 面に依拠

    # 【テストデータ準備】: フレーム 0 件の最小境界
    # 【初期条件設定】: 空シーケンスでもクラッシュしない
    traj = Trajectory(records=(), lifecycles={})
    path = str(tmp_path / "empty.csv")

    # 【実際の処理実行】: to_csv を呼びファイルを読み戻す
    result = traj.to_csv(path)
    dicts = _read_dicts(path)

    # 【結果検証】: 成功しデータ行が 0 であること
    # 【期待値確認】: len(records)==0 → データ行 0
    assert result == path  # 【確認内容】: 空でも書き出しパスを返す 🟡
    assert len(dicts) == 0  # 【確認内容】: データ行数 0 🟡


def test_single_frame_one_data_row(tmp_path):
    # 【テスト目的】: 単一フレーム (records 長 1) でデータ行が 1 行であること (T-B02)
    # 【テスト内容】: 最小の非空シーケンスの行数を検証
    # 【期待される動作】: ヘッダ除くデータ行が 1 行
    # 🟡 信頼性レベル: EDGE-101 / TC-101-06 の CSV 面に依拠

    # 【テストデータ準備】: 相 A を含む単一フレーム
    # 【初期条件設定】: 単数でヘッダ/行の対応が崩れないか
    traj = Trajectory(
        records=(_record(frame_index=0, phases=(_phase(),)),),
        lifecycles={"A": PhaseLifecycle()},
    )
    path = str(tmp_path / "single.csv")

    # 【実際の処理実行】: to_csv 後に全行を読み戻す
    traj.to_csv(path)
    rows = _read_rows(path)

    # 【結果検証】: ヘッダを除くデータ行が 1 行
    # 【期待値確認】: 単数でも 1 フレーム 1 行
    assert len(rows) - 1 == 1  # 【確認内容】: データ行 1 行 🟡


def test_phase_union_sorted_and_absent_blank(tmp_path):
    # 【テスト目的】: フレーム間で相集合が異なるとき列は和集合 sorted・出現前は空欄 (T-B03)
    # 【テスト内容】: frame0=(A,), frame1=(A,B) で B 列が sorted 昇順・出現前空欄か検証
    # 【期待される動作】: 相列は A.* → B.* の昇順、frame0 の B.* は空欄
    # 🔵 信頼性レベル: 要件 §4.3 EC-4 / REQ-402 / TC-104-01 に依拠

    # 【テストデータ準備】: 相 B が途中フレームで出現 (changepoint シナリオ)
    # 【初期条件設定】: 相の到来順に依存せず列順が安定するか
    a = _phase(ref="A")
    b = _phase(ref="B")
    records = (
        _record(frame_index=0, phases=(a,)),
        _record(frame_index=1, phases=(a, b)),
    )
    traj = Trajectory(records=records,
                      lifecycles={"A": PhaseLifecycle(), "B": PhaseLifecycle()})
    path = str(tmp_path / "union.csv")

    # 【実際の処理実行】: to_csv 後にヘッダとデータ行を取得
    traj.to_csv(path)
    header = _read_rows(path)[0]
    rows = _read_dicts(path)

    # 【結果検証】: 相列が A.* → B.* の sorted 昇順で並び出現前は空欄
    # 【期待値確認】: 和集合 sorted で列順が決定論
    a_pos = header.index("A.a")
    b_pos = header.index("B.a")
    assert a_pos < b_pos  # 【確認内容】: 相列が sorted 昇順 (A < B) 🔵
    assert rows[0]["B.a"] == ""  # 【確認内容】: 出現前フレームの B 列は空欄 🔵
    assert rows[1]["B.a"] == "5.0"  # 【確認内容】: 出現後フレームの B 列は値 🔵


def test_lifecycle_only_phase_columns(tmp_path):
    # 【テスト目的】: lifecycles にのみ存在する相の列が出力されることを確認 (T-B04)
    # 【テスト内容】: 全フレーム phases=(A,)、lifecycles={"A","Z"} で Z 列を検証
    # 【期待される動作】: Z の格子/scale/wt_frac は空欄、lifecycle 列に値
    # 🟡 信頼性レベル: 要件 §4.3 EC-5 (phases ∪ lifecycles.keys()) に依拠

    # 【テストデータ準備】: どのフレームの phases にも無いが lifecycles にある相 Z
    # 【初期条件設定】: 列和集合が phases ∪ lifecycles.keys() であることの確認
    traj = Trajectory(
        records=(_record(frame_index=0, phases=(_phase(ref="A"),)),),
        lifecycles={
            "A": PhaseLifecycle(),
            "Z": PhaseLifecycle(birth_frame=3, death_frame=None, confidence=0.5),
        },
    )
    path = str(tmp_path / "lconly.csv")

    # 【実際の処理実行】: to_csv 後にヘッダとデータ行を取得
    traj.to_csv(path)
    header = _read_rows(path)[0]
    row = _read_dicts(path)[0]

    # 【結果検証】: 相 Z 列が存在し格子系列は空・lifecycle 系列に値
    # 【期待値確認】: 格子系列と lifecycle 系列の欠損が独立に扱える
    assert "Z.a" in header  # 【確認内容】: lifecycle のみの相も列を持つ 🟡
    assert row["Z.a"] == ""  # 【確認内容】: 格子系列は全行空欄 🟡
    assert row["Z.wt_frac"] == ""  # 【確認内容】: wt_frac も空欄 🟡
    assert row["Z.birth_frame"] == "3"  # 【確認内容】: lifecycle 列に値 🟡


def test_deterministic_byte_identical(tmp_path):
    # 【テスト目的】: 同一 Trajectory を 2 回出力しバイト完全一致すること (T-B05 / REQ-402)
    # 【テスト内容】: 相 A,B が複数フレームにまたがる出力を 2 パスへ書き比較
    # 【期待される動作】: 2 ファイルのバイト列が完全一致 (列順・数値化・改行が決定論)
    # 🔵 信頼性レベル: REQ-402 / 完了条件④ / NFR-102 に直接依拠

    # 【テストデータ準備】: 相集合が複数フレームにまたがる Trajectory
    # 【初期条件設定】: dict/set 反復順・環境非依存であることを検証
    a = _phase(ref="A")
    b = _phase(ref="B")
    records = (
        _record(frame_index=0, axis_value=1.0, phases=(a,), rwp=1.1),
        _record(frame_index=1, axis_value=2.0, phases=(a, b), rwp=1.2),
        _record(frame_index=2, axis_value=3.0, phases=(b,), rwp=1.3),
    )
    traj = Trajectory(records=records,
                      lifecycles={"A": PhaseLifecycle(0, 2, 1.0),
                                  "B": PhaseLifecycle(1, None, 0.9)})
    p1 = str(tmp_path / "det1.csv")
    p2 = str(tmp_path / "det2.csv")

    # 【実際の処理実行】: 同一 Trajectory を 2 つのパスへ出力
    traj.to_csv(p1)
    traj.to_csv(p2)

    # 【結果検証】: 2 ファイルのバイト列が完全一致すること
    # 【期待値確認】: newline/utf-8 固定で改行・エンコーディング差を排除
    with open(p1, "rb") as f1, open(p2, "rb") as f2:
        assert f1.read() == f2.read()  # 【確認内容】: バイト完全一致 (決定論) 🔵


def test_frozen_immutability():
    # 【テスト目的】: FrameRecord / Trajectory が frozen で代入不可であること (T-B06)
    # 【テスト内容】: 生成済みインスタンスのフィールド代入が失敗するか検証
    # 【期待される動作】: 代入時に FrozenInstanceError が送出される
    # 🔵 信頼性レベル: CLAUDE.md frozen 規約 / interfaces.py frozen に依拠

    # 【テストデータ準備】: FrameRecord / Trajectory を 1 件ずつ生成
    # 【初期条件設定】: 値オブジェクトとして生成後は不変
    rec = _record(frame_index=0, phases=(_phase(),), rwp=2.0)
    traj = Trajectory(records=(rec,), lifecycles={"A": PhaseLifecycle()})

    # 【実際の処理実行】/【結果検証】: フィールド代入が FrozenInstanceError になること
    # 【期待値確認】: @dataclass(frozen=True) が両クラスに付与されている
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.rwp = 1.0  # 【確認内容】: FrameRecord が不変 🔵
    with pytest.raises(dataclasses.FrozenInstanceError):
        traj.records = ()  # 【確認内容】: Trajectory が不変 🔵


def test_finite_endpoints_preserved(tmp_path):
    # 【テスト目的】: 有限端点 (0.0/負値/極小) が空欄化されず保持されること (T-B07)
    # 【テスト内容】: rwp=0.0, axis_value=-273.15, wt_frac=1e-12 の保持を検証
    # 【期待される動作】: 空欄化は None/inf/NaN 限定で 0 や負を巻き込まない
    # 🔵 信頼性レベル: 要件 §3 非有限制約 / serialization.py 有限端点保持に依拠

    # 【テストデータ準備】: 有限だが極端な端点値を与える
    # 【初期条件設定】: falsy な 0.0 を欠損扱いしない (is None / isfinite 判定)
    a = _phase(ref="A", wt_frac=1e-12)
    rec = _record(frame_index=0, axis_value=-273.15, phases=(a,), rwp=0.0)
    traj = Trajectory(records=(rec,), lifecycles={"A": PhaseLifecycle()})
    path = str(tmp_path / "endpoints.csv")

    # 【実際の処理実行】: to_csv 後に 1 行目を取得
    traj.to_csv(path)
    row = _read_dicts(path)[0]

    # 【結果検証】: 有限端点が空欄化されず保持されること
    # 【期待値確認】: 空欄化は非有限限定で 0/負/極小を巻き込まない
    assert row["rwp"] == "0.0"  # 【確認内容】: 0.0 は保持 🔵
    assert row["axis_value"] == "-273.15"  # 【確認内容】: 負値は保持 🔵
    assert row["A.wt_frac"] != ""  # 【確認内容】: 極小値は空欄でない 🔵
    assert float(row["A.wt_frac"]) == pytest.approx(1e-12)  # 【確認内容】: 1e-12 相当 🔵
