"""TASK-0034 operando/hysteresis + 結合出力 (FR-315 / FR-314) の失敗テスト (TDD Red)。

対象実装 (**未実装**):
- ``src/tsumugin/operando/output.py``:
  - ``combined_csv(trajectory, echem, path) -> str`` — ``Trajectory`` 列 + ``EchemData`` の
    echem 列 (voltage/current/capacity/composition_x = V/I/Q/x) を frame_index で外部結合し
    stdlib ``csv`` で決定論書き出し。非有限 (inf/NaN)/None は空欄化。書き出しパスを返す。
  - ``TransitionPoint(frame_index, x, voltage, sigma_x, sigma_v)`` (frozen dataclass)。
  - ``transition_point(echem, frame_index) -> TransitionPoint`` — 境界フレーム index から x/V±σ を導出する純関数。
- ``src/tsumugin/operando/hysteresis.py``:
  - ``BranchComparison(x, charge_value, discharge_value, difference)`` (frozen dataclass)。
  - ``split_branches(x_values) -> (charge_idx, discharge_idx)`` — dx 符号で充電枝/放電枝を分離。
  - ``branch_differences(x_values, values, *, n_grid=20) -> tuple[BranchComparison, ...]`` — 共通 x
    グリッド上の枝間差分。片枝欠損は None + UserWarning。

このファイルで凍結する契約 (要件定義書 / testcases / interfaces.py L324-363 / D9 / D-Q10 に依拠):
- **echem 列名**: EchemData のフィールド名をそのまま列名にする ("voltage"/"current"/"capacity"/
  "composition_x")。空 tuple の echem 列は CSV に列自体を追加しない (echem.to_channels の空縮退と同流儀)。
- **外部結合**: 行集合 = trajectory ∪ echem の frame_index 和集合。片側欠損・None・非有限セルは空欄。
- **転移点 (D-Q10 / 認可式)**: 境界フレーム b は隣接 2 フレーム (b-1, b) を用いる。
  x = (x[b-1]+x[b])/2、voltage = (v[b-1]+v[b])/2、sigma_x = abs(x[b]-x[b-1])、sigma_v = abs(v[b]-v[b-1])。
  b<=0 (前フレームなし) / b>=n (b フレームなし) / 隣接 echem 欠損 (None) / 非有限は該当フィールド None。
  frame_index は常に保持。(N2 が 🔵 AC TC-205-02 で midpoint=(x[b-1]+x[b])/2 を凍結するため (b-1,b) を採る。)
- **枝分離 (REQ-104)**: dx = x[i]-x[i-1] の符号で分離。dx>0 → charge_idx (第 1 要素)、dx<0 → discharge_idx
  (第 2 要素)。dx==0 / 先頭フレーム (dx 未定義) / None フレームは両枝から除外。昇順・重複なし。
- **枝間差分 (EDGE-007)**: 共通 x グリッドは両枝の finite な x の**全域** (min..max) を n_grid 分割。
  各グリッド x で charge/discharge を線形補間し difference = charge_value - discharge_value。
  片枝しか値を持たない x は該当 value と difference を None にし UserWarning を 1 回出す。

対象モジュール未実装のため collection 時に import が失敗し、本ファイルの全テストがエラー(=失敗)になる想定 (Red)。
書式は tests/test_trajectory.py / tests/test_discrimination.py に準拠。
"""

from __future__ import annotations

import csv
import dataclasses
import warnings

import pytest

from tsumugin.model import LatticeParams, PhaseInstance, PhaseLifecycle
from tsumugin.operando import EchemData

# 未実装のため、この 2 つの import が collection 時に失敗し全テストがエラー(=失敗)になる想定 (Red)。
from tsumugin.operando.hysteresis import (
    BranchComparison,
    branch_differences,
    split_branches,
)
from tsumugin.operando.output import (
    TransitionPoint,
    combined_csv,
    transition_point,
)
from tsumugin.sequential import FrameRecord, Trajectory

# ---------------------------------------------------------------------------
# 共通ヘルパ (Given の土台)。tests/test_trajectory.py の _phase/_record を踏襲。
# ---------------------------------------------------------------------------


