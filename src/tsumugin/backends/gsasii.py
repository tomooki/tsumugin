"""GSAS-II (GSASIIscriptable) バックエンド (仕様 §3.1)。

RefinementModel を一時 .gpx プロジェクトへ変換して GSAS-II の Rietveld 精密化を実行する。
GSAS-II 2.x のパッケージ構成 (`GSASII.GSASIIscriptable`) を前提とし、未導入環境では
明示的に無効化する。import は関数内で遅延させ、未導入環境でモジュール収集が失敗しない。

M1 で認識するパラメータ: "scale" (相分率 HAP Scale), "lattice.*" (単位胞、対称性の許す
自由度をまとめて解放)。その他の suffix (profile/texture 等) は no-op で無視される。

構造モデルの簡約 (M0/M1): 各相は空間群 P m m m (直方晶)・原点に Ni 1 原子として CIF 化する。
SimulatedBackend の直方 d 間隔模型と整合し、格子 a/b/c を個別に識別できる。
"""

from __future__ import annotations

import importlib.util
import math
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import numpy as np

from ..errors import GSASUnavailableError
from ..model import LatticeParams, PhaseInstance
from .base import RefinementModel, RefinementResult, parse_param

_DEFAULT_WAVELENGTH = 1.5406  # Cu Kα1 (Å)


@lru_cache(maxsize=1)
def gsasii_available() -> bool:
    """GSASII.GSASIIscriptable が import 可能か (バイナリ含め) を判定する。

    パッケージ不在なら find_spec の時点で False (副作用なし)。存在する場合のみ
    実 import を試み、コンパイル済みバイナリの解決まで含めて検証する。
    """
    try:
        if importlib.util.find_spec("GSASII") is None:
            return False
    except (ImportError, ValueError):
        return False
    try:
        from GSASII import GSASIIscriptable  # noqa: F401

        return True
    except Exception:
        return False


def _g2sc():
    """遅延 import + 出力抑制済みの GSASIIscriptable モジュールを返す。"""
    from GSASII import GSASIIscriptable as G2sc

    try:
        G2sc.SetPrintLevel("none")
    except Exception:
        pass
    return G2sc


