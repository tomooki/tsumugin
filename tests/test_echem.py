"""TASK-0029 operando/echem — CSV マッパ + Loader Protocol の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/operando/echem.py``:
  - ``EchemData`` (frozen dataclass): voltage/current/capacity/composition_x の 4 tuple
    フィールド (要素は ``float | None``)。``to_channels()`` で非空フィールドを対応 kind
    (voltage/current/capacity/composition) の ``ExternalChannel`` 群へ変換。None フレームは
    sync_map に含めない (欠損=不同期・捏造しない / dataflow.md L124)。
  - ``read_echem_csv(path, *, column_map, capacity_to_x=None) -> EchemData``: stdlib ``csv`` で
    読み ``column_map`` で列抽出。数値は ``float()`` で明示変換 (**eval 不使用**)。
    ``capacity_to_x=(a, b)`` 指定時 ``x = a·Q + b`` を全フレームに適用。
  - ``EchemLoader`` (Protocol) / ``BiologicMprLoader`` (M3 では ``NotImplementedError`` スタブ)。

欠損政策 (D-Q7 / EDGE-003, 非対称を厳守):
- 列欠損 = 列名を示す ``ValueError`` (処理継続不能)。
- 行数不一致 (空セル) = 短い方に合わせ ``None`` + ``warnings.warn(UserWarning)`` (縮退継続)。

対象モジュール ``tsumugin.operando.echem`` 未実装のため、import が collection 時に失敗し
本ファイル全テストがエラー (=失敗) になる (Red)。書式は tests/test_trajectory.py /
tests/test_model_m3.py に準拠。テスト ID (TC-Nxx/Axx/BVxx) と AC (TC-202-01〜04) を各所に明記。
"""

from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path

import pytest

from tsumugin.model import ExternalChannel

# 未実装モジュール: この import が collection 時に失敗し全テストが Red になる。
import tsumugin.operando.echem as echem_module
from tsumugin.operando.echem import (
    BiologicMprLoader,
    EchemData,
    EchemLoader,
    read_echem_csv,
)

# ---------------------------------------------------------------------------
# 共通テストデータ (テストケース定義 §0 の代表 CSV)
# ---------------------------------------------------------------------------

# ヘッダに特殊列名 (Ewe/V 等) を含む代表的な充放電 3 フレーム CSV。
COMMON_CSV = (
    "index,Ewe/V,I/mA,Q/mAh\n"
    "0,3.20,0.50,0.00\n"
    "1,3.50,0.50,1.00\n"
    "2,3.80,0.50,2.00\n"
)

# 論理名 (frame/voltage/current/capacity) → CSV ヘッダ列名。
COMMON_COLUMN_MAP = {
    "frame": "index",
    "voltage": "Ewe/V",
    "current": "I/mA",
    "capacity": "Q/mAh",
}


def _write_csv(tmp_path: Path, content: str, name: str = "echem.csv") -> str:
    """一時 CSV を書き出しそのパス文字列を返す (tmp_path フィクスチャ利用)。"""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


# ===========================================================================
# 1. 正常系テストケース
# ===========================================================================


