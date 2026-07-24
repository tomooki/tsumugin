"""operando/echem — 電気化学 CSV マッパ + Loader Protocol (FR-311 / REQ-007/008)。

【モジュール概要】: 充放電 (電気化学) の汎用 CSV を stdlib ``csv`` のみで読み、電圧/電流/容量
と容量→組成 x の線形換算値を、回折フレームに同期した ``ExternalChannel`` 群として供給する。
機種別バイナリ (.mpr 等) 用の交換境界 ``EchemLoader`` Protocol と未実装スタブも定義する。
【実装方針】: 数値変換は ``float()`` のみで行い、危険な動的評価は一切用いない (architecture.md L130)。
列欠損は列名入り ValueError で停止、行数不一致 (空セル) は None + UserWarning で縮退継続 (D-Q7 / EDGE-003)。
🔵 信頼性レベル: interfaces.py L199-228 / dataflow.md L16-17/L110/L124 / requirements §2-§4 に依拠。
"""

from __future__ import annotations

import csv
import warnings
from dataclasses import dataclass
from typing import Mapping, Protocol

from tsumugin.model import ExternalChannel
from tsumugin.model.channel import ChannelKind

# 【フィールド→kind 対応】: EchemData の各データフィールドを ExternalChannel の kind に写像する。
# frame は同期キー用途で EchemData に保持しないため kind を持たない (voltage/current/capacity/composition のみ)。🔵
_FIELD_KINDS: tuple[tuple[str, ChannelKind], ...] = (
    ("voltage", "voltage"),
    ("current", "current"),
    ("capacity", "capacity"),
    ("composition_x", "composition"),
)

# 【CSV から抽出する論理列】: column_map のうち EchemData のデータ列になる論理名 (frame は同期キーで対象外)。🔵
_DATA_LOGICALS: tuple[str, ...] = ("voltage", "current", "capacity")


@dataclass(frozen=True)
class EchemData:
    """フレーム同期済みの電気化学量 (frozen)。欠損は None、全フィールド tuple。

    【機能概要】: voltage を位置必須、current/capacity/composition_x を既定空 tuple で保持する不変値オブジェクト。
    【実装方針】: 全フィールドを tuple にしてハッシュ可・構造的等価可にし、to_channels で非空フィールドのみチャネル化。
    【テスト対応】: TC-N01〜N06 (frozen/等価/to_channels/None 除外) を通す。
    🔵 信頼性レベル: interfaces.py L199-208 / CLAUDE.md (frozen dataclass 規約) に依拠。
    """

    voltage: tuple[float | None, ...]  # 【電圧列】: 位置必須 (V) 🔵
    current: tuple[float | None, ...] = ()  # 【電流列】: 既定空 (I) 🔵
    capacity: tuple[float | None, ...] = ()  # 【容量列】: 既定空 (Q) 🔵
    # 【改善内容】: field(default=()) を他フィールドと同じ平易な既定値 () に統一 (tuple は不変で field 不要) 🔵
    composition_x: tuple[float | None, ...] = ()  # 【換算済み組成 x】: 既定空 🔵

    def to_channels(self) -> tuple[ExternalChannel, ...]:
        """非空フィールドを対応 kind の ExternalChannel 群へ変換する。

        【実装方針】: 各フィールドを (frame_index → value) の sync_map に変換。None フレームは
        欠損=不同期として sync_map に含めない (捏造しない / dataflow.md L124)。空フィールドは生成しない。
        【テスト対応】: TC-N01/N02/N04/N06 (kind 網羅・同期・None 除外) を通す。
        🟡 信頼性レベル: interfaces.py L208 / dataflow.md L124 / channel.py value_for から妥当推測。
        """
        channels: list[ExternalChannel] = []
        # 【フィールド走査】: 定義順 (voltage→current→capacity→composition) に処理し決定論的な並びを保証 🔵
        for field_name, kind in _FIELD_KINDS:
            values: tuple[float | None, ...] = getattr(self, field_name)
            # 【空縮退】: 既定 () のフィールドはチャネルを生成しない (誤生成防止) 🔵
            if not values:
                continue
            # 【同期写像構築】: None フレームを除外し frame_index → value の写像にする (欠損は不同期) 🟡
            sync_map = {
                frame_index: value
                for frame_index, value in enumerate(values)
                if value is not None
            }
            channels.append(ExternalChannel(kind=kind, sync_map=sync_map))
        # 【決定論】: フィールド定義順で確定した並びの tuple を返す 🔵
        return tuple(channels)


