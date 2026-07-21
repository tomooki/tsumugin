"""joint ベンチ (仕様 §12-6, Issue #72 後半)。

X線単独 vs SXRD+ND joint で NaCuHCF・nD2O (Prussian blue analogue) の占有率 (Na/O/Ow) ±σ を
比較し、中性子コントラスト (b: Na 3.63 / O 5.80 fm vs X線 Z: Na 11 / O 8) による占有率決定精度の
向上を定量する。

(a) X線単独 (SR SXRD λ=0.79958): model6 相当 (Ow 部分占有水を含む) で段階解放。
(b) SXRD+ND joint: 同一モデルを X線+中性子 TOF (J-PARC iMATERIA SE バンク) で同時精密化。
(c) FR-244 (``tsumugin.joint.contrast.recommend_occupancy_release``) が joint データで
    Na/O 混合サイトの占有率解放を推奨することを記録する (numpy-only, GSAS 不要)。

入力データは ``docs/benchmark/testdata/xnd/`` に配置 (README 参照, ローカル限定・非再配布)。
出力は ``docs/benchmark/joint/results/`` (occupancy_comparison.csv / rwp_summary.csv /
contrast_recommendations.txt / xray_only.gpx / joint.gpx)。

実行 (uv run python -u docs/benchmark/joint/run_joint_occupancy_bench.py) は GSAS-II の最小二乗
精密化のため決定論 (同一入力・同一 GSAS-II バージョンでビット同一)。GSAS-II 導入環境が必要
(gated テスト化はしない; README 参照)。
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from tsumugin.autorietveld.compare import metrics_from_result
from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
)
from tsumugin.evidence import BICBackend
from tsumugin.joint import (
    ContrastConfig,
    JointHistogram,
    JointRefinementModel,
    recommend_occupancy_release,
)
from tsumugin.model import LatticeParams, PhaseInstance

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
TESTDATA = REPO_ROOT / "docs" / "benchmark" / "testdata" / "xnd"
RESULTS = HERE.parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

# 混合占有サイト (占有率和=1): Na1/O3, Na2/O1。Ow はゼオライト水の単独部分占有 (和=1 制約なし)。
MIXED_OCCUPANCY_GROUPS = (("Na1", "O3"), ("Na2", "O1"))
FREE_OCCUPANCY_LABELS = ("Ow",)
SITES = ("Na1", "O3", "Na2", "O1", "Ow")

# X線精密化範囲 (interop.prepare_histograms の既定 _DEFAULT_XRAY_LIMITS と同じ)。
XRAY_LIMITS = (5.0, 78.0)
# 中性子 TOF (SE バンク) の精密化範囲 [us]。出典: imateria_D_SE_type0m_30SC_251104_700kW
# .zDiffractometer の [Global fitting range][Peak position] Min/Max (ビームタイム実測、
# 生ファイルは非再配布のため値のみ転記; docs/benchmark/README.md 参照)。
ND_LIMITS = (5142.0, 70900.0)

# 背景 18 項 + 格子 + プロファイル + 占有率の 4 段 (PR #35 nacuhcf_joint_analysis.py の焦点レシピと
# 同一: joint model6 相当で ~7分/変種で占有率解放まで到達する既知良好レシピ)。
RECIPE = [
    RefinementStage("bg", {"background": {"coeffs": 18}}),
    RefinementStage("cell", {"cell": True}),
    RefinementStage("prof", {"profile": True}),
    RefinementStage("occ", {"occupancy": True}),
]


def xray_histogram() -> HistogramSpec:
    return HistogramSpec(
        data_path=str(TESTDATA / "xray.xye"),
        instrument_path=str(TESTDATA / "xray.instprm"),
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="XYE",
        two_theta_limits=XRAY_LIMITS,
    )


def nd_histogram() -> HistogramSpec:
    return HistogramSpec(
        data_path=str(TESTDATA / "nd.fxye"),
        instrument_path=str(TESTDATA / "nd.instprm"),
        radiation=Radiation.NEUTRON_TOF,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="GSAS",
        two_theta_limits=ND_LIMITS,
    )


def model6_phase() -> PhaseSpec:
    return PhaseSpec(
        structure_path=str(TESTDATA / "model6.cif"),
        phase_name="NaCuHCF",
        mixed_occupancy_groups=MIXED_OCCUPANCY_GROUPS,
        free_occupancy_labels=FREE_OCCUPANCY_LABELS,
    )


def extract_occupancy_esd(gpx_path: str, labels: Sequence[str]) -> dict[str, tuple[float, float]]:
    """精密化済み gpx から {label: (occupancy, esd)} を読む。

    esd は GSAS-II の共分散行列由来 (``G2Phase.get_cell_and_esd`` と同型の抽出: varyList の
    sig を直に採り、和=1/等値制約で従属化した変数 [混合占有サイトの Afrac] は
    ``GSASIImapvars.ComputeDepESD`` で共分散から逆算する)。単独解放 (Ow) は varyList に直接
    現れるため sig をそのまま使う。
    """
    from GSASII import GSASIImapvars as G2mv
    from GSASII import GSASIIscriptable as G2sc

    gpx = G2sc.G2Project(gpx_path)
    ph = gpx.phases()[0]
    cx, ct, _cs, _cia = ph.data["General"]["AtomPtrs"]
    pid = str(ph.id)

    cov = gpx.data["Covariance"]["data"]
    sig_dict = dict(zip(cov.get("varyList", []), cov.get("sig", [])))
    if cov.get("covMatrix") is not None:
        sig_dict.update(G2mv.ComputeDepESD(cov["covMatrix"], cov["varyList"]))

    labels_set = set(labels)
    out: dict[str, tuple[float, float]] = {}
    for i, row in enumerate(ph.data["Atoms"]):
        label = row[ct - 1]
        if label in labels_set:
            occ = float(row[cx + 3])
            esd = float(sig_dict.get(f"{pid}::Afrac:{i}", 0.0))
            out[label] = (occ, esd)
    return out


def run_mode(name: str, histograms: Sequence[HistogramSpec], keep_gpx: Path) -> dict[str, object]:
    t0 = time.time()
    result: AutoRietveldResult = run_auto_rietveld(
        list(histograms),
        [model6_phase()],
        recipe=RECIPE,
        max_cyc=2,
        keep_gpx=str(keep_gpx),
    )
    dt = time.time() - t0
    metrics = metrics_from_result(result)
    bic = BICBackend().score(metrics).value
    occ = extract_occupancy_esd(str(keep_gpx), SITES)

    print(f"\n===== {name} dt={dt:.0f}s =====")
    print(
        f"  Rwp={result.final_rwp:.3f}%  GOF={result.final_gof:.3f}  n_obs={metrics.n_obs}  "
        f"n_params={metrics.n_params}  BIC={bic:.1f}  validity={result.validity.passed}"
    )
    for lab in SITES:
        if lab in occ:
            v, e = occ[lab]
            print(f"    {lab:4s} occ={v:.4f} +/- {e:.4f}")

    return {
        "name": name,
        "rwp": float(result.final_rwp),
        "gof": float(result.final_gof),
        "n_obs": metrics.n_obs,
        "n_params": metrics.n_params,
        "bic": float(bic),
        "validity": result.validity.passed,
        "dt_s": dt,
        "occ": occ,
    }


def demo_contrast_recommendation() -> tuple[tuple, tuple]:
    """FR-244: joint データで Na/O 混合サイトの占有率解放が推奨されることを記録する (numpy-only)。"""
    grid = np.arange(15.0, 80.0, 0.5)

    def hist(probe: str) -> JointHistogram:
        return JointHistogram(two_theta=grid, intensity=np.ones_like(grid), probe=probe)

    phase = PhaseInstance(
        phase_ref="NaCuHCF",
        lattice=LatticeParams(6.95024, 7.29076, 12.83917, beta=119.6595),
        occupancies={"Na1_O3": 0.24, "Na2_O1": 0.75},
    )
    config = ContrastConfig(site_elements={"Na1_O3": ("Na", "O"), "Na2_O1": ("Na", "O")})

    joint_model = JointRefinementModel(
        phases=(phase,), histograms=(hist("xray"), hist("neutron_tof"))
    )
    joint_recs = recommend_occupancy_release((phase,), joint_model, config=config)

    xray_only_model = JointRefinementModel(phases=(phase,), histograms=(hist("xray"),))
    xray_recs = recommend_occupancy_release((phase,), xray_only_model, config=config)

    lines = [
        "FR-244 recommend_occupancy_release 発火確認 (NaCuHCF Na/O 混合サイト)",
        "",
        f"joint (xray+neutron_tof): {len(joint_recs)} 件推奨",
    ]
    for r in joint_recs:
        lines.append(
            f"  site={r.site} elements={r.elements} contrast={r.contrast:.4f}"
            f" param={r.param_name}"
        )
        lines.append(f"    rationale: {r.rationale}")
    lines.append(
        f"xray-only (probe 種別 1 種): {len(xray_recs)} 件推奨 "
        "(joint 条件 [hist>=2 かつ probe 種別>=2] 未達のため空を期待)"
    )
    text = "\n".join(lines)
    print("=== FR-244 contrast-driven occupancy release recommendation ===")
    print(text)
    (RESULTS / "contrast_recommendations.txt").write_text(text + "\n", encoding="utf-8")
    return joint_recs, xray_recs


def write_occupancy_csv(
    xray_result: Mapping[str, object], joint_result: Mapping[str, object]
) -> Path:
    csv_path = RESULTS / "occupancy_comparison.csv"
    xray_occ: dict[str, tuple[float, float]] = xray_result["occ"]  # type: ignore[assignment]
    joint_occ: dict[str, tuple[float, float]] = joint_result["occ"]  # type: ignore[assignment]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["site", "xray_value", "xray_esd", "joint_value", "joint_esd", "esd_ratio"])
        for lab in SITES:
            xv, xe = xray_occ.get(lab, (float("nan"), float("nan")))
            jv, je = joint_occ.get(lab, (float("nan"), float("nan")))
            ratio = je / xe if xe == xe and xe != 0.0 else float("nan")
            w.writerow(
                [
                    lab,
                    f"{xv:.6f}",
                    f"{xe:.6f}",
                    f"{jv:.6f}",
                    f"{je:.6f}",
                    f"{ratio:.4f}" if ratio == ratio else "nan",
                ]
            )
    return csv_path


def write_rwp_summary(*results: Mapping[str, object]) -> Path:
    summary_path = RESULTS / "rwp_summary.csv"
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["mode", "rwp_pct", "gof", "n_obs", "n_params", "bic", "validity", "dt_s"])
        for r in results:
            w.writerow(
                [
                    r["name"],
                    f"{r['rwp']:.4f}",
                    f"{r['gof']:.4f}",
                    r["n_obs"],
                    r["n_params"],
                    f"{r['bic']:.2f}",
                    r["validity"],
                    f"{r['dt_s']:.1f}",
                ]
            )
    return summary_path


def main() -> None:
    demo_contrast_recommendation()

    print("\n=== (a) X-ray only (model6, Na/Ow occupancy release) ===")
    xray_result = run_mode("xray_only", [xray_histogram()], RESULTS / "xray_only.gpx")

    print("\n=== (b) SXRD + ND TOF joint (model6, Na/Ow occupancy release) ===")
    joint_result = run_mode(
        "joint", [xray_histogram(), nd_histogram()], RESULTS / "joint.gpx"
    )

    csv_path = write_occupancy_csv(xray_result, joint_result)
    summary_path = write_rwp_summary(xray_result, joint_result)

    print(f"\nwrote {csv_path}")
    print(f"wrote {summary_path}")


if __name__ == "__main__":
    main()
