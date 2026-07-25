"""実プロジェクト境界 — JSON spec ロード + 検証 + 精密化前プレビュー
(`docs/design/gui-workbench/architecture.md` §バックエンド `project.py`)。

spec の ``histograms``/``phases`` は ② ``auto_rietveld`` MCP ツールと同一 JSON スキーマ
(``HistogramSpec``/``PhaseSpec.from_dict``) を再利用する (REQ-GUI-012, §4.5 到達可能性)。
相対パス (``data_path``/``instrument_path``/``structure_path``) は spec ファイルのディレクトリ
基準で絶対化する。GSAS-II が直接読めない形式 (XRDML 等) はロード時に ``reference.io`` で読んで
XYE へ自己変換する (M9 ``insitu.engine.make_gsas_runner`` の先例を踏襲)。

numpy 使用可 (``reference.io`` 経由の観測データ読み込み) だが、返り値は素の型 (list/float) のみ。
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ..autorietveld.model import HistogramSpec, PhaseSpec
from ..reference.io import load_pattern

__all__ = ["WorkbenchProject", "load_project_spec", "preview_pattern"]

_MAX_PREVIEW_POINTS = 2000


@dataclasses.dataclass(frozen=True)
class WorkbenchProject:
    """実プロジェクト spec のロード結果 (frozen)。

    相対パスは spec ディレクトリ基準で絶対化済み、XRDML ヒストグラムは XYE へ自己変換済み
    (``histograms`` はそのまま ``run_auto_rietveld`` に渡せる形)。

    :param name: プロジェクト名 (GET /api/state の ``project.name``)
    :param histograms: 絶対パス化済み ``HistogramSpec`` の列
    :param phases: 絶対パス化済み ``PhaseSpec`` の列
    :param background_coeffs: 初期背景 (Chebyshev) 係数数
    :param max_cyc: 各段階の最大精密化サイクル
    :param gpx_path: 精密化結果を保存する gpx の絶対パス (spec ディレクトリ内 ``workbench_out/``)
    :param phase_display: 相名→表示用メタ (``space_group``/``mp_id`` 等、任意キー)。spec の
        phases 要素の ``display`` キーを退避したもの (``PhaseSpec.from_dict`` は無視するため)。
    :param spec_dir: spec ファイルのディレクトリ (絶対パス文字列)
    """

    name: str
    histograms: tuple[HistogramSpec, ...]
    phases: tuple[PhaseSpec, ...]
    background_coeffs: int = 6
    max_cyc: int = 12
    gpx_path: str = ""
    phase_display: Mapping[str, Mapping[str, Any]] = dataclasses.field(default_factory=dict)
    spec_dir: str = "."


def _abspath(spec_dir: Path, raw: str) -> str:
    """``raw`` を ``spec_dir`` 基準で絶対化する (既に絶対パスならそのまま)。"""
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    return str((spec_dir / p).resolve())


def _convert_xrdml_if_needed(hist: HistogramSpec, spec_dir: Path, index: int) -> HistogramSpec:
    """XRDML ヒストグラムを ``workbench_out/histN.xye`` へ自己変換した ``HistogramSpec`` を返す。

    GSAS-II の Panalytical importer は optional 依存 (xmltodict) を要するため、コア側の numpy
    ローダー (``reference.io.load_xrdml``) で読んで 3 列 XYE (deg intensity esd) に落とし GSAS の
    xye importer に渡す (`insitu.engine._xrdml_to_xye` と同じ流儀・依存追加なし)。
    """
    if hist.data_format.upper() != "XRDML":
        return hist
    from ..reference.io import load_xrdml

    two_theta, intensity = load_xrdml(hist.data_path)
    out_dir = spec_dir / "workbench_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"hist{index}.xye"
    esd = np.sqrt(np.clip(np.asarray(intensity, dtype=float), 1.0, None))
    with open(out_path, "w", encoding="utf-8") as fh:
        for x, y, e in zip(two_theta, intensity, esd):
            fh.write(f"{float(x):.6f} {float(y):.4f} {float(e):.4f}\n")
    return dataclasses.replace(hist, data_path=str(out_path), data_format="XYE")


def load_project_spec(path: "str | Path") -> WorkbenchProject:
    """JSON プロジェクト spec をロードし ``WorkbenchProject`` を返す。

    spec の形は ② ``auto_rietveld`` (``HistogramSpec.to_dict``/``PhaseSpec.to_dict``) と同一。
    トップレベルは ``{"name", "histograms": [...], "phases": [...], "background_coeffs"?,
    "max_cyc"?}``。phases の各要素は任意で ``"display": {...}`` を持てる (表示専用メタ、
    ``PhaseSpec.from_dict`` の余分キー無視により素通しされないため本関数側で退避する)。

    :raises ValueError: 必須キー欠落・空配列・不明な enum 値等、不正な spec のとき
        (呼び出し側 [CLI/API] が error dict へ縮退する)。
    """
    spec_path = Path(path)
    try:
        data = json.loads(spec_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"プロジェクト spec を読み込めません: {exc}") from exc
    # 【json.JSONDecodeError は ValueError のサブクラス】: そのまま伝播させれば呼び出し側の
    #   ``except ValueError`` で捕捉できる (変換不要)。

    if not isinstance(data, dict):
        raise ValueError("プロジェクト spec はオブジェクト (dict) である必要があります")

    spec_dir = spec_path.resolve().parent
    try:
        name = str(data["name"])
        raw_histograms = list(data["histograms"])
        raw_phases = list(data["phases"])
        if not raw_histograms:
            raise ValueError("histograms が空です")
        if not raw_phases:
            raise ValueError("phases が空です")
        background_coeffs = int(data.get("background_coeffs", 6))
        max_cyc = int(data.get("max_cyc", 12))

        histograms: list[HistogramSpec] = []
        for i, h in enumerate(raw_histograms):
            hspec = HistogramSpec.from_dict(h)
            hspec = dataclasses.replace(
                hspec,
                data_path=_abspath(spec_dir, hspec.data_path),
                instrument_path=_abspath(spec_dir, hspec.instrument_path),
            )
            hspec = _convert_xrdml_if_needed(hspec, spec_dir, i)
            histograms.append(hspec)

        phases: list[PhaseSpec] = []
        phase_display: dict[str, dict[str, Any]] = {}
        for p in raw_phases:
            pspec = PhaseSpec.from_dict(p)
            pspec = dataclasses.replace(pspec, structure_path=_abspath(spec_dir, pspec.structure_path))
            phases.append(pspec)
            if isinstance(p, dict) and "display" in p:
                phase_display[pspec.phase_name] = dict(p["display"])
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise ValueError(f"不正なプロジェクト spec です: {exc}") from exc

    return WorkbenchProject(
        name=name,
        histograms=tuple(histograms),
        phases=tuple(phases),
        background_coeffs=background_coeffs,
        max_cyc=max_cyc,
        gpx_path=str(spec_dir / "workbench_out" / "refined.gpx"),
        phase_display=phase_display,
        spec_dir=str(spec_dir),
    )


def preview_pattern(spec: HistogramSpec) -> dict[str, Any]:
    """精密化前プレビュー: ``load_pattern`` で (x, yobs) を読み ≤2000 点へ間引いた契約 fit.plot 形。

    ``ycalc``/``ybkg``/``residual`` は精密化前のため ``None``、``ticks`` は空 dict
    (契約 `docs/design/gui-workbench/api-contract.md` の fit.plot 形と同一)。
    """
    two_theta, intensity = load_pattern(spec.data_path, spec.data_format)
    x = np.asarray(two_theta, dtype=float)
    y = np.asarray(intensity, dtype=float)
    if spec.two_theta_limits is not None:
        lo, hi = spec.two_theta_limits
        mask = (x >= lo) & (x <= hi)
        x, y = x[mask], y[mask]
    n = len(x)
    if n > _MAX_PREVIEW_POINTS:
        idx = np.unique(np.round(np.linspace(0, n - 1, _MAX_PREVIEW_POINTS)).astype(int))
        x, y = x[idx], y[idx]
    return {
        "x": x.tolist(),
        "yobs": y.tolist(),
        "ycalc": None,
        "ybkg": None,
        "residual": None,
        "ticks": {},
    }