def test_read_echem_csv_maps_columns_and_syncs_vic(tmp_path):
    # 【テスト目的】: frame,V,I,Q 列 CSV を column_map で読み V/I/Q がフレーム同期チャネルになること (TC-202-01)
    # 【テスト内容】: read_echem_csv → to_channels → value_for の一連経路を検証
    # 【期待される動作】: voltage/current/capacity kind の ExternalChannel 群が生成され値が一致
    # 🔵 信頼性: TC-N01 / TC-202-01 / REQ-007 / interfaces.py L211-218 に直接依拠

    # 【テストデータ準備】: 特殊列名 (Ewe/V 等) を含む代表 CSV を tmp_path に用意
    # 【初期条件設定】: 3 フレーム分の充放電データ
    csv_path = _write_csv(tmp_path, COMMON_CSV)

    # 【実際の処理実行】: read_echem_csv を呼び EchemData を得る (stdlib csv・eval 不使用)
    data = read_echem_csv(csv_path, column_map=COMMON_COLUMN_MAP)

    # 【結果検証】: 各論理列が CSV 記載順で tuple 化されていること
    assert data.voltage == (3.20, 3.50, 3.80)  # 【確認内容】: 電圧列の抽出 🔵
    assert data.current == (0.50, 0.50, 0.50)  # 【確認内容】: 電流列の抽出 🔵
    assert data.capacity == (0.00, 1.00, 2.00)  # 【確認内容】: 容量列の抽出 🔵

    # 【期待値確認】: to_channels が対応 kind の ExternalChannel を返しフレーム同期する
    channels = {ch.kind: ch for ch in data.to_channels()}
    assert isinstance(channels["voltage"], ExternalChannel)  # 【確認内容】: 型が ExternalChannel 🔵
    assert set(channels) == {"voltage", "current", "capacity"}  # 【確認内容】: kind の網羅 🔵
    assert channels["voltage"].value_for(1) == 3.50  # 【確認内容】: frame_index 同期 🔵
    assert channels["capacity"].value_for(2) == 2.00  # 【確認内容】: 容量チャネルの同期 🔵


def test_read_echem_csv_applies_linear_capacity_to_x(tmp_path):
    # 【テスト目的】: capacity_to_x=(a,b) で composition_x[i] == a·Q[i] + b となること (TC-202-02)
    # 【テスト内容】: 線形換算の適用と composition kind チャネルの生成を検証
    # 【期待される動作】: 全フレームに x = a·Q + b が適用され composition チャネルが生成
    # 🔵 信頼性: TC-N02 / TC-202-02 / REQ-007 / interfaces.py L215 に直接依拠

    # 【テストデータ準備】: 共通 CSV に (slope, intercept)=(0.5, 0.1) を適用 (Q=0,1,2 → x=0.1,0.6,1.1)
    csv_path = _write_csv(tmp_path, COMMON_CSV)

    # 【実際の処理実行】: 容量→x 線形換算つきで読み込む
    data = read_echem_csv(csv_path, column_map=COMMON_COLUMN_MAP, capacity_to_x=(0.5, 0.1))

    # 【結果検証】: 換算値が capacity から派生し期待どおりであること
    assert data.composition_x == pytest.approx((0.1, 0.6, 1.1))  # 【確認内容】: x=a·Q+b の適用 🔵

    # 【期待値確認】: composition kind チャネルが生成され value_for が換算値を返す
    channels = {ch.kind: ch for ch in data.to_channels()}
    assert "composition" in channels  # 【確認内容】: composition チャネル生成 🔵
    assert channels["composition"].value_for(2) == pytest.approx(1.1)  # 【確認内容】: 換算値の同期 🔵


def test_read_echem_csv_no_conversion_leaves_composition_empty(tmp_path):
    # 【テスト目的】: capacity_to_x 未指定なら composition_x が空・composition チャネル非生成 (TC-N03)
    # 【テスト内容】: 換算則未指定時に x を捏造しないことを検証
    # 【期待される動作】: composition_x == () で composition kind が現れない
    # 🔵 信頼性: interfaces.py L206/L215 (x は換算済み派生) / dataflow.md L124 (捏造しない) に依拠

    # 【テストデータ準備】: 共通 CSV、capacity_to_x は省略 (既定 None)
    csv_path = _write_csv(tmp_path, COMMON_CSV)

    # 【実際の処理実行】: 換算則なしで読み込む
    data = read_echem_csv(csv_path, column_map=COMMON_COLUMN_MAP)

    # 【結果検証】: composition_x が空で composition チャネルが誤生成されないこと
    assert data.composition_x == ()  # 【確認内容】: 換算未指定なら x を生成しない 🔵
    kinds = {ch.kind for ch in data.to_channels()}
    assert "composition" not in kinds  # 【確認内容】: composition チャネル非生成 🔵