def read_echem_csv(
    path: str,
    *,
    column_map: Mapping[str, str],
    capacity_to_x: tuple[float, float] | None = None,
) -> EchemData:
    """電気化学 CSV を読み込み EchemData を返す (stdlib csv・eval 不使用)。

    【機能概要】: column_map (論理名→CSV 列名) で列を抽出し、容量→x 線形換算を任意適用する。
    【実装方針】: csv.DictReader で読み、数値セルは float() で明示変換。列欠損は列名入り ValueError で
    停止し、空セル (行数不一致) は None + UserWarning で縮退継続する (非対称政策 / D-Q7・EDGE-003)。
    【テスト対応】: TC-N01/N02/N03/N04/N07, TC-A01/A02, TC-BV01/BV02/BV03/BV04 を通す。
    🔵 信頼性レベル: interfaces.py L211-218 / requirements §2.2/§4 に依拠。

    @param path: CSV ファイルパス
    @param column_map: 論理名→CSV 列名 (例 {"frame": "index", "voltage": "Ewe/V", ...})
    @param capacity_to_x: (slope, intercept)。指定時 x = slope·Q + intercept を全フレームに適用
    @returns: フレーム同期済みの EchemData
    """
    # 【CSV 読込】: stdlib csv のみ使用 (pandas 等の外部パーサ不使用 / REQ-403) 🔵
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []  # 【ヘッダ列名】: 列存在検証の基準 🔵
        # 【列欠損検証】: column_map が要求する全列がヘッダに存在するか確認 (frame も含む) 🔵
        for logical_name, csv_column in column_map.items():
            # 【明示エラー】: 欠損列は列名を提示して処理を停止 (沈黙しない / dataflow.md L110) 🔵
            if csv_column not in header:
                raise ValueError(
                    f"echem CSV に必要な列 '{csv_column}' (論理名 '{logical_name}') "
                    f"が見つかりません。CSV ヘッダ: {header}"
                )
        rows = list(reader)  # 【全行取得】: CSV 記載順を保持し決定論を担保 🔵

    # 【欠損警告フラグ】: 空セルを一度でも検出したら UserWarning を出す (縮退継続を通知) 🟡
    saw_missing_cell = False
    # 【列別値の収集器】: 論理データ列ごとに frame 順の値 tuple を組み立てる 🔵
    collected: dict[str, tuple[float | None, ...]] = {}
    for logical_name in _DATA_LOGICALS:
        csv_column = column_map.get(logical_name)
        # 【未指定列の縮退】: column_map に無い論理列は空 tuple のまま (voltage-only 等) 🔵
        if csv_column is None:
            collected[logical_name] = ()
            continue
        column_values: list[float | None] = []
        for row in rows:
            cell = row.get(csv_column)
            # 【欠損セル判定】: None または空白のみのセルは行数不一致による欠損とみなす 🟡
            if cell is None or cell.strip() == "":
                column_values.append(None)  # 【None 縮退】: 0 埋め/補間せず欠損を明示 🟡
                saw_missing_cell = True
                continue
            # 【数値変換】: float() のみで明示変換 (eval を経由しない / 完了条件) 🔵
            try:
                column_values.append(float(cell))
            except ValueError as exc:
                # 【変換失敗の明示エラー】: 問題列名を提示して停止 (握りつぶさない) 🔵
                raise ValueError(
                    f"echem CSV の列 '{csv_column}' の値 {cell!r} を数値に変換できません。"
                ) from exc
        collected[logical_name] = tuple(column_values)

    # 【空セル警告】: 行数不一致で欠損が生じた場合のみ縮退を通知する (列欠損とは非対称) 🟡
    if saw_missing_cell:
        warnings.warn(
            "echem CSV の列間で行数が一致しません。欠損フレームを None として縮退します。",
            UserWarning,
            stacklevel=2,
        )

    # 【容量→x 線形換算】: capacity_to_x 指定かつ capacity 取得時のみ x = slope·Q + intercept を適用 🔵
    composition_x: tuple[float | None, ...] = ()
    capacity_values = collected["capacity"]
    if capacity_to_x is not None and capacity_values:
        slope, intercept = capacity_to_x
        composition_x = tuple(
            # 【欠損伝播】: 容量が None のフレームは換算値も None にする (捏造しない) 🟡
            None if q is None else slope * q + intercept
            for q in capacity_values
        )

    # 【結果生成】: 決定論的に確定した各列 tuple で EchemData を構築 🔵
    return EchemData(
        voltage=collected["voltage"],
        current=collected["current"],
        capacity=capacity_values,
        composition_x=composition_x,
    )


class EchemLoader(Protocol):
    """機種別ローダの交換境界 (Protocol)。

    【機能概要】: パスから EchemData を読み出す load メソッドの構造的契約を定義する。
    【テスト対応】: TC-A04 (load(path) シグネチャの構造適合) を通す。
    🔵 信頼性レベル: interfaces.py L221-224 / REQ-008 に依拠。
    """

    def load(self, path: str) -> EchemData:
        """機種別ファイルを読み EchemData を返す (実装はローダごと)。"""
        ...


class BiologicMprLoader:
    """Biologic .mpr バイナリローダの旧交換境界 (**実装は移管済み — 本クラスは使わないこと**)。

    【移管先 (Issue #71/#127)】: 実 .mpr パーサは ``tsumugin.interop.biologic.parse_mpr``
      (galvani 遅延 import) + ``curve_from_mpr_data`` / ``align_frames``。② は ``align_echem``
      ツール (mcp/echem_tools.py) から到達可能。本クラスは M3 期の ``EchemLoader`` Protocol
      向けスタブで、後方互換のため型だけ残している (「.mpr は未実装」と誤読しないこと —
      未実装なのは本クラス経由の経路のみ)。
    【実装方針】: 呼出時に NotImplementedError で移管先を案内し、中途半端な戻り値で沈黙しない。
    🔵 信頼性レベル: interfaces.py L227-228 / REQ-008 (歴史的) + Issue #127 項目 3。
    """

    def load(self, path: str) -> EchemData:
        """.mpr 読込は本クラスでは提供しない。``interop.biologic.parse_mpr`` を使うこと。"""
        # 【移管明示 (Issue #127)】: 死骸スタブの誤読 (「.mpr 未実装」) を防ぐため移管先を案内する 🔵
        raise NotImplementedError(
            "BiologicMprLoader.load は使われていません。実 .mpr 読込は "
            "tsumugin.interop.biologic.parse_mpr (② align_echem ツール) へ移管済みです。"
        )
