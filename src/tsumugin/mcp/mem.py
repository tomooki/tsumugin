"""MEM 実行の M5 委譲境界 (M4→M5 実体化 / REQ-033/034/101/104 / EDGE-006/008/013)。

M4 では ``run_mem_boundary`` は委譲境界としてのみ存在し、既定 (``placeholder=False``) は
``MEMUnavailableError`` を送出、``placeholder=True`` はプレースホルダ dict を返すだけだった。
M5 (TASK-0057) では ``mem_backend`` が供給された場合に ``build_mem_input``→``mem_backend.run``
の実処理へ委譲するよう **実体化** する。M4 の placeholder 契約 (placeholder=True の dict /
mem_backend 未供給の MEMUnavailableError) は **後方互換で不変** (REQ-033)。

【非破壊 (P2/NFR-101)】: 本境界は密度マップ path・要約統計・警告のみを素の型 dict へ写し、
  親仮説/joint 結果・ledger を書き換えない。削除/上書き API を一切呼ばない。

【JSON 安全 (EDGE-013/TC-511-04)】: 密度統計・R 因子・ボンド経路長など全非有限値 (inf/-inf/NaN)
  は ``_json.finite_or_none`` で None 化し ``json.dumps(allow_nan=False)`` を安全に通す。

本モジュールは MCP SDK を一切 import しない (SDK 非依存の実処理層, D7)。``build_mem_input`` /
``MEMBackend`` はコア (numpy) のみで import でき、``import tsumugin`` に SDK/dysnomia を持ち込まない。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .._json import finite_or_none
from ..errors import MEMUnavailableError
from ..mem.base import MEMBackend, MEMResult
from ..mem.inputgen import build_mem_input
from ..model.project import Probe

if TYPE_CHECKING:  # 【循環回避】: 型注釈のみ (実行時 import しない・SDK 非依存維持) 🔵
    from .tools import AnalysisSession

__all__ = ["run_mem_boundary"]


def _resolve_probe(session: "AnalysisSession", frame_index: int | None, hist_index: int) -> Probe:
    """MEM の密度種別選択に用いる probe を session の Frame から取り出す。🔵 REQ-034

    【取得】: ``session.project`` の指定 Frame (frame_index; 未指定は 0) の
      ``histograms[hist_index].probe`` を返す。取れない (データセット/フレーム/ヒスト欠落) 場合は
      既定 "xray" へ縮退する (fail-loud せず決定論を保つ)。
    """
    fi = 0 if frame_index is None else frame_index
    for dataset in session.project.datasets:
        for frame in dataset.frames:
            if frame.index != fi:
                continue
            if 0 <= hist_index < len(frame.histograms):
                return frame.histograms[hist_index].probe
    return "xray"


def run_mem_boundary(
    session: "AnalysisSession",
    *,
    placeholder: bool = False,
    mem_backend: MEMBackend | None = None,
    hypothesis_id: str | None = None,
    frame_index: int | None = None,
    **params: object,
) -> dict:
    """M4 プレースホルダ境界を MEMBackend 委譲へ実体化する (後方互換維持)。🔵 REQ-033/034/104/EDGE-006/013

    【後方互換 (REQ-033)】: ``placeholder=True`` は M4 の
      ``{"status":"not_implemented","milestone":"M5","tool":"run_mem"}`` を返す (契約不変)。
      ``mem_backend=None`` かつ ``placeholder=False`` は従来通り ``MEMUnavailableError`` を送出する
      (M4 既定挙動不変)。
    【MEMBackend 委譲 (REQ-034/EDGE-013)】: ``mem_backend`` 供給時は対象仮説の
      ``JointRefinementResult`` (session.verification) と probe から ``build_mem_input`` を組み、
      ``mem_backend.run`` で ``MEMResult`` を得て、密度マップパス・断面・最小密度・警告を **素の型 dict**
      で返す。全非有限値は ``finite_or_none`` で None 化し ``json.dumps(allow_nan=False)`` 安全にする
      (TC-511-04)。子スナップショット追記のみで破壊操作なし (P2/NFR-101)。
    【未導入 (REQ-104/EDGE-006)】: ``mem_backend.run`` が ``MEMUnavailableError`` を送出したら捕捉し
      ``{"status":"error","error":"mem_unavailable"}`` へ変換する (クラッシュ・破壊操作なし)。M4 の
      export_gpx→GSASUnavailableError→error dict 変換パターンと対称。
    【縮退】: verification 不在・未知 hypothesis_id は素直な error dict を返す (クラッシュしない)。

    :param session: 8 ツール共通の facade。verification / project を読み取る (書き換えない)。
    :param placeholder: True で M4 プレースホルダ dict を返す (後方互換)。
    :param mem_backend: MEM ソルバ。None (既定) は placeholder=False で MEMUnavailableError 送出。
    :param hypothesis_id: MEM 対象仮説 ID。未指定は verified 先頭を使う。
    :param frame_index: probe 解決に用いる Frame index (未指定は 0)。
    :param params: 将来の MEM パラメータ (grid_shape/hist_index 等; 受理して該当のみ利用)。
    :returns: placeholder=True なら M4 dict、mem_backend 供給時は素の型 MEM 結果 dict、未導入/縮退は error dict。
    :raises MEMUnavailableError: mem_backend=None かつ placeholder=False (M4 既定挙動不変)。
    """
    # 【プレースホルダ経路 (REQ-033)】: M4 契約 dict を返す (状態変更なし) 🔵 D9
    if placeholder:
        return {"status": "not_implemented", "milestone": "M5", "tool": "run_mem"}

    # 【M4 既定経路 (REQ-033)】: mem_backend 未供給は従来通り明示送出 (破壊的操作なし) 🔵 REQ-101
    if mem_backend is None:
        raise MEMUnavailableError(
            "MEM バックエンド (最大エントロピー法) は M5 (FR-601〜606) で提供予定です。"
        )

    # 【verification 縮退】: joint 検証結果が無ければ MEM 入力を組めない (error dict・非クラッシュ) 🔵
    verification = session.verification
    if verification is None:
        return {"status": "error", "error": "no_verification"}

    # 【対象仮説の引き当て】: 未指定なら verified 先頭、指定は joint_results メンバか確認する 🔵 REQ-034
    target_id = hypothesis_id
    if target_id is None:
        if not verification.verified:
            return {"status": "error", "error": "no_verification"}
        target_id = verification.verified[0].id
    if target_id not in verification.joint_results:
        return {"status": "error", "error": "unknown_hypothesis"}
    joint_result = verification.joint_results[target_id]

    # 【probe 解決】: session の Frame から密度種別選択用 probe を取り出す (縮退時 "xray") 🔵 REQ-034
    #   【LOW-6】: 非数値 hist_index (例 "foo"/None) は素の ValueError/TypeError を出さず既定 0 へ
    #   縮退する (他の error dict / _resolve_probe の fail-soft 縮退思想と対称・クラッシュしない)。
    try:
        hist_index = int(params.get("hist_index", 0))  # type: ignore[arg-type]
    except (ValueError, TypeError):
        hist_index = 0
    probe = _resolve_probe(session, frame_index, hist_index)

    # 【委譲 (REQ-034/EDGE-013)】: build_mem_input→mem_backend.run。未導入は error dict へ変換 🔵
    mem_input = build_mem_input(joint_result, probe, hist_index=hist_index)
    try:
        result: MEMResult = mem_backend.run(mem_input)
    except MEMUnavailableError:
        # 【EDGE-006】: 未導入例外を MCP エラー dict へ変換 (クラッシュ・破壊操作なし) 🔵 REQ-104
        return {"status": "error", "error": "mem_unavailable"}

    # 【素の型 dict 化 (TC-511-04)】: 全非有限値を finite_or_none で None 化し JSON 安全にする 🔵
    return _result_to_dict(result, target_id)


def _result_to_dict(result: MEMResult, hypothesis_id: str) -> dict:
    """MEMResult を素の型 (JSON 安全) dict へ写す純関数。🔵 REQ-034/EDGE-013

    【純化】: min/max 密度・R 因子・ボンド経路の最小密度/経路長など全非有限値を
      ``finite_or_none`` で None 化し ``json.dumps(allow_nan=False)`` を安全に通す (TC-511-04)。
    【非破壊】: MEMResult は読み取るのみ (density_map は path 参照で重データを引き回さない, P2)。
    """
    density_map = result.density_map
    return {
        "status": "ok",
        "hypothesis_id": hypothesis_id,
        "density_map": {
            "path": density_map.path,
            "density_kind": density_map.density_kind,
            "min_density": finite_or_none(density_map.min_density),
            "max_density": finite_or_none(density_map.max_density),
            "grid_shape": list(density_map.grid_shape),
        },
        # 【断面】: 重い座標/値配列は引き回さずラベルのみ (要約, 非破壊) 🔵 REQ-028
        "cross_sections": [cs.label for cs in result.cross_sections],
        "bond_paths": [
            {
                "start_site": bp.start_site,
                "end_site": bp.end_site,
                "min_density": finite_or_none(bp.min_density),
                "path_length": finite_or_none(bp.path_length),
            }
            for bp in result.bond_paths
        ],
        "r_factor": finite_or_none(result.r_factor),
        "converged": bool(result.converged),
        "warnings": list(result.warnings),
    }
