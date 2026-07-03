""".gpx 書き出し export_gpx (REQ-006 / FR-505 / 設計 D5)。

任意時点の相集合と観測パターンを GSAS-II GUI (GSASIIscriptable) で再オープン可能な
.gpx プロジェクトとしてユーザ指定の永続パスへ書き出す。gpx 構築は GSASIIBackend の
共有ヘルパ _build_project() (D-Q8 単一情報源) を再利用する薄い書き出し層。
GSAS-II 未導入環境では書き出し前に GSASUnavailableError を送出する (REQ-105)。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Sequence

import numpy as np

from ..backends.gsasii import _DEFAULT_WAVELENGTH, GSASIIBackend
from ..model import PhaseInstance

__all__ = ["export_gpx"]


def export_gpx(
    path: str,
    phases: Sequence[PhaseInstance],
    two_theta: np.ndarray,
    intensity: np.ndarray,
    *,
    weights: np.ndarray | None = None,
    wavelength: float = _DEFAULT_WAVELENGTH,
) -> str:
    """GSAS-II GUI で開ける .gpx を書き出し、書き出したパスを返す。

    【機能概要】: phases + 観測パターン (two_theta, intensity) からヒストグラム・全相・
    計算パターン (Ycalc) 込みの .gpx を永続 path へ生成する (REQ-006 / FR-505)。
    【実装方針】: GSASIIBackend._build_project() を永続パスで実行し、max cyc=0 の
    do_refinements で Ycalc を埋め込んでから save() する (設計 D5 / 要件定義 §2.3)。
    🔵 信頼性レベル: interfaces.py の export_gpx 契約 (L207-218) に準拠

    :param path: 出力 .gpx パス (永続)。戻り値と一致する 🔵
    :param phases: 書き出す相集合 (空でない Sequence[PhaseInstance]) 🔵
    :param two_theta: 観測 2θ グリッド (intensity と同長) 🔵
    :param intensity: 観測強度 (Yobs としてヒストグラムに埋め込む) 🔵
    :param weights: 観測重み。None なら統計重み (既存 _write_xye の既定挙動) 🔵
    :param wavelength: 波長 (Å)。instprm の Lam: に反映 (既定は Cu Kα1 = 1.5406) 🔵
    :returns: 書き出しに成功した .gpx の永続パス (str)
    :raises GSASUnavailableError: GSAS-II 未導入時 (書き出し処理前に副作用ゼロで送出) 🔵
    """
    # 【未導入判定】: GSASIIBackend.__init__ が gsasii_available() False で
    # GSASUnavailableError を送出する既存経路を利用。ファイル書き出しに入る前の
    # 早期 raise であり副作用ゼロ (REQ-105 / TC-006-03 / TC-006-08) 🔵
    backend = GSASIIBackend(wavelength=wavelength)

    # 【入力正規化】: refine と同様に float ndarray へ揃える 🔵
    two_theta = np.asarray(two_theta, dtype=float)
    intensity = np.asarray(intensity, dtype=float)

    # 【一時/永続の分離】: instprm/xye/cif は一時作業ディレクトリ、gpx 本体だけ永続 path に
    # 置く (要件定義 §3.4)。save() を with ブロック内で完了させ、補助ファイル消滅後も
    # 再オープン可能な自己完結 .gpx を保証する (TC-006-10) 🔵
    with tempfile.TemporaryDirectory(prefix="tsumugin-g2exp-") as tmp:
        work_dir = Path(tmp)
        gpx, _hist, _g2phases = backend._build_project(
            Path(path), work_dir, phases, two_theta, intensity, weights
        )
        # 【Ycalc 埋め込み】: max cyc=0 → do_refinements([{}]) で計算パターンを 1 度計算して
        # から保存する (simulate/refine と同じ手法。要件定義 §3.5 / TC-006-05) 🔵
        gpx.data["Controls"]["data"]["max cyc"] = 0
        gpx.do_refinements([{}])
        # 【永続化】: 永続 path へ確定保存 (TC-006-01 / TC-006-04) 🔵
        gpx.save()

    # 【結果返却】: 書き出しパスを str で返す (戻り値契約 §2.2) 🔵
    return str(path)