def _phase(ref="A", a=5.0, b=6.0, c=7.0, scale=1.0, wt_frac=0.5):
    """相 PhaseInstance を組む簡易ヘルパ (格子/scale/wt_frac 既知)。"""
    return PhaseInstance(
        phase_ref=ref,
        lattice=LatticeParams(a=a, b=b, c=c),
        scale=scale,
        wt_frac=wt_frac,
    )


def _record(frame_index=0, phases=None, **kw):
    """FrameRecord を既定値付きで組む簡易ヘルパ。phases 未指定なら相 A 1 個。"""
    if phases is None:
        phases = (_phase(),)
    return FrameRecord(frame_index=frame_index, phases=phases, **kw)


def _trajectory(n=3):
    """相 A を各フレームに持つ n フレームの Trajectory を組む。"""
    records = tuple(_record(frame_index=i) for i in range(n))
    return Trajectory(records=records, lifecycles={"A": PhaseLifecycle()})


def _echem(voltage=(3.0, 3.5, 4.0), composition_x=(0.0, 0.3, 0.6), current=(), capacity=()):
    """EchemData を組む簡易ヘルパ (位置 index = frame_index)。"""
    return EchemData(
        voltage=voltage,
        current=current,
        capacity=capacity,
        composition_x=composition_x,
    )


def _roundtrip():
    """充放電往復 (非単調 x) と枝でずらした values を返す (N4/N7 共用)。

    x: 0→0.8 上昇 (frame 1-3) 後 0.8→0 下降 (frame 4-6)。
    values: charge 枝 = 10.0 + x、discharge 枝 = 10.1 + x (差分 = -0.1 一定)。
    """
    x_values = [0.0, 0.2, 0.5, 0.8, 0.5, 0.2, 0.0]
    values = [10.0, 10.2, 10.5, 10.8, 10.6, 10.3, 10.1]
    return x_values, values


def _read_dicts(path):
    """csv.DictReader でデータ行を辞書列として読み戻す。"""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_header(path):
    """csv.reader でヘッダ行 (列名) を読み戻す。"""
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


# ---------------------------------------------------------------------------
# 1. 正常系テストケース
# ---------------------------------------------------------------------------


def test_combined_csv_contains_vx_and_wtfrac_lattice_readback(tmp_path):
    # 【テスト目的】: combined_csv が V/x 列 + wt_frac(x)/格子(x) を同一行に結合し読み戻せることを確認 (N1)
    # 【テスト内容】: Trajectory + EchemData を frame_index 外部結合で CSV 化し DictReader で読み戻す
    # 【期待される動作】: 各行に echem 列 (voltage/composition_x) と相列 (A.wt_frac/A.a) が並び値が一致
    # 🔵 信頼性レベル: acceptance-criteria TC-205-01 / architecture.md D9 / interfaces.py L349-350

    # 【テストデータ準備】: 相列既知の Trajectory と V/x 既知の EchemData (REQ-011 の代表入力)
    # 【初期条件設定】: backend 不要・純データ・出力先は tmp_path
    trajectory = _trajectory(3)
    echem = _echem(voltage=(3.0, 3.5, 4.0), composition_x=(0.0, 0.3, 0.6))
    path = str(tmp_path / "c.csv")

    # 【実際の処理実行】: combined_csv を呼び出す (frame_index 外部結合で trajectory 列 + echem 列)
    out = combined_csv(trajectory, echem, path)

    # 【結果検証】: 戻り値 == path、読み戻して V/x 列と wt_frac/格子 列を検証
    # 【期待値確認】: echem 列の値一致・相列の値一致・行数一致
    assert out == path  # 【確認内容】: 書き出しパスを返す 🔵
    rows = _read_dicts(path)
    assert len(rows) == 3  # 【確認内容】: 行数 = フレーム数 🔵
    assert rows[1]["voltage"] == "3.5"  # 【確認内容】: V 列が入る 🔵
    assert rows[1]["composition_x"] == "0.3"  # 【確認内容】: x 列が入る 🔵
    assert rows[1]["A.wt_frac"] == "0.5"  # 【確認内容】: 相の wt_frac(x) が同一行に並ぶ 🔵
    assert rows[1]["A.a"] == "5.0"  # 【確認内容】: 相の格子(x) が同一行に並ぶ 🔵


