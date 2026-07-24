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
from typing import Mapping, Sequence

import numpy as np

from .._json import finite_or_none
from ..errors import GSASUnavailableError
from ..model import LatticeParams, PhaseInstance, SigmaSource
from ..model import strip_lattice_sigma as _strip_sigma
from .base import RefinementModel, RefinementResult, parse_param

_DEFAULT_WAVELENGTH = 1.5406  # Cu Kα1 (Å)

# 【セル辞書キー】: get_cell()/get_cell_and_esd() が返す格子 6 成分のキー (読み戻し検証用) 🔵
_CELL_KEYS = (
    "length_a",
    "length_b",
    "length_c",
    "angle_alpha",
    "angle_beta",
    "angle_gamma",
)


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


def _apply_cell(g2ph, lattice: LatticeParams) -> None:
    """実 CIF から読んだ相の単位胞を warm-start 格子へ上書きする (Issue #130)。

    ``add_phase`` が実構造 (原子/空間群) を保持したまま、``General.Cell`` の 6 定数と体積のみを
    ``lattice`` へ置換する (GSAS-II 自身が ``add_phase(cell=...)`` で行う操作と同じ; L1423-1424)。
    格子解放時の精密化は空間群の対称拘束を尊重するため、CIF の対称と整合する格子を渡すこと
    (discrimination は端成分で phase_ref=構造を共有し a/b/c のみ解放するので整合する)。
    """
    from GSASII import GSASIIlattice as G2lat  # noqa: PLC0415 (遅延 import)

    cell = [lattice.a, lattice.b, lattice.c, lattice.alpha, lattice.beta, lattice.gamma]
    g2ph.data["General"]["Cell"][1:7] = cell
    g2ph.data["General"]["Cell"][7] = G2lat.calc_V(G2lat.cell2A(cell))


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
                # 【σ 素通り防止 (レビュー対応)】: model.phases に残る古い σ をそのまま返すと
                # chi2=inf の仮説に σ が付いて見えてしまうため _strip_sigma で剥離する 🔵
                return RefinementResult(
                    phases=_strip_sigma(model.phases),
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

            new_phases = self._read_back(g2phases, hist, model.phases, cell_free)

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
            if phase.structure_ref is not None:
                # 【実 CIF 分岐 (Issue #130)】: 実結晶構造 (原子/空間群/参照セル) を読み、
                #   格子だけ warm-start 値へ上書きする (discrimination の格子解放を反映)。
                g2ph = gpx.add_phase(
                    str(phase.structure_ref),
                    phasename=f"phase{i}",
                    histograms=[hist],
                    fmthint="CIF",
                )
                _apply_cell(g2ph, phase.lattice)
            else:
                # 【従来フォールバック】: structure_ref なしはプレースホルダ CIF (格子/scale 判別)。
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
        self,
        g2phases,
        hist,
        originals: tuple[PhaseInstance, ...],
        cell_free: set[int],
    ) -> tuple[PhaseInstance, ...]:
        """精密化済み格子/scale を読み戻す。

        【σ セマンティクス (統一定義)】: ``lattice.sigma``/``sigma_source`` は「当該 refine()
        呼び出しで推定した不確かさのみ」を表す。格子を解放した相のみ ``get_cell_and_esd()``
        の共分散由来 esd を新 dict として与え、非解放相は sigma={} / sigma_source="" とする
        (入力に古い σ が残っていても持ち越さない。SimulatedBackend と対称)。
        【効率化】: 格子解放相は ``get_cell_and_esd()`` の cell 戻り値を再利用し、
        ``get_cell()`` の二重呼び出しを避ける (取得失敗時のみ get_cell へフォールバック)。
        """
        out: list[PhaseInstance] = []
        for i, (g2ph, orig) in enumerate(zip(g2phases, originals)):
            cell: Mapping[str, float] | None = None
            sigma: dict[str, float] = {}
            sigma_source: SigmaSource = ""
            if i in cell_free:
                # 【共分散由来 σ + cell 再利用】: 格子解放相は get_cell_and_esd() 一発 (REQ-306) 🔵
                cell, sigma, sigma_source = self._cell_sigma(g2ph)
            if cell is None:
                # 【フォールバック】: 非解放相の従来経路 / esd 取得失敗時 🔵
                cell = g2ph.get_cell()
            lattice = LatticeParams(
                a=float(cell["length_a"]),
                b=float(cell["length_b"]),
                c=float(cell["length_c"]),
                alpha=float(cell["angle_alpha"]),
                beta=float(cell["angle_beta"]),
                gamma=float(cell["angle_gamma"]),
                sigma=sigma,
                sigma_source=sigma_source,
            )
            scale = float(g2ph.getHAPvalues(hist)["Scale"][0])
            out.append(orig.with_updates(lattice=lattice, scale=scale))
        return tuple(out)

    def _cell_sigma(
        self, g2ph
    ) -> tuple[dict[str, float] | None, dict[str, float], SigmaSource]:
        """精密化済み格子と共分散由来 esd (a/b/c) を ``get_cell_and_esd()`` から取得する。

        【機能概要】: GSAS-II の共分散行列由来の真の格子 esd を sigma_source="covariance" で
        返す (FR-306/NFR-107)。cell 戻り値も検証済み dict として返し、呼び出し側の
        ``get_cell()`` 二重呼び出しを不要にする。GSAS-II 側 API は共分散欠如時 ``KeyError``
        を自前で吸収して esd=0.0 の dict へ縮退させる実装のため、0.0/非有限は「取得不能」
        として除外する (非有限判定は ``_json.finite_or_none`` の単一実装へ委譲)。
        【設計方針 (レビュー対応, ラウンド2)】: try スコープを 2 段に分割する。外側 try は
        ``get_cell_and_esd()`` 呼び出しと cell 6 成分の float 化のみを担い、失敗時は
        (None, {}, "") へ縮退する (cell 自体が取得不能)。内側 try は esd 抽出のみを担い、
        失敗しても**検証済み cell は活かす** (cell, {}, "") へ縮退する。旧実装は 1 つの try で
        両方を包んでいたため、cell 検証に成功していても esd 側の例外 (戻り値形状異常等) で
        cell まで巻き添えに捨てて呼び出し側が ``get_cell()`` を再呼び出しする無駄が生じていた。
        いずれの縮退も fail-loud しない (「精密化バックエンドの失敗は chi2=inf へ変換し
        ガードレールに処理させる」不変条件と同趣旨、σ 取得は精密化成否そのものではないため
        例外を上げず黙って未提供とする)。
        :returns: (検証済み cell dict | None, sigma dict, sigma_source)。cell=None は取得不能
        (呼び出し側が get_cell() へフォールバックする)。
        🟡 信頼性レベル: GSASIIscriptable.G2Phase.get_cell_and_esd() 実装 (KeyError→0.0 縮退) に依拠。
        """
        try:
            raw_cell, esd = g2ph.get_cell_and_esd()
            # 【cell 検証】: 6 成分を float 化して形状を検証 (失敗は except で縮退) 🔵
            cell = {key: float(raw_cell[key]) for key in _CELL_KEYS}
        except Exception:
            return None, {}, ""

        sigma: dict[str, float] = {}
        try:
            for attr, key in (("a", "length_a"), ("b", "length_b"), ("c", "length_c")):
                value = finite_or_none(esd.get(key))
                if value is not None and value > 0.0:
                    sigma[attr] = value
        except Exception:
            # 【esd 抽出のみ失敗】: 検証済み cell は捨てず活かす (呼び出し側の get_cell() 二重
            #   呼び出しを回避, レビュー対応) 🔵
            return cell, {}, ""

        if not sigma:
            return cell, {}, ""
        return cell, sigma, "covariance"
