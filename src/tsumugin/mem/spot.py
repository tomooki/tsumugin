"""MEM フレームスポット解析 (M5 / REQ-032/405 / FR-606)。

シーケンシャル (operando / 高温) の **指定単一フレーム** (充電端 / 放電端 / 転移前後) の
joint 検証済み仮説に対して MEM をスポット実行する。全フレーム自動反復はしない (spot 単位で完結)。

【スポット (REQ-032/405)】``frame_index`` で指定した 1 フレームのみ処理し、MEMBackend.run は
  1 回だけ呼ぶ (全フレーム反復禁止)。

【適用ガード (REQ-031)】``check_mem_applicability`` の警告を ``MEMResult.warnings`` に伝播する
  (推奨条件を満たさなくても実行を止めない・仮説除外もしない, Dara 教訓)。

【非破壊 (P2)】``FrameSeries`` / ``JointVerificationResult`` を改変しない。ledger 非 None のとき
  スポット実行を追記記録するのみ (verify() True 維持)。
"""

from __future__ import annotations

from dataclasses import replace

from ..backends.base import RefinementBackend
from ..joint.verification import JointVerificationResult
from ..model.project import Probe
from ..sequential.series import FrameSeries
from ..store.ledger import Ledger
from .base import MEMBackend, MEMResult
from .guard import check_mem_applicability
from .inputgen import build_mem_input


def run_mem_spot(
    backend: RefinementBackend,
    mem_backend: MEMBackend,
    series: FrameSeries,
    verification: JointVerificationResult,
    hypothesis_id: str,
    frame_index: int,
    probe: Probe,
    *,
    grid_shape: tuple[int, int, int] = (64, 64, 64),
    ledger: Ledger | None = None,
) -> MEMResult:
    """シーケンシャルの指定フレーム (充電端/放電端/転移前後) に MEM をスポット実行する。🔵 REQ-032/FR-606

    【スポット (REQ-032/405)】: frame_index で指定した単一フレームの joint 検証済み仮説に対して MEM を
      実行する。全フレーム自動反復はしない (spot 単位で完結, REQ-405)。MEMBackend.run は 1 回のみ。
    【適用ガード】: check_mem_applicability の警告を MEMResult.warnings に伝播する (除外しない, REQ-031)。
    """
    # 【フレーム範囲検証】: 器の契約違反 (範囲外) は fail-loud で弾く (縮退しない)。
    if not (0 <= frame_index < series.n_frames):
        raise ValueError(
            f"frame_index {frame_index} が範囲外です (0..{series.n_frames - 1})。"
        )

    # 【適用ガード (REQ-031)】: 推奨条件を判定するが実行は止めない・仮説除外もしない (Dara 教訓)。
    report = check_mem_applicability(verification, hypothesis_id)

    # 【MEM 入力生成】: 該当仮説の joint 検証結果から MEM 入力を組む (指定フレームのスポット)。
    joint_result = verification.joint_results[hypothesis_id]
    mem_input = build_mem_input(joint_result, probe, grid_shape=grid_shape)

    if ledger is not None:
        ledger.append(
            "mem_spot_start",
            {
                "hypothesis_id": hypothesis_id,
                "frame_index": frame_index,
                "recommended": report.recommended,
                "n_guard_warnings": len(report.warnings),
            },
        )

    # 【スポット実行 (1 フレームのみ)】: MEMBackend.run は 1 回だけ呼ぶ (全フレーム反復しない)。
    mem_result = mem_backend.run(mem_input)

    # 【ガード警告の伝播 (REQ-031)】: guard 警告を MEMResult.warnings に非破壊で足す (除外はしない)。
    merged_warnings = tuple(mem_result.warnings) + report.warnings
    if merged_warnings != tuple(mem_result.warnings):
        mem_result = replace(mem_result, warnings=merged_warnings)

    if ledger is not None:
        ledger.append(
            "mem_spot_done",
            {
                "hypothesis_id": hypothesis_id,
                "frame_index": frame_index,
                "n_warnings": len(mem_result.warnings),
            },
        )

    return mem_result