def test_transition_point_interpolates_xv_and_sigma_from_boundary():
    # 【テスト目的】: 境界フレーム b から x/V を隣接補間・σ を隣接差として算出することを確認 (N2)
    # 【テスト内容】: transition_point(echem, 2) の x/voltage/sigma_x/sigma_v を検証
    # 【期待される動作】: x=(x[1]+x[2])/2、v=(v[1]+v[2])/2、σ=abs(隣接差)
    # 🔵 信頼性レベル: acceptance-criteria TC-205-02 / design-interview D-Q10 / thermal.py L207-226

    # 【テストデータ準備】: 単調な composition_x/voltage 列と既知境界 b=2 (D-Q10 の代表)
    # 【初期条件設定】: (b-1, b) = (frame1, frame2) の線形補間を凍結
    echem = _echem(composition_x=(0.0, 0.2, 0.4, 0.6), voltage=(3.0, 3.3, 3.6, 3.9))

    # 【実際の処理実行】: 境界フレーム b=2 から転移点を導出
    tp = transition_point(echem, 2)

    # 【結果検証】: x/V の中点補間・σ の隣接差・frame_index 保持を検証
    # 【期待値確認】: (b-1,b)=(1,2) の中点と隣接差 (D-Q10)
    assert tp.frame_index == 2  # 【確認内容】: 境界 index を保持 🔵
    assert tp.x == pytest.approx((0.2 + 0.4) / 2)  # 【確認内容】: x = 中点補間 🔵
    assert tp.voltage == pytest.approx((3.3 + 3.6) / 2)  # 【確認内容】: V = 中点補間 🔵
    assert tp.sigma_x == pytest.approx(abs(0.4 - 0.2))  # 【確認内容】: σ_x = 隣接差 🔵
    assert tp.sigma_v == pytest.approx(abs(3.6 - 3.3))  # 【確認内容】: σ_v = 隣接差 🔵


def test_split_branches_separates_charge_discharge_on_nonmonotonic_x():
    # 【テスト目的】: 非単調 x の往復データで充電枝/放電枝が dx 符号で自動分離されることを確認 (N3)
    # 【テスト内容】: 0→0.8 上昇後 0.8→0 下降の x 列を split_branches に渡す
    # 【期待される動作】: dx>0 のフレーム群 (charge) と dx<0 のフレーム群 (discharge) を別 tuple で返す
    # 🟡 信頼性レベル: acceptance-criteria TC-205-03 / interfaces.py L339-341 / REQ-104

    # 【テストデータ準備】: 0→0.8 上昇 (frame1-3) 後 0.8→0 下降 (frame4-6) の非単調 x
    # 【初期条件設定】: 先頭 frame0 は dx 未定義、折返し frame3 は dx>0 側 (規約)
    x_values = [0.0, 0.2, 0.5, 0.8, 0.5, 0.2, 0.0]

    # 【実際の処理実行】: dx 符号で枝分離
    charge, discharge = split_branches(x_values)

    # 【結果検証】: 上昇区間 index 群と下降区間 index 群が分離され昇順・重複なし
    # 【期待値確認】: dx>0 → charge=(1,2,3)、dx<0 → discharge=(4,5,6)、frame0 は除外
    assert charge == (1, 2, 3)  # 【確認内容】: dx>0 の充電枝 (折返し frame3 含む) 🟡
    assert discharge == (4, 5, 6)  # 【確認内容】: dx<0 の放電枝 🟡
    assert list(charge) == sorted(set(charge))  # 【確認内容】: 昇順・重複なし 🟡
    assert set(charge).isdisjoint(discharge)  # 【確認内容】: 両枝は排他 🟡