def test_read_echem_csv_voltage_only_leaves_others_empty(tmp_path):
    # 【テスト目的】: column_map に voltage(+frame) のみ指定した場合 current/capacity が空になること (TC-N04)
    # 【テスト内容】: 部分列マッピングの縮退挙動を検証
    # 【期待される動作】: 指定されない論理列は空 tuple、voltage チャネルのみ生成
    # 🟡 信頼性: interfaces.py L204-206 (任意列の既定 ()) から妥当推測

    # 【テストデータ準備】: voltage のみを含む簡略 CSV
    csv_path = _write_csv(tmp_path, "index,Ewe/V\n0,3.20\n1,3.50\n", name="volt.csv")
    column_map = {"frame": "index", "voltage": "Ewe/V"}

    # 【実際の処理実行】: voltage のみを対象に読み込む
    data = read_echem_csv(csv_path, column_map=column_map)

    # 【結果検証】: voltage は取得され、未指定列は空縮退すること
    assert data.voltage == (3.20, 3.50)  # 【確認内容】: 電圧列の抽出 🟡
    assert data.current == ()  # 【確認内容】: 未指定の電流列は空 🟡
    assert data.capacity == ()  # 【確認内容】: 未指定の容量列は空 🟡
    assert data.composition_x == ()  # 【確認内容】: 換算未指定で x も空 🟡
    kinds = tuple(ch.kind for ch in data.to_channels())
    assert kinds == ("voltage",)  # 【確認内容】: voltage チャネルのみ生成 🟡


def test_echem_data_frozen_and_structural_equality():
    # 【テスト目的】: EchemData が frozen・構造的等価・to_channels を直接満たすこと (TC-N05)
    # 【テスト内容】: I/O を介さないデータモデル単体契約 (frozen dataclass) を検証
    # 【期待される動作】: 同値は == で真、フィールド再代入は FrozenInstanceError
    # 🔵 信頼性: interfaces.py L199-208 / CLAUDE.md (frozen dataclass 規約) に依拠

    # 【テストデータ準備】: 同値な EchemData を 2 つ生成 (全 tuple のためハッシュ可・等価可)
    data_a = EchemData(voltage=(3.2, 3.5), current=(0.5, 0.5))
    data_b = EchemData(voltage=(3.2, 3.5), current=(0.5, 0.5))

    # 【結果検証】: 構造的等価が成立すること
    assert data_a == data_b  # 【確認内容】: 同値 EchemData は == で真 🔵

    # 【期待値確認】: frozen によりフィールド再代入が禁止されること
    with pytest.raises(dataclasses.FrozenInstanceError):
        data_a.voltage = ()  # type: ignore[misc]  # 【確認内容】: 再代入で FrozenInstanceError 🔵

    # 【追加検証】: 直接生成でも to_channels が非空フィールドをチャネル化すること
    kinds = {ch.kind for ch in data_a.to_channels()}
    assert kinds == {"voltage", "current"}  # 【確認内容】: 非空フィールドのみチャネル化 🔵


def test_to_channels_excludes_none_frames_from_sync_map():
    # 【テスト目的】: フィールドに None を含む場合 to_channels の sync_map が None フレームを除外すること (TC-N06)
    # 【テスト内容】: 欠損フレームが不同期 (キー不在) として表現されることを検証
    # 【期待される動作】: 欠損フレームは sync_map に不在、value_for が None を返す
    # 🟡 信頼性: dataflow.md L124 (捏造しない) / channel.py L43 (value_for は get で None 縮退) から妥当推測

    # 【テストデータ準備】: frame 1 が欠損 (None) の voltage を持つ EchemData (行数不一致縮退後の状態を代表)
    data = EchemData(voltage=(3.2, None, 3.8))

    # 【実際の処理実行】: to_channels で voltage チャネルを得る
    channel = {ch.kind: ch for ch in data.to_channels()}["voltage"]

    # 【結果検証】: 存在フレームは値を保持し欠損フレームは None (キー不在) であること
    assert channel.value_for(0) == 3.2  # 【確認内容】: frame 0 は値保持 🟡
    assert channel.value_for(2) == 3.8  # 【確認内容】: frame 2 は値保持 🟡
    assert channel.value_for(1) is None  # 【確認内容】: 欠損フレームは None (0 埋め/補間しない) 🟡
    assert 1 not in channel.sync_map  # 【確認内容】: 欠損フレームは sync_map に不在 🟡