def _write_instprm(path: Path, wavelength: float) -> None:
    lines = [
        "#GSAS-II instrument parameter file; created by tsumugin",
        "Type:PXC",
        "Bank:1.0",
        f"Lam:{wavelength}",
        "Polariz.:0.7",
        "Azimuth:0.0",
        "Zero:0.0",
        "U:2.0",
        "V:-2.0",
        "W:5.0",
        "X:0.0",
        "Y:0.0",
        "Z:0.0",
        "SH/L:0.002",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_xye(
    path: Path,
    two_theta: np.ndarray,
    intensity: np.ndarray,
    weights: np.ndarray | None,
) -> None:
    if weights is not None:
        esd = 1.0 / np.sqrt(np.maximum(weights, 1e-12))
    else:
        esd = np.sqrt(np.maximum(intensity, 1.0))
    rows = "\n".join(
        f"{t:.6f} {y:.8g} {e:.8g}" for t, y, e in zip(two_theta, intensity, esd)
    )
    path.write_text(rows + "\n", encoding="utf-8")


def _write_cif(path: Path, name: str, lattice: LatticeParams) -> None:
    """P m m m・Ni 1 原子の簡約 CIF を書き出す (モジュール docstring 参照)。"""
    cif = f"""data_{name}
_space_group_name_H-M_alt 'P m m m'
_symmetry_space_group_name_H-M 'P m m m'
_cell_length_a {lattice.a}
_cell_length_b {lattice.b}
_cell_length_c {lattice.c}
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_adp_type
_atom_site_U_iso_or_equiv
Ni1 Ni 0.0 0.0 0.0 1.0 Uiso 0.01
"""
    path.write_text(cif, encoding="utf-8")


class GSASIIBackend:
    """RefinementBackend の GSAS-II 実装。

    吸収補正 (absorption) について: v1 では透過平板の実効 μt を独立パラメータとしては
    精密化せず、吸収による強度歪みを scale (相分率スケール) への畳み込み近似として吸収させる
    (REQ-020 / architecture.md D8 L101)。実効 μt を 1 パラメータとして陽に精密化する
    restraint 付き吸収補正は SimulatedBackend (AbsorptionConfig) 側で提供する。GSAS-II 側の
    厳密な吸収モデル (Sample Parameters の Absorption) 連携は将来タスクで扱う。
    """

    name = "gsasii"

    def __init__(self, *, wavelength: float = _DEFAULT_WAVELENGTH) -> None:
        if not gsasii_available():
            raise GSASUnavailableError(
                "GSASII.GSASIIscriptable が見つかりません。GSAS-II を導入するか "
                "SimulatedBackend を使用してください (導入手順は README 参照)。"
            )
        self.wavelength = float(wavelength)

    # ---- 前方モデル -----------------------------------------------------

    def simulate(
        self, phases: Sequence[PhaseInstance], two_theta: np.ndarray
    ) -> np.ndarray:
        """GSAS-II のパターン計算で強度を生成する (noise-free の Ycalc)。"""
        G2sc = _g2sc()
        two_theta = np.asarray(two_theta, dtype=float)
        tstep = float(two_theta[1] - two_theta[0])
        with tempfile.TemporaryDirectory(prefix="tsumugin-g2sim-") as tmp:
            tmp_path = Path(tmp)
            instprm = tmp_path / "inst.instprm"
            _write_instprm(instprm, self.wavelength)
            gpx = G2sc.G2Project(newgpx=str(tmp_path / "sim.gpx"))
            hist = gpx.add_simulated_powder_histogram(
                "tsumugin simulation",
                str(instprm),
                float(two_theta[0]),
                float(two_theta[-1]),
                Tstep=tstep,
            )
            self._add_phases(gpx, hist, phases, tmp_path)
            gpx.data["Controls"]["data"]["max cyc"] = 0
            gpx.do_refinements([{}])
            x = np.asarray(hist.getdata("X"), dtype=float)
            ycalc = np.asarray(hist.getdata("Ycalc"), dtype=float)
        return np.interp(two_theta, x, ycalc)

    # ---- 精密化 ---------------------------------------------------------

    def refine(
        self, model: RefinementModel, *, max_cycles: int = 20
    ) -> RefinementResult:
        two_theta = np.asarray(model.two_theta, dtype=float)
        intensity = np.asarray(model.intensity, dtype=float)

        scale_free, cell_free = self._recognized(model.free_params, len(model.phases))
        any_free = bool(scale_free or cell_free)

        with tempfile.TemporaryDirectory(prefix="tsumugin-g2ref-") as tmp:
            tmp_path = Path(tmp)
            # 【gpx 構築】: 共有ヘルパで instprm/xye 書き出し + 観測ヒストグラム/全相追加を行う。
            # 一時 refine.gpx を生成し、精密化フラグ設定・読み戻しは本メソッドで続ける 🔵
            gpx, hist, g2phases = self._build_project(
                tmp_path / "refine.gpx",
                tmp_path,
                model.phases,
                two_theta,
                intensity,
                model.weights,
            )

            for i, g2ph in enumerate(g2phases):
                if i in cell_free:
                    g2ph.set_refinements({"Cell": True})
                if i in scale_free:
                    g2ph.set_HAP_refinements({"Scale": True}, histograms=[hist])

            gpx.data["Controls"]["data"]["max cyc"] = max_cycles if any_free else 0
            try:
                gpx.do_refinements([{}])
            except Exception:
                # 最小二乗の失敗は発散として表現し、ガードレール側で処理させる。
                return RefinementResult(
                    phases=model.phases,
                    chi2=float("inf"),
                    rwp=float("inf"),
                    n_obs=int(intensity.size),
                    n_params=0,
                    converged=False,
                    n_cycles=max_cycles,
                    free_params=model.free_params,
                )

            x, yobs, w, ycalc = (
                np.asarray(a, dtype=float) for a in hist.data["data"][1][:4]
            )
            chi2 = float(np.sum(w * (yobs - ycalc) ** 2))
            denom = float(np.sum(w * yobs**2))
            rwp = 100.0 * math.sqrt(chi2 / denom) if denom > 0 else 0.0

            cov = gpx.data["Covariance"]["data"]
            rvals = cov.get("Rvals", {})
            vary_list = cov.get("varyList", [])
            converged = bool(rvals.get("converged", True)) if any_free else True

            new_phases = self._read_back(g2phases, hist, model.phases)

        return RefinementResult(
            phases=new_phases,
            chi2=chi2,
            rwp=rwp,
            n_obs=int(x.size),
            n_params=len(vary_list),
            converged=converged,
            n_cycles=max_cycles if any_free else 1,
            free_params=model.free_params,
        )

    # ---- 内部ヘルパ -----------------------------------------------------

    def _build_project(
        self,
        gpx_path: Path,
        work_dir: Path,
        phases: Sequence[PhaseInstance],
        two_theta: np.ndarray,
        intensity: np.ndarray,
        weights: np.ndarray | None,
    ) -> tuple[object, object, list[object]]:
        """観測データ入り GSAS-II プロジェクトを構築する共有ヘルパ (D-Q8 単一情報源)。

        【責務】: 補助ファイル (instprm/xye) の書き出しから gpx_path への G2Project 生成、
        観測ヒストグラム追加、全相追加までを担う。精密化フラグ設定・do_refinements・保存・
        読み戻しといった用途固有の処理は呼び出し側 (refine / export_gpx) の責務とする。
        🔵 信頼性レベル: 要件定義 §2.3 / note §3.1 の推奨シグネチャに準拠

        :param gpx_path: 生成する .gpx のパス (refine は一時、export_gpx は永続)
        :param work_dir: instprm/xye/cif を置く作業ディレクトリ
        :param phases: gpx に追加する相集合
        :param two_theta: 観測 2θ グリッド
        :param intensity: 観測強度 (Yobs としてヒストグラムに埋め込む)
        :param weights: 観測重み。None なら _write_xye の統計重み既定
        :returns: (gpx, hist, g2phases) — 呼び出し側が用途固有処理を続けるためのハンドル
        """
        G2sc = _g2sc()
        # 【補助ファイル書き出し】: 装置パラメータと観測パターンを作業ディレクトリへ置く 🔵
        instprm = work_dir / "inst.instprm"
        datafile = work_dir / "pattern.xye"
        _write_instprm(instprm, self.wavelength)
        _write_xye(datafile, two_theta, intensity, weights)

        # 【プロジェクト構築】: gpx 生成 → 観測ヒストグラム追加 → 全相追加 🔵
        gpx = G2sc.G2Project(newgpx=str(gpx_path))
        hist = gpx.add_powder_histogram(str(datafile), str(instprm))
        g2phases = self._add_phases(gpx, hist, phases, work_dir)
        return gpx, hist, g2phases

    def _recognized(
        self, free_params: frozenset[str], n_phases: int
    ) -> tuple[set[int], set[int]]:
        """free_params を (scale 解放相, 格子解放相) のインデックス集合へ変換。"""
        scale_free: set[int] = set()
        cell_free: set[int] = set()
        for name in free_params:
            idx, key = parse_param(name)
            if idx >= n_phases:
                continue
            if key == "scale":
                scale_free.add(idx)
            elif key.startswith("lattice."):
                cell_free.add(idx)
        return scale_free, cell_free

    def _add_phases(self, gpx, hist, phases: Sequence[PhaseInstance], tmp_path: Path):
        g2phases = []
        for i, phase in enumerate(phases):
            cif = tmp_path / f"phase{i}.cif"
            _write_cif(cif, f"phase{i}", phase.lattice)
            g2ph = gpx.add_phase(
                str(cif), phasename=f"phase{i}", histograms=[hist], fmthint="CIF"
            )
            hap = g2ph.getHAPvalues(hist)
            hap["Scale"][0] = float(phase.scale)
            g2phases.append(g2ph)
        return g2phases

    def _read_back(
        self, g2phases, hist, originals: tuple[PhaseInstance, ...]
    ) -> tuple[PhaseInstance, ...]:
        out: list[PhaseInstance] = []
        for g2ph, orig in zip(g2phases, originals):
            cell = g2ph.get_cell()
            lattice = LatticeParams(
                a=float(cell["length_a"]),
                b=float(cell["length_b"]),
                c=float(cell["length_c"]),
                alpha=float(cell["angle_alpha"]),
                beta=float(cell["angle_beta"]),
                gamma=float(cell["angle_gamma"]),
            )
            scale = float(g2ph.getHAPvalues(hist)["Scale"][0])
            out.append(orig.with_updates(lattice=lattice, scale=scale))
        return tuple(out)