def test_branch_differences_computes_same_x_charge_discharge_diff():
    # 【テスト目的】: 同一 x での枝間差分 (格子/分率) が共通 x グリッド上で算出されることを確認 (N4)
    # 【テスト内容】: 往復 x + 枝でずらした values を branch_differences に渡す
    # 【期待される動作】: 各グリッド x で charge/discharge を補間し difference = charge - discharge
    # 🟡 信頼性レベル: acceptance-criteria TC-205-04 前半 / interfaces.py L329-346 / REQ-012

    # 【テストデータ準備】: charge=10.0+x, discharge=10.1+x (差分 -0.1 一定) の往復データ
    # 【初期条件設定】: n_grid=5、重なり域で difference が有限になる
    x_values, values = _roundtrip()

    # 【実際の処理実行】: 共通 x グリッド上の枝間差分を算出 (片枝域の警告は本ケースの検証対象外)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = branch_differences(x_values, values, n_grid=5)

    # 【結果検証】: BranchComparison 列で difference = charge - discharge、x は昇順グリッド
    # 【期待値確認】: 重なり域では difference が有限で -0.1、両枝値を持つ点で式が一致
    assert isinstance(result, tuple)  # 【確認内容】: 戻り値は tuple 🟡
    assert all(isinstance(c, BranchComparison) for c in result)  # 【確認内容】: 要素は BranchComparison 🟡
    xs = [c.x for c in result]
    assert xs == sorted(xs)  # 【確認内容】: 共通 x グリッドは昇順 🟡
    both = [c for c in result if c.charge_value is not None and c.discharge_value is not None]
    assert both  # 【確認内容】: 重なり域の比較点が少なくとも 1 つ存在 🟡
    for c in both:
        assert c.difference == pytest.approx(c.charge_value - c.discharge_value)
        # 【確認内容】: difference = charge_value - discharge_value 🟡
        assert c.difference == pytest.approx(-0.1)  # 【確認内容】: 枝オフセット -0.1 が復元される 🟡


def test_combined_csv_outer_join_blank_for_missing_frames(tmp_path):
    # 【テスト目的】: フレーム数不一致で外部結合し欠損側を空欄化することを確認 (N5)
    # 【テスト内容】: trajectory 4 フレーム + echem voltage 2 フレームのみ
    # 【期待される動作】: 行集合 = frame_index 和集合、echem 未提供フレームの列は空欄
    # 🟡 信頼性レベル: architecture.md D9 / dataflow.md L124 / note.md §6-1

    # 【テストデータ準備】: trajectory frame 0..3、echem voltage は frame 0,1 のみ (2,3 は欠損)
    # 【初期条件設定】: 部分同期 (行数不一致) の代表 (echem.py の None 縮退と整合)
    trajectory = _trajectory(4)
    echem = _echem(voltage=(3.0, 3.5), composition_x=(0.0, 0.3))
    path = str(tmp_path / "join.csv")

    # 【実際の処理実行】: combined_csv で外部結合
    combined_csv(trajectory, echem, path)
    rows = _read_dicts(path)

    # 【結果検証】: 行数 = 全フレーム和集合、echem 欠損フレームの voltage が空欄、非欠損は保持
    # 【期待値確認】: 外部結合 + 欠損空欄 (捏造しない)
    assert len(rows) == 4  # 【確認内容】: 行数 = frame_index 和集合 🟡
    assert rows[0]["voltage"] == "3.0"  # 【確認内容】: echem のあるフレームは値保持 🟡
    assert rows[2]["voltage"] == ""  # 【確認内容】: echem 欠損フレームは空欄 🟡
    assert rows[3]["voltage"] == ""  # 【確認内容】: echem 欠損フレームは空欄 🟡
    assert rows[2]["A.a"] == "5.0"  # 【確認内容】: trajectory 側は通常値 🟡