def test_read_echem_csv_is_deterministic(tmp_path):
    # 【テスト目的】: 同一 CSV・同一引数で 2 回読み結果が等価であること (TC-N07)
    # 【テスト内容】: 決定論 (再現性) の検証
    # 【期待される動作】: 行順・列順で結果が揺れず == で真
    # 🔵 信頼性: NFR-102 / REQ-402 / CLAUDE.md 不変条件に直接依拠

    # 【テストデータ準備】: 共通 CSV に線形換算 (0.5, 0.0) を付与して 2 回読む
    csv_path = _write_csv(tmp_path, COMMON_CSV)

    # 【実際の処理実行】: 同一入力で 2 回呼び出す
    first = read_echem_csv(csv_path, column_map=COMMON_COLUMN_MAP, capacity_to_x=(0.5, 0.0))
    second = read_echem_csv(csv_path, column_map=COMMON_COLUMN_MAP, capacity_to_x=(0.5, 0.0))

    # 【結果検証】: 2 回の結果がビット同一 (等価) であること
    assert first == second  # 【確認内容】: dict イテレーション順等に依存しない決定論 🔵


# ===========================================================================
# 2. 異常系テストケース
# ===========================================================================


def test_read_echem_csv_missing_column_raises_valueerror_with_name(tmp_path):
    # 【テスト目的】: 要求列が CSV ヘッダに無いとき列名を含む ValueError を送出すること (TC-A01)
    # 【テスト内容】: 誤った列参照で沈黙せず処理継続不能を明示することを検証
    # 【期待される動作】: ValueError が送出されメッセージに欠損列名 "Q/mAh" を含む
    # 🔵 信頼性: TC-202-03 / EDGE-003 / dataflow.md L110 / design-interview D-Q7 に直接依拠

    # 【テストデータ準備】: Q/mAh 列を持たない CSV に、capacity を要求する column_map を与える
    csv_path = _write_csv(tmp_path, "index,Ewe/V\n0,3.20\n1,3.50\n", name="missing.csv")
    column_map = {"frame": "index", "voltage": "Ewe/V", "capacity": "Q/mAh"}

    # 【実際の処理実行/結果検証】: 列欠損は明示エラーで停止し不完全な EchemData を返さない
    with pytest.raises(ValueError) as exc:
        read_echem_csv(csv_path, column_map=column_map)
    assert "Q/mAh" in str(exc.value)  # 【確認内容】: どの列が無いかを列名で提示 🔵


def test_read_echem_csv_non_numeric_cell_raises_explicit_error(tmp_path):
    # 【テスト目的】: 数値であるべきセルが非数値のとき列名を含む明示エラーを送出すること (TC-A02)
    # 【テスト内容】: float() 変換失敗を握りつぶさず明示し、eval を経由しないことを検証
    # 【期待される動作】: ValueError が送出されメッセージに問題列名 "Ewe/V" を含む
    # 🔵 信頼性: 完了条件 (数値変換失敗の明示エラー・eval 不使用) / architecture.md L130 に直接依拠

    # 【テストデータ準備】: Ewe/V 列に float 化不能な "abc" を含む CSV
    bad_csv = "index,Ewe/V,I/mA,Q/mAh\n0,3.20,0.50,0.00\n1,abc,0.50,1.00\n"
    csv_path = _write_csv(tmp_path, bad_csv, name="bad.csv")

    # 【実際の処理実行/結果検証】: 変換失敗は列名付き明示エラーで停止
    with pytest.raises(ValueError) as exc:
        read_echem_csv(csv_path, column_map=COMMON_COLUMN_MAP)
    assert "Ewe/V" in str(exc.value)  # 【確認内容】: 数値化できない列を列名で提示 🔵

    # 【追加検証】: 実装が eval/exec/ast.literal_eval を経由しない (任意コード実行経路を持たない)
    source = Path(echem_module.__file__).read_text(encoding="utf-8")
    assert "eval(" not in source  # 【確認内容】: eval() を使用しない (セキュリティ) 🔵
    assert "exec(" not in source  # 【確認内容】: exec() を使用しない (セキュリティ) 🔵
    assert "literal_eval" not in source  # 【確認内容】: ast.literal_eval を使用しない 🔵


