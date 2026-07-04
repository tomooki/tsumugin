"""時系列トラジェクトリ + CSV 書き出し (REQ-005 / REQ-402 / FR-306 / interfaces.py L141-165)。

逐次 Rietveld 解析の各フレーム結果を「1 行 = 1 フレーム」の構造化レコード ``FrameRecord`` として
保持し、フレーム列と相ライフサイクルをまとめた ``Trajectory`` を stdlib ``csv`` で CSV ファイルへ
書き出す (``Trajectory.to_csv``)。REQ-009 の「外部委譲出口」を CSV で満たす出力層。
乱数・時刻・環境依存を持たず、同一 ``Trajectory`` から常に同一バイト列を生成する (REQ-402 決定論)。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from typing import Mapping

from tsumugin._json import finite_or_none
from tsumugin.model import PhaseInstance, PhaseLifecycle

__all__ = ["FrameRecord", "Trajectory"]

# 【凍結列レイアウト】: フレーム共通列 (固定・先頭順)。テスト側 FRAME_COMMON_COLUMNS と一致させる 🔵
_FRAME_COMMON_COLUMNS = [
    "frame_index",
    "axis_value",
    "temperature",
    "rwp",
    "chi2",
    "changepoint",
    "changepoint_reasons",
    "refine_failed",
]
# 【凍結列レイアウト】: 相ごと列のうち「当該フレームの相由来」の接尾辞 (格子 abc / scale / wt_frac)。順序固定 🔵
# 【改善内容】: 相由来列と lifecycle 由来列を分離し、空欄プレースホルダの個数をこの定義から導出可能にした 🔵
_PHASE_FRAME_SUFFIXES = [
    "a",
    "b",
    "c",
    "scale",
    "wt_frac",
]
# 【凍結列レイアウト】: 相ごと列のうち「相メタ (lifecycle) 由来」の接尾辞。全行一貫で並ぶ。順序固定 🔵
_PHASE_LIFECYCLE_SUFFIXES = [
    "birth_frame",
    "death_frame",
    "confidence",
]
# 【凍結列レイアウト】: 相ごと列 = フレーム由来 + lifecycle 由来 の連結 (計 8 列)。
# 【設計方針】: 分割済み 2 リストから合成し、テスト側 PHASE_FIELD_SUFFIXES との一致とヘッダ生成の単一情報源を担保 🔵
_PHASE_FIELD_SUFFIXES = _PHASE_FRAME_SUFFIXES + _PHASE_LIFECYCLE_SUFFIXES
# 【区切り文字】: changepoint_reasons(tuple) を 1 セルへ連結する決定論区切り。CSV デリミタと非衝突 🟡
_REASONS_DELIMITER = "|"


@dataclass(frozen=True)
class FrameRecord:
    """1 フレーム分の逐次解析結果 (frozen dataclass / interfaces.py L141-153)。

    【機能概要】: フレーム軸値・相集合・Rwp/GOF・changepoint・失敗フラグを 1 行として保持する不変値オブジェクト。
    【実装方針】: 契約フィールド順 (要件 §2.1) に沿った frozen dataclass とし、CSV 化ロジックは持たない器に徹する。
    【テスト対応】: T-N01〜T-B07 全ケースの入力 (tests/test_trajectory.py の ``_record`` が全 9 フィールドを供給)。
    🔵 信頼性レベル: interfaces.py L141-153 / 要件 §2.1 に依拠 (refine_failed セマンティクスのみ 🟡)。
    """

    frame_index: int  # 【フレーム番号】: 0 起点想定。負値許容 (入力側責務) 🔵
    axis_value: float | None = None  # 【フレーム軸値】: index 軸/欠損は None 可 🔵
    temperature: float | None = None  # 【温度】: ExternalChannel 由来。無ければ None 🔵
    phases: tuple[PhaseInstance, ...] = ()  # 【確定相集合】: 当該フレームの相 (順序保持) 🔵
    rwp: float | None = None  # 【重み付きプロファイル R】: 失敗フレームは None 🔵
    chi2: float | None = None  # 【GOF (χ²)】: 失敗フレームは None 🔵
    changepoint: bool = False  # 【changepoint 判定フラグ】 🔵
    changepoint_reasons: tuple[str, ...] = ()  # 【判定理由】: rwp_jump/lattice_jump/new_peaks の部分集合 🔵
    refine_failed: bool = False  # 【精密化失敗フラグ】: EDGE-002 🟡


@dataclass(frozen=True)
class Trajectory:
    """フレーム列 + 相ライフサイクルの集約 (frozen dataclass / interfaces.py L156-165)。

    【機能概要】: フレーム順の ``FrameRecord`` 列と相 ref→``PhaseLifecycle`` の対応を保持し、CSV へ書き出す。
    【実装方針】: 器 (records/lifecycles) と決定論 CSV 写像 (to_csv) のみを提供。上流結果の結合は TASK-0019 の責務。
    【テスト対応】: T-N01〜T-B07 全ケース。frozen 不変性は T-B06。
    🔵 信頼性レベル: interfaces.py L156-165 / 要件 §2.2-2.3 に依拠。
    """

    records: tuple[FrameRecord, ...] = ()  # 【フレーム順の行】 🔵
    lifecycles: Mapping[str, PhaseLifecycle] = field(default_factory=dict)  # 【相 ref → lifecycle】 🔵

    def to_csv(self, path: str) -> str:
        """records/lifecycles から決定論 CSV を書き出し、書き出したパスを返す。

        【機能概要】: フレーム共通列 + 相ごと列 (格子/scale/wt_frac/lifecycle) の CSV を stdlib ``csv`` で生成する。
        【実装方針】: 相 ref は phases ∪ lifecycles.keys() の ``sorted()`` 昇順で固定し、列順を明示リストで構築。
        None/非有限は空欄化して漏らさない。``newline=""`` / ``utf-8`` で改行・エンコーディングを固定しバイト同一を担保。
        【テスト対応】: T-N01〜T-N06 (正常系)、T-E01〜T-E04 (非有限/None/相なし)、T-B01〜T-B07 (境界/決定論/frozen)。
        🔵 信頼性レベル: 要件 §2.3 / REQ-005 (stdlib csv 限定) / REQ-402 (決定論) に依拠。

        :param path: 出力 CSV パス。戻り値と一致する 🔵
        :returns: 書き出しに成功した CSV パス (入力 path と同一の str) 🔵
        """
        # 【相 ref の確定】: 全フレームの phase_ref と lifecycles キーの和集合を sorted 昇順で固定 (REQ-402) 🔵
        phase_refs = self._sorted_phase_refs()

        # 【ヘッダ構築】: 公開 API header() に委譲 (列順の単一情報源化 / operando 結合出力と共有) 🔵
        header = self.header()

        # 【書き出し】: newline="" / utf-8 で改行・エンコーディング差を排除しバイト同一を担保 (REQ-402) 🔵
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)  # 【ヘッダ行】: 1 行目に列名 🔵
            for record in self.records:
                writer.writerow(self._row_values(record, phase_refs))  # 【1 フレーム 1 行】 🔵

        # 【結果返却】: 書き出しパスを str で返す (export_gpx と同一契約) 🔵
        return str(path)

    def header(self) -> list[str]:
        """CSV ヘッダ (フレーム共通列 + 相ごと 8 列) を決定論順で返す公開 API。

        【機能概要】: ``to_csv`` と同一の列レイアウト (共通列 + 各相 ref の格子/scale/wt_frac/lifecycle) を
          外部 (operando の結合出力 ``combined_csv`` 等) が私有定数へ触れずに取得できるようにする。
        【実装方針】: 相 ref は ``_sorted_phase_refs`` の sorted 昇順で固定し列順を決定論化する。
        🔵 信頼性レベル: to_csv のヘッダ構築ロジックと同一 (単一情報源化) / Issue #5 の私有横断 import 是正方針。
        """
        columns = list(_FRAME_COMMON_COLUMNS)
        for ref in self._sorted_phase_refs():
            columns.extend(f"{ref}.{suffix}" for suffix in _PHASE_FIELD_SUFFIXES)
        return columns

    def rows_by_frame(self) -> dict[int, list[str]]:
        """frame_index → CSV セル列 (``header()`` と同順) の決定論マップを返す公開 API。

        【機能概要】: 外部結合 (operando ``combined_csv``) が frame_index をキーに trajectory 行を引けるよう、
          各 ``FrameRecord`` の決定論セル列を frame_index で索引化して返す (非有限/None は空欄化済み)。
        【実装方針】: 列順は ``header()`` と一致 (同一 ``_sorted_phase_refs`` を用いる)。frame_index は契約上一意。
        🔵 信頼性レベル: _row_values の決定論写像を再利用 / Issue #5 の私有横断 import 是正方針。
        """
        phase_refs = self._sorted_phase_refs()
        return {
            record.frame_index: self._row_values(record, phase_refs)
            for record in self.records
        }

    def _sorted_phase_refs(self) -> list[str]:
        """出力対象の相 ref を phases ∪ lifecycles.keys() の sorted 昇順で返す。

        【実装方針】: set で和集合を作り sorted() で昇順固定 (dict/set の非決定反復順に依存しない)。
        【テスト対応】: T-B03 (和集合 sorted)、T-B04 (lifecycles のみの相も列化)、T-B05 (決定論)。
        🔵 信頼性レベル: 要件 §2.3 / §4.3 EC-4/EC-5 に依拠。
        """
        refs: set[str] = set(self.lifecycles.keys())
        for record in self.records:
            for phase in record.phases:
                refs.add(phase.phase_ref)
        return sorted(refs)

    def _row_values(self, record: FrameRecord, phase_refs: list[str]) -> list[str]:
        """1 フレーム分の CSV セル列 (header と同順) を組み立てる。

        【実装方針】: 共通列 → 各相の格子/scale/wt_frac (当該フレーム相由来) + lifecycle 3 列 (相メタ・全行一貫) の順。
        【テスト対応】: T-N03 (共通列往復)、T-N04 (相列値)、T-E04 (相なし空欄)、T-B03 (出現前空欄)。
        🔵 信頼性レベル: 要件 §2.3 に依拠。
        """
        # 【共通列】: 数値は空欄純化 (_num_cell)、bool は str、reasons は "|" 連結 🔵
        row = [
            _num_cell(record.frame_index),
            _num_cell(record.axis_value),
            _num_cell(record.temperature),
            _num_cell(record.rwp),
            _num_cell(record.chi2),
            str(record.changepoint),
            _REASONS_DELIMITER.join(record.changepoint_reasons),
            str(record.refine_failed),
        ]

        # 【当該フレームの相を ref で引けるよう索引化】: dict 内包のため同一 ref は後勝ち (契約上 ref は一意) 🔵
        phase_by_ref = {phase.phase_ref: phase for phase in record.phases}

        for ref in phase_refs:
            phase = phase_by_ref.get(ref)
            if phase is None:
                # 【相なし】: 当該フレームに存在しない相の格子/scale/wt_frac 列は空欄 (T-E04/T-B03) 🔵
                # 【改善内容】: 空欄数を _PHASE_FRAME_SUFFIXES から導出し、列定義変更時の個数ずれを防止 🔵
                row.extend([""] * len(_PHASE_FRAME_SUFFIXES))
            else:
                # 【格子/scale/wt_frac】: 有限値のみ str 化、None/非有限は空欄 (T-N04/T-E02) 🔵
                row.extend([
                    _num_cell(phase.lattice.a),
                    _num_cell(phase.lattice.b),
                    _num_cell(phase.lattice.c),
                    _num_cell(phase.scale),
                    _num_cell(phase.wt_frac),
                ])

            # 【lifecycle 列】: 相メタとして lifecycles から引き全行一貫。欠損相は空欄 (T-N04/T-B04) 🔵
            lifecycle = self.lifecycles.get(ref)
            if lifecycle is None:
                # 【改善内容】: 空欄数を _PHASE_LIFECYCLE_SUFFIXES から導出し、列定義変更時の個数ずれを防止 🔵
                row.extend([""] * len(_PHASE_LIFECYCLE_SUFFIXES))
            else:
                row.extend([
                    _num_cell(lifecycle.birth_frame),
                    _num_cell(lifecycle.death_frame),
                    _num_cell(lifecycle.confidence),
                ])

        return row


def _num_cell(value: float | int | None) -> str:
    """【機能概要】: 有限な数値は ``str(value)``、None / 非有限 (inf/-inf/NaN) は空文字列を返す。
    【実装方針】: 非有限/None 判定は共有葉モジュール ``_json.finite_or_none`` へ委譲し (Issue #5 の単一情報源化)、
    CSV セル書式は int/float の元表現を保つため判定後に元値を ``str`` 化する (finite_or_none の float 正規化は
    判定にのみ用い、frame_index は "5"、axis_value は "300.0" を維持する)。
    【テスト対応】: T-E01 (None/inf 空欄)、T-E02 (nan 空欄)、T-E03 (None 空欄)、T-B07 (0.0/負値/極小は保持)。
    🔵 信頼性レベル: 要件 §3 非有限制約 / 完了条件③ / _json.finite_or_none 単一実装に依拠。
    """
    # 【判定は単一情報源へ委譲・書式は元値保持】: finite_or_none が None (欠損/非有限) を返せば空欄、
    #   有限なら元の int/float 表現を保って str 化する (falsy な 0.0 も潰さない) 🔵
    return "" if finite_or_none(value) is None else str(value)