def test_combined_csv_deterministic_byte_identical(tmp_path):
    # 【テスト目的】: 同一入力で combined_csv を 2 回実行しバイト完全一致することを確認 (N6)
    # 【テスト内容】: 同一 trajectory/echem を別パスへ 2 回出力し bytes 比較
    # 【期待される動作】: 乱数/時刻/集合反復順に依存せず newline=""/utf-8 固定でバイト同一
    # 🔵 信頼性レベル: CLAUDE.md NFR-102 / trajectory.py L107-108

    # 【テストデータ準備】: 同一 trajectory + echem を用意
    # 【初期条件設定】: 決定論出力 (相 ref sorted・列順固定・改行/エンコーディング固定) の検証
    trajectory = _trajectory(3)
    echem = _echem()
    p1 = str(tmp_path / "det1.csv")
    p2 = str(tmp_path / "det2.csv")

    # 【実際の処理実行】: 同一入力を 2 パスへ出力
    combined_csv(trajectory, echem, p1)
    combined_csv(trajectory, echem, p2)

    # 【結果検証】: 2 ファイルのバイト列が完全一致
    # 【期待値確認】: NFR-102 再現性 (trajectory.to_csv と同一保証)
    with open(p1, "rb") as f1, open(p2, "rb") as f2:
        assert f1.read() == f2.read()  # 【確認内容】: バイト完全一致 (決定論) 🔵


def test_hysteresis_and_transition_deterministic_bit_identical():
    # 【テスト目的】: split_branches/branch_differences/transition_point がビット同一であることを確認 (N7)
    # 【テスト内容】: 同一入力で各純関数を 2 回呼び結果を == 比較
    # 【期待される動作】: dataclass の ==・tuple 一致で再現性を担保
    # 🔵 信頼性レベル: CLAUDE.md NFR-102 / note.md §6-3/6-6

    # 【テストデータ準備】: 同一 x_values/values/echem/frame_index を 2 回呼ぶ
    # 【初期条件設定】: 枝分離 tie-break・補間の決定論性を検証
    x_values, values = _roundtrip()
    echem = _echem(composition_x=(0.0, 0.2, 0.4, 0.6), voltage=(3.0, 3.3, 3.6, 3.9))

    # 【実際の処理実行】: 各純関数を 2 回呼ぶ (片枝域の警告は決定論検証の対象外)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        split1 = split_branches(x_values)
        split2 = split_branches(x_values)
        diff1 = branch_differences(x_values, values, n_grid=5)
        diff2 = branch_differences(x_values, values, n_grid=5)
    tp1 = transition_point(echem, 2)
    tp2 = transition_point(echem, 2)

    # 【結果検証】: 全結果がビット同一 (==)
    # 【期待値確認】: 安定 tie-break + 決定論補間
    assert split1 == split2  # 【確認内容】: 枝分離が再現的 🔵
    assert diff1 == diff2  # 【確認内容】: 枝間差分が再現的 🔵
    assert tp1 == tp2  # 【確認内容】: 転移点が再現的 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース
# ---------------------------------------------------------------------------


def test_branch_differences_single_branch_yields_none_and_warns():
    # 【テスト目的】: 片枝のみのデータで枝間差分が None + UserWarning になることを確認 (E1)
    # 【テスト内容】: 単調増加のみ (放電枝が空) の x_values を branch_differences に渡す
    # 【期待される動作】: 例外を投げず、片枝しかない x の discharge/difference が None、UserWarning が出る
    # 🟡 信頼性レベル: acceptance-criteria TC-205-04 後半 / EDGE-007 / echem.py L137-143

    # 【テストデータ準備】: 単調増加 x (放電枝なし) + values (片方向スキャンの代表)
    # 【初期条件設定】: 往復がなく枝間差分が定義できない x 域が生じる
    x_values = [0.0, 0.2, 0.4, 0.6, 0.8]
    values = [10.0, 10.2, 10.4, 10.6, 10.8]

    # 【実際の処理実行】: 片枝欠損で UserWarning を捕捉しつつ差分を算出
    # 【処理内容】: 例外化せず None 縮退 + 警告 (縮退継続)
    with pytest.warns(UserWarning):
        result = branch_differences(x_values, values, n_grid=5)

    # 【結果検証】: 片枝しかない x の discharge_value/difference が None、処理はブロックしない
    # 【期待値確認】: 欠損を捏造せず None + 警告で通知 (CLAUDE.md 不変条件)
    assert isinstance(result, tuple)  # 【確認内容】: 例外を投げず結果を返す 🟡
    none_side = [c for c in result if c.discharge_value is None]
    assert none_side  # 【確認内容】: 放電枝欠損の比較点が存在する 🟡
    for c in none_side:
        assert c.difference is None  # 【確認内容】: 片枝欠損 x の difference は None (捏造しない) 🟡