def test_biologic_mpr_loader_load_raises_not_implemented():
    # 【テスト目的】: 未実装機種ローダ (.mpr) が呼出で NotImplementedError を送出すること (TC-A03)
    # 【テスト内容】: Protocol 境界は用意しつつ未実装を明示し誤用時に沈黙しないことを検証
    # 【期待される動作】: BiologicMprLoader().load(path) が NotImplementedError
    # 🔵 信頼性: TC-202-04 / REQ-008 / interfaces.py L227-228 に直接依拠

    # 【テストデータ準備】: M3 スコープ外の .mpr パスを渡す (バイナリパーサ未実装)
    loader = BiologicMprLoader()

    # 【実際の処理実行/結果検証】: 中途半端な戻り値を返さず例外で停止
    with pytest.raises(NotImplementedError):
        loader.load("any.mpr")  # 【確認内容】: 未実装は NotImplementedError で明示 🔵


def test_biologic_mpr_loader_satisfies_echem_loader_protocol():
    # 【テスト目的】: BiologicMprLoader が EchemLoader Protocol の構造 (load メソッド) を満たすこと (TC-A04)
    # 【テスト内容】: 交換境界として型互換 (load(path) シグネチャ) であることを検証
    # 【期待される動作】: load が callable で 'path' パラメータを持つ (実装未完でも境界は成立)
    # 🟡 信頼性: REQ-008 / interfaces.py L221-228 / TASK-0025 Protocol 範から妥当推測

    # 【テストデータ準備】: EchemLoader 型として機種ローダを保持 (静的境界の構造適合を確認)
    loader: EchemLoader = BiologicMprLoader()

    # 【結果検証】: 構造的準拠 (load メソッドの存在と callable 性)
    assert hasattr(loader, "load")  # 【確認内容】: load メソッドを持つ 🟡
    assert callable(loader.load)  # 【確認内容】: load は呼び出し可能 🟡

    # 【期待値確認】: load(path) シグネチャ (path 引数) を持つこと
    params = inspect.signature(BiologicMprLoader.load).parameters
    assert "path" in params  # 【確認内容】: load(self, path) の交換境界シグネチャ 🟡


# ===========================================================================
# 3. 境界値テストケース
# ===========================================================================


def test_read_echem_csv_ragged_rows_pad_none_and_warn(tmp_path):
    # 【テスト目的】: 列間で行数が不一致 (空セル) のとき欠損を None にし警告すること (TC-BV01)
    # 【テスト内容】: 部分同期の境界で列欠損 (エラー) とは非対称に警告で縮退継続することを検証
    # 【期待される動作】: 欠損フレームの capacity が None、voltage は全フレーム保持、UserWarning 発生
    # 🟡 信頼性: EDGE-003 / TC-202-03 / design-interview D-Q7 に依拠 (警告文言・縮退詳細は 🟡)

    # 【テストデータ準備】: frame 1 の Q/mAh セルが空 (電気化学ロガーと回折フレームの記録ずれを代表)
    ragged_csv = "index,Ewe/V,I/mA,Q/mAh\n0,3.20,0.50,0.00\n1,3.50,0.50,\n2,3.80,0.50,2.00\n"
    csv_path = _write_csv(tmp_path, ragged_csv, name="ragged.csv")

    # 【実際の処理実行】: 行数不一致は警告で継続し欠損 None に縮退
    with pytest.warns(UserWarning):
        data = read_echem_csv(csv_path, column_map=COMMON_COLUMN_MAP)

    # 【結果検証】: 存在値は保持し欠損のみ None (0 埋め/補間しない)
    assert data.voltage == (3.20, 3.50, 3.80)  # 【確認内容】: voltage 側は全フレーム保持 🟡
    assert data.capacity == (0.00, None, 2.00)  # 【確認内容】: 欠損セルは None 縮退 🟡

    # 【期待値確認】: 欠損フレームは capacity チャネルの sync_map に不在
    channel = {ch.kind: ch for ch in data.to_channels()}["capacity"]
    assert channel.value_for(1) is None  # 【確認内容】: 欠損フレームは不同期 (None) 🟡
    assert 1 not in channel.sync_map  # 【確認内容】: 欠損フレームは sync_map に不在 🟡


