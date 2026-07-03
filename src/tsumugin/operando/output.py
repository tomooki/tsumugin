"""operando/output — 結合出力 + 転移点 (FR-314 / D9 / D-Q10)。

【モジュール概要】: 逐次 Rietveld 解析の ``Trajectory`` と電気化学量 ``EchemData`` を frame_index で
外部結合し、wt_frac(x)/格子(x) と echem 列 (V/I/Q/x) を同一行に並べた CSV を stdlib ``csv`` で
決定論的に書き出す (``combined_csv``)。加えて、判別/分割で確定した境界フレーム index から転移点
x/V±σ を隣接 echem の線形補間で導出する純関数 (``transition_point``) と不変値 ``TransitionPoint`` を提供する。
【実装方針】: 精密化 backend を呼ばない下流の純関数出力層。非有限 (inf/NaN)/None は空欄化/None 縮退し
下流へ漏らさない。CSV は ``newline=""``/``utf-8`` でバイト同一 (``Trajectory.to_csv`` と同一保証)。
🔵 信頼性レベル: interfaces.py L349-363 / architecture.md D9 / design-interview D-Q10 / requirements TASK-0034 に依拠。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass

# 【非有限純化の単一情報源】: dataclass の float フィールドへ inf/-inf/NaN を格納しないための縮退は
#   共有葉モジュール _json.finite_or_none へ委譲する (TASK-0023 の重複統合と整合 / 完了条件5)。🔵
from tsumugin._json import finite_or_none
from tsumugin.operando.echem import EchemData
from tsumugin.sequential.trajectory import (
    _FRAME_COMMON_COLUMNS,
    _PHASE_FIELD_SUFFIXES,
    _num_cell,
)
from tsumugin.sequential.trajectory import Trajectory as _Trajectory

# 【echem 列レイアウト】: CSV に並べる echem フィールドの決定論順 (echem._FIELD_KINDS と同順)。
# 空 tuple の列は追加しない (echem.to_channels の空縮退と同流儀 / B3)。🔵
_ECHEM_FIELDS: tuple[str, ...] = ("voltage", "current", "capacity", "composition_x")


@dataclass(frozen=True)
class TransitionPoint:
    """転移点の電気化学量表現 (frozen / interfaces.py L354-362)。

    【機能概要】: 境界フレームにおける組成 x・電圧 V と、その散布度 σ_x/σ_v を保持する不変値。
    【実装方針】: 補間/差分が定義できないフィールドは None (非有限を格納しない)。frame_index は常に保持。
    【テスト対応】: N2/E3/B1/B4 (補間・None 縮退・端縮退・frozen)。
    🔵 信頼性レベル: interfaces.py L354-362 / CLAUDE.md コーディング規約に依拠。
    """

    frame_index: int  # 【境界フレーム番号】: 判別/分割で確定した境界 index 🔵
    x: float | None  # 【組成 x】: 隣接補間。欠損/端/非有限は None 🔵
    voltage: float | None  # 【電圧 V】: 隣接補間。欠損/端/非有限は None 🔵
    sigma_x: float | None  # 【σ_x】: 隣接差 abs(x[b]-x[b-1])。欠損/端/非有限は None 🔵
    sigma_v: float | None  # 【σ_v】: 隣接差 abs(v[b]-v[b-1])。欠損/端/非有限は None 🔵


def _pair_midpoint_sigma(
    series: tuple[float | None, ...], b: int
) -> tuple[float | None, float | None]:
    """境界フレーム b の隣接 (b-1, b) から中点補間値と隣接差 σ を算出する。

    【実装方針】: b<=0 (前フレームなし) / b>=n (b フレームなし) / 隣接欠損 (None) / 非有限は
    (None, None) へ縮退。それ以外は mid=(v[b-1]+v[b])/2、sigma=abs(v[b]-v[b-1])。
    【テスト対応】: N2 (中点/隣接差)、E3/B1 (欠損隣接・端で None)。
    🔵 信頼性レベル: red-phase 凍結契約 (認可式) / design-interview D-Q10 に依拠。

    @param series: 位置 index=frame_index の echem 列 (composition_x または voltage)
    @param b: 境界フレーム index
    @returns: (中点補間値 or None, 隣接差 σ or None)
    """
    n = len(series)
    # 【端縮退】: 前フレームなし (b<=0) / b フレームなし (b>=n) は隣接不能で None (B1) 🔵
    if b <= 0 or b >= n:
        return None, None
    prev = finite_or_none(series[b - 1])
    cur = finite_or_none(series[b])
    # 【欠損縮退】: 隣接いずれかが欠損/非有限なら補間/差分不能で None (E3) 🔵
    if prev is None or cur is None:
        return None, None
    # 【中点補間 + 隣接差】: 認可式に従い x/V=中点、σ=隣接差 (D-Q10)。結果も finite_or_none で再純化 🔵
    midpoint = finite_or_none((prev + cur) / 2)
    sigma = finite_or_none(abs(cur - prev))
    return midpoint, sigma


def transition_point(echem: EchemData, frame_index: int) -> TransitionPoint:
    """境界フレーム index から転移点 x/V±σ を隣接 echem 線形補間で導出する。

    【機能概要】: composition_x/voltage の (frame_index-1, frame_index) 中点を x/V、隣接差を σ とする。
    【実装方針】: 端・欠損・非有限は該当フィールドを None へ縮退し例外化しない。frame_index は常に保持。
    【テスト対応】: N2/E3/B1/N7 (補間・None 縮退・端縮退・決定論)。
    🔵 信頼性レベル: red-phase 凍結契約 / design-interview D-Q10 / thermal.estimate_transition と同型。

    @param echem: 位置 index=frame_index の電気化学量
    @param frame_index: 転移点を導出する境界フレーム index
    @returns: 境界の x/V/σ を保持する TransitionPoint
    """
    # 【x/σ_x 算出】: composition_x 列の隣接中点/差 🔵
    x, sigma_x = _pair_midpoint_sigma(echem.composition_x, frame_index)
    # 【V/σ_v 算出】: voltage 列の隣接中点/差 🔵
    voltage, sigma_v = _pair_midpoint_sigma(echem.voltage, frame_index)
    # 【結果生成】: frame_index は常に保持し、欠損フィールドのみ None 🔵
    return TransitionPoint(
        frame_index=frame_index,
        x=x,
        voltage=voltage,
        sigma_x=sigma_x,
        sigma_v=sigma_v,
    )


def _echem_columns(echem: EchemData) -> list[tuple[str, tuple[float | None, ...]]]:
    """CSV へ出力する echem 列 (列名, 値 tuple) を決定論順で列挙する。

    【実装方針】: _ECHEM_FIELDS 順に走査し、空 tuple の列は追加しない (B3)。
    🔵 信頼性レベル: echem.to_channels の空縮退と同流儀 / red-phase 凍結契約。
    """
    columns: list[tuple[str, tuple[float | None, ...]]] = []
    for field_name in _ECHEM_FIELDS:
        values: tuple[float | None, ...] = getattr(echem, field_name)
        # 【空縮退】: 既定 () のフィールドは列自体を追加しない (誤列生成防止) 🔵
        if not values:
            continue
        columns.append((field_name, values))
    return columns


def combined_csv(trajectory: _Trajectory, echem: EchemData, path: str) -> str:
    """trajectory 列 + echem 列 (V/I/Q/x) を frame_index で外部結合して CSV 出力する。

    【機能概要】: 各行 = frame_index。trajectory 由来 (格子/scale/wt_frac 等) と echem 由来 (V/I/Q/x) を
    同一行へ並べ wt_frac(x)/格子(x) を表現する。行集合は trajectory ∪ echem の frame_index 和集合。
    【実装方針】: trajectory の列/行値は既存 Trajectory の決定論写像を再利用し、片側欠損・None・非有限は
    空欄化。``newline=""``/``utf-8`` で改行・エンコーディングを固定しバイト同一を担保 (NFR-102)。
    【テスト対応】: N1/N5/N6/E2/B2/B3 (結合・外部結合・決定論・非有限空欄・None 空欄・空列)。
    🔵 信頼性レベル: red-phase 凍結契約 / architecture.md D9 / interfaces.py L349-350 に依拠。

    @param trajectory: 逐次解析トラジェクトリ (frame_index が結合キー)
    @param echem: 位置 index=frame_index の電気化学量
    @param path: 出力 CSV パス (戻り値と一致)
    @returns: 書き出した CSV パス
    """
    # 【trajectory 列の確定】: 既存 Trajectory と同一の相 ref 昇順・列順を再利用 (決定論) 🔵
    phase_refs = trajectory._sorted_phase_refs()
    traj_header = list(_FRAME_COMMON_COLUMNS)
    for ref in phase_refs:
        traj_header.extend(f"{ref}.{suffix}" for suffix in _PHASE_FIELD_SUFFIXES)

    # 【trajectory 行の索引化】: frame_index → 決定論セル列 (Trajectory の非有限空欄化を流用) 🔵
    traj_rows: dict[int, list[str]] = {
        record.frame_index: trajectory._row_values(record, phase_refs)
        for record in trajectory.records
    }
    # 【trajectory 欠損行の空欄テンプレート】: 外部結合で echem のみ存在するフレーム用 🔵
    traj_blank = [""] * len(traj_header)

    # 【echem 列の確定】: 空 tuple 列を除外した (列名, 値) 列 🔵
    echem_cols = _echem_columns(echem)

    # 【frame_index 和集合】: trajectory ∪ echem 各列の位置 index を昇順で確定 (外部結合) 🔵
    frames: set[int] = set(traj_rows.keys())
    for _name, values in echem_cols:
        frames.update(range(len(values)))
    ordered_frames = sorted(frames)

    # 【ヘッダ構築】: trajectory 列 + echem 列 (決定論順) 🔵
    header = traj_header + [name for name, _values in echem_cols]

    # 【書き出し】: newline=""/utf-8 でバイト同一を担保 (NFR-102 / Trajectory.to_csv と同一) 🔵
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)  # 【ヘッダ行】: 1 行目に列名 🔵
        for frame in ordered_frames:
            # 【trajectory セル】: 存在すれば決定論行、無ければ空欄 (外部結合の片側欠損) 🔵
            row = list(traj_rows.get(frame, traj_blank))
            for _name, values in echem_cols:
                # 【echem セル】: 位置範囲内は非有限空欄化して出力、範囲外は空欄 (欠損捏造しない) 🔵
                if 0 <= frame < len(values):
                    row.append(_num_cell(values[frame]))
                else:
                    row.append("")
            writer.writerow(row)  # 【1 フレーム 1 行】🔵

    # 【結果返却】: 書き出しパスを str で返す (Trajectory.to_csv と同一契約) 🔵
    return str(path)