def test_combined_csv_never_leaks_nonfinite_values(tmp_path):
    # 【テスト目的】: 非有限 (inf/NaN)/None が CSV セルに漏れないことを確認 (E2)
    # 【テスト内容】: chi2=inf/rwp=None/格子 a=nan の Trajectory + None を含む echem を CSV 化
    # 【期待される動作】: 該当セルは空文字、inf/nan/None 文字列がファイルに現れない
    # 🔵 信頼性レベル: 完了条件5 / M1/M2 教訓 / trajectory.py L183-197 / CLAUDE.md 不変条件

    # 【テストデータ準備】: 精密化失敗フレーム (chi2=inf, a=nan) と echem 欠損 (None) を混在
    # 【初期条件設定】: 非有限を空欄化し下流へ漏らさない純化を全出口で守る
    bad = _record(
        frame_index=0,
        phases=(_phase(a=float("nan")),),
        rwp=None,
        chi2=float("inf"),
        refine_failed=True,
    )
    good = _record(frame_index=1, rwp=1.0, chi2=1.0)
    trajectory = Trajectory(records=(bad, good), lifecycles={"A": PhaseLifecycle()})
    echem = _echem(voltage=(3.0, None), composition_x=(0.0, 0.3))
    path = str(tmp_path / "nonfinite.csv")

    # 【実際の処理実行】: combined_csv 後に行辞書とファイル全文を取得
    combined_csv(trajectory, echem, path)
    rows = _read_dicts(path)
    with open(path, encoding="utf-8") as f:
        text = f.read()

    # 【結果検証】: 非有限/None セルは空欄・非有限文字列が全文に無い
    # 【期待値確認】: 完了条件5 の直接検証
    assert rows[0]["chi2"] == ""  # 【確認内容】: inf は空欄 🔵
    assert rows[0]["A.a"] == ""  # 【確認内容】: 格子 nan は空欄 🔵
    assert rows[1]["voltage"] == ""  # 【確認内容】: echem None は空欄 🔵
    for token in ("inf", "nan", "Infinity", "NaN"):
        assert token not in text  # 【確認内容】: 非有限文字列がファイルに漏れない 🔵


def test_transition_and_comparison_degrade_nonfinite_to_none():
    # 【テスト目的】: 転移点の float フィールドに非有限を格納せず None へ縮退することを確認 (E3)
    # 【テスト内容】: 境界に None が隣接する echem で transition_point を算出
    # 【期待される動作】: 補間/差分が定義できないフィールドは None、例外なし
    # 🟡 信頼性レベル: note.md §6-2/6-5 / thermal.py (欠損→None 先例)

    # 【テストデータ準備】: 境界 b=1 に None が隣接する部分同期 echem
    # 【初期条件設定】: 欠損隣接で補間/差分が定義できないケース
    echem = _echem(composition_x=(0.0, None, 0.4), voltage=(3.0, None, 3.6))

    # 【実際の処理実行】: 欠損隣接の境界フレームから転移点を導出
    tp = transition_point(echem, 1)

    # 【結果検証】: 該当フィールドが None (inf/NaN を格納しない)、frame_index は保持
    # 【期待値確認】: None 縮退で下流の等価比較・出力を保護
    assert tp.frame_index == 1  # 【確認内容】: 境界 index を保持 🟡
    assert tp.x is None  # 【確認内容】: 欠損隣接の x は None 🟡
    assert tp.voltage is None  # 【確認内容】: 欠損隣接の voltage は None 🟡
    assert tp.sigma_x is None  # 【確認内容】: 欠損隣接の σ_x は None 🟡
    assert tp.sigma_v is None  # 【確認内容】: 欠損隣接の σ_v は None 🟡


# ---------------------------------------------------------------------------
# 3. 境界値テストケース
# ---------------------------------------------------------------------------