def test_read_echem_csv_header_only_returns_empty(tmp_path):
    # 【テスト目的】: ヘッダのみ (データ行 0 件) の最小 CSV で空 EchemData を返すこと (TC-BV02)
    # 【テスト内容】: 例外を投げず空 tuple・チャネルなしに安全縮退することを検証
    # 【期待される動作】: 全フィールドが空 tuple、to_channels() == ()
    # 🟡 信頼性: 空入力縮退の一般規約 (clustering 等の空縮退) から妥当推測

    # 【テストデータ準備】: データ行を持たないヘッダのみ CSV (空計測ファイル・初期化直後を代表)
    csv_path = _write_csv(tmp_path, "index,Ewe/V,I/mA,Q/mAh\n", name="empty.csv")

    # 【実際の処理実行】: 0 件でクラッシュせず読み込む
    data = read_echem_csv(csv_path, column_map=COMMON_COLUMN_MAP)

    # 【結果検証】: 空でも型 (tuple) を保ちチャネルを誤生成しないこと
    assert data.voltage == ()  # 【確認内容】: 電圧列は空 tuple 🟡
    assert data.current == ()  # 【確認内容】: 電流列は空 tuple 🟡
    assert data.capacity == ()  # 【確認内容】: 容量列は空 tuple 🟡
    assert data.to_channels() == ()  # 【確認内容】: 空入力ではチャネルを生成しない 🟡


def test_read_echem_csv_single_row(tmp_path):
    # 【テスト目的】: データ行 1 件の最小非空ケースで単一要素 tuple になること (TC-BV03)
    # 【テスト内容】: 1 フレームでも正しく同期しオフバイワンしないことを検証
    # 【期待される動作】: voltage == (3.20,)、voltage チャネル value_for(0) == 3.20
    # 🟡 信頼性: interfaces.py 契約からの自然な境界 (妥当推測)

    # 【テストデータ準備】: 単一スナップショット計測を代表するデータ行 1 件の CSV
    csv_path = _write_csv(tmp_path, "index,Ewe/V,I/mA,Q/mAh\n0,3.20,0.50,0.00\n", name="single.csv")

    # 【実際の処理実行】: 1 行のみを読み込む
    data = read_echem_csv(csv_path, column_map=COMMON_COLUMN_MAP)

    # 【結果検証】: 単一要素でも tuple 構造とフレーム同期を保つこと
    assert data.voltage == (3.20,)  # 【確認内容】: 単一要素 tuple を保持 🟡
    channel = {ch.kind: ch for ch in data.to_channels()}["voltage"]
    assert channel.value_for(0) == 3.20  # 【確認内容】: frame 0 の単一同期 🟡


def test_capacity_to_x_identity_equals_capacity(tmp_path):
    # 【テスト目的】: capacity_to_x=(1.0, 0.0) の恒等換算で composition_x が capacity に一致すること (TC-BV04)
    # 【テスト内容】: 線形換算式 x=a·Q+b の a=1,b=0 境界で崩れないことを検証
    # 【期待される動作】: composition_x == capacity (slope/intercept の適用順が正しい)
    # 🔵 信頼性: interfaces.py L215 (x = a·Q + b) に直接依拠

    # 【テストデータ準備】: 共通 CSV に恒等係数 (1.0, 0.0) を適用 (容量そのものを x 軸に使う簡略運用)
    csv_path = _write_csv(tmp_path, COMMON_CSV)

    # 【実際の処理実行】: 恒等換算つきで読み込む
    data = read_echem_csv(csv_path, column_map=COMMON_COLUMN_MAP, capacity_to_x=(1.0, 0.0))

    # 【結果検証】: 恒等係数で capacity と一致すること
    assert data.composition_x == pytest.approx(data.capacity)  # 【確認内容】: 恒等換算は capacity と一致 🔵