def test_transition_point_at_series_ends_returns_none_fields():
    # 【テスト目的】: 境界端フレームで隣接不能なら該当フィールドが None になることを確認 (B1)
    # 【テスト内容】: 4 フレーム echem で b=0 (前フレームなし) と b=4 (b フレームなし) を検証
    # 【期待される動作】: 隣接不能側に依存する x/voltage/sigma が None、例外なし、frame_index 保持
    # 🟡 信頼性レベル: design-interview D-Q10 / note.md §6-2
    #   (N2 が (b-1,b) 補間を凍結するため、隣接不能端 = b<=0 / b>=n を None とする凍結規約)

    # 【テストデータ準備】: 4 フレーム echem、両端 b=0 と b=n(=4) の 2 パターン
    # 【初期条件設定】: 端で捏造せず None 縮退する規約の検証
    echem = _echem(composition_x=(0.0, 0.2, 0.4, 0.6), voltage=(3.0, 3.3, 3.6, 3.9))

    # 【実際の処理実行】: 前隣接なし (b=0) と後隣接なし (b=4=len) を導出
    low = transition_point(echem, 0)
    high = transition_point(echem, 4)

    # 【結果検証】: 隣接不能端の x/voltage/sigma が None、frame_index は保持
    # 【期待値確認】: D-Q10 縮退 (端で補間/σ 不能)
    assert low.frame_index == 0  # 【確認内容】: 下端 index を保持 🟡
    assert low.x is None and low.voltage is None  # 【確認内容】: 前フレームなしで x/V が None 🟡
    assert low.sigma_x is None and low.sigma_v is None  # 【確認内容】: 前フレームなしで σ が None 🟡
    assert high.frame_index == 4  # 【確認内容】: 上端 index を保持 🟡
    assert high.x is None and high.voltage is None  # 【確認内容】: b フレームなしで x/V が None 🟡
    assert high.sigma_x is None and high.sigma_v is None  # 【確認内容】: b フレームなしで σ が None 🟡


def test_combined_csv_blank_for_none_echem_cells(tmp_path):
    # 【テスト目的】: echem 列の None (欠損フレーム) が該当セル空欄になることを確認 (B2)
    # 【テスト内容】: voltage/composition_x に None を混ぜた部分同期 echem を CSV 化
    # 【期待される動作】: None の echem セルは空文字、非 None セルは値保持、行数=フレーム数
    # 🟡 信頼性レベル: echem.py L122-124 (None 縮退) / dataflow.md L124

    # 【テストデータ準備】: voltage=(3.0,None,4.0), composition_x=(0.0,0.3,None) の 3 フレーム
    # 【初期条件設定】: echem.py の None 縮退政策 (欠損は捏造しない) との整合検証
    trajectory = _trajectory(3)
    echem = _echem(voltage=(3.0, None, 4.0), composition_x=(0.0, 0.3, None))
    path = str(tmp_path / "none_cells.csv")

    # 【実際の処理実行】: combined_csv で部分同期 echem を結合
    combined_csv(trajectory, echem, path)
    rows = _read_dicts(path)

    # 【結果検証】: None の echem セルは空欄、非 None は値保持、行数=フレーム数
    # 【期待値確認】: 欠損セルのみ空欄で他に波及しない
    assert len(rows) == 3  # 【確認内容】: 行数 = フレーム数 🟡
    assert rows[1]["voltage"] == ""  # 【確認内容】: voltage None は空欄 🟡
    assert rows[2]["composition_x"] == ""  # 【確認内容】: composition_x None は空欄 🟡
    assert rows[0]["voltage"] == "3.0"  # 【確認内容】: 非 None セルは値保持 🟡
    assert rows[2]["voltage"] == "4.0"  # 【確認内容】: 非 None セルは値保持 🟡


def test_combined_csv_handles_absent_echem_columns(tmp_path):
    # 【テスト目的】: echem 未提供列 (空 tuple) の列を CSV に追加しないことを確認 (B3)
    # 【テスト内容】: voltage のみの EchemData を CSV 化しヘッダを検証
    # 【期待される動作】: 空 tuple の current/capacity/composition_x は列を追加しない、voltage は正常出力
    # 🟡 信頼性レベル: echem.py L62-64 (空縮退) / note.md §6-1

    # 【テストデータ準備】: voltage-only の最小 EchemData (current/capacity/composition_x は既定 ())
    # 【初期条件設定】: 未提供列で列数が破綻しないことの検証
    trajectory = _trajectory(3)
    echem = EchemData(voltage=(3.0, 3.5, 4.0))
    path = str(tmp_path / "absent.csv")

    # 【実際の処理実行】: combined_csv 後にヘッダとデータ行を取得
    combined_csv(trajectory, echem, path)
    header = _read_header(path)
    rows = _read_dicts(path)

    # 【結果検証】: voltage 列のみ追加、空 tuple 列はヘッダに現れない
    # 【期待値確認】: 空縮退 (echem.to_channels と同流儀)
    assert "voltage" in header  # 【確認内容】: voltage 列は追加される 🟡
    assert "current" not in header  # 【確認内容】: 空 tuple の列は追加しない 🟡
    assert "capacity" not in header  # 【確認内容】: 空 tuple の列は追加しない 🟡
    assert "composition_x" not in header  # 【確認内容】: 空 tuple の列は追加しない 🟡
    assert rows[1]["voltage"] == "3.5"  # 【確認内容】: voltage 列は正常出力 🟡


def test_branch_comparison_and_transition_point_are_frozen():
    # 【テスト目的】: BranchComparison / TransitionPoint が frozen で代入不可であることを確認 (B4)
    # 【テスト内容】: 生成済みインスタンスへの属性代入が FrozenInstanceError になるか検証
    # 【期待される動作】: 代入時に FrozenInstanceError が送出される
    # 🔵 信頼性レベル: interfaces.py L329/L354 (@dataclass(frozen=True)) / CLAUDE.md コーディング規約

    # 【テストデータ準備】: BranchComparison / TransitionPoint を 1 件ずつ生成
    # 【初期条件設定】: 不変データ (P2 / コーディング規約) の境界検証
    bc = BranchComparison(x=0.3, charge_value=10.2, discharge_value=10.3, difference=-0.1)
    tp = TransitionPoint(frame_index=2, x=0.3, voltage=3.45, sigma_x=0.2, sigma_v=0.3)

    # 【実際の処理実行】/【結果検証】: フィールド代入が FrozenInstanceError になること
    # 【期待値確認】: @dataclass(frozen=True) が両クラスに付与されている
    with pytest.raises(dataclasses.FrozenInstanceError):
        bc.difference = 0.0  # 【確認内容】: BranchComparison が不変 🔵
    with pytest.raises(dataclasses.FrozenInstanceError):
        tp.x = 0.0  # 【確認内容】: TransitionPoint が不変 🔵


def test_split_branches_empty_single_and_flat_deterministic():
    # 【テスト目的】: 空/単一/全平坦 (dx==0) の x_values で枝分離が決定論規約に従うことを確認 (B5)
    # 【テスト内容】: (a) []、(b) [0.5]、(c) [0.5,0.5,0.5] を split_branches に渡す
    # 【期待される動作】: 例外なし、dx 未定義 (空/単一)・dx==0 (平坦) は両枝から除外、2 回実行で同一
    # 🟡 信頼性レベル: note.md §6-3 (dx==0/None/折返し帰属) / interfaces.py L339-341

    # 【テストデータ準備】: 分離不能/縮退の 3 パターン (dx 未定義と dx==0)
    # 【初期条件設定】: 最小入力でも Result 契約 (tuple ペア) を満たし決定論
    empty = split_branches([])
    single = split_branches([0.5])
    flat = split_branches([0.5, 0.5, 0.5])

    # 【結果検証】: 空/単一/全平坦は両枝とも空 tuple、かつ 2 回実行で同一
    # 【期待値確認】: dx 未定義/dx==0 は両枝除外の凍結規約 + tie-break 安定性
    assert empty == ((), ())  # 【確認内容】: 空入力は両枝空 🟡
    assert single == ((), ())  # 【確認内容】: 単一フレームは dx 未定義で両枝空 🟡
    assert flat == ((), ())  # 【確認内容】: 全平坦 (dx==0) は両枝除外 🟡
    assert split_branches([0.5, 0.5, 0.5]) == flat  # 【確認内容】: 2 回実行でビット同一 (決定論) 🟡
