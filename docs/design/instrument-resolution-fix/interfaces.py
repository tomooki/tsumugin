"""装置分解能 抽出・固定 型/シグネチャ設計 (実装の契約)。docs 配下・非実行。

信頼性: 🔵 CeO2 実測 + engine/recipe 精読。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from tsumugin.autorietveld.model import HistogramSpec, PhaseSpec

# 装置分解能で扱う CW プロファイルキー。
INSTRUMENT_PROFILE_KEYS = ("U", "V", "W", "X", "Y", "SH/L", "Zero")


# =====================================================================
# model.py に追加
# =====================================================================


@dataclass(frozen=True)
class InstrumentProfile:
    """標準試料から実測した CW 装置分解能関数 (不変)。

    :param values: GSAS キー→値 (U,V,W,X,Y,SH/L,Zero の部分集合)
    :param source_rwp: 抽出精密化の最終 Rwp (出典の質)
    :param wavelength: 波長 Å (任意・記録用)
    """

    values: Mapping[str, float]
    source_rwp: float = float("nan")
    wavelength: float | None = None


# HistogramSpec に追加するフィールド (末尾・既定 None で後方互換):
#   instrument_profile: InstrumentProfile | None = None


# =====================================================================
# resolution.py (新規, numpy コア + GSAS 遅延は run_auto_rietveld 経由)
# =====================================================================


def build_resolution_recipe(
    *, background_coeffs: int = 12, refine_sh_l: bool = True
) -> "tuple":
    """標準試料の分解能抽出用レシピ (既存ステージフラグの合成, numpy)。

    背景→cell→profile(U,V,W)→profile_lorentzian(X,Y,Zero)→(任意)profile_asymmetry(SH/L)。
    **size/mustrain は解放しない** (標準は試料広がりが無い; 解放すると U,V,W と競合して負の局所解に
    落ちる — CeO2 実測で確認)。返り値は RefinementStage のタプル。
    """
    ...


def extract_instrument_profile(
    standard: HistogramSpec,
    structure: PhaseSpec,
    *,
    runner=None,
    background_coeffs: int = 12,
    refine_sh_l: bool = True,
) -> InstrumentProfile:
    """標準試料を精密化し装置分解能 (U,V,W,X,Y,SH/L,Zero) を抽出する (コア)。

    `build_resolution_recipe` を `run_auto_rietveld` (既定) または注入 runner に渡し、
    結果 `hist_profile[0]` から INSTRUMENT_PROFILE_KEYS を拾って InstrumentProfile を返す。
    runner 注入で決定論テスト可能 (GSAS 非依存)。実 CeO2 抽出は @pytest.mark.gsas。
    """
    ...


# 純ヘルパ (再現パイプライン用, numpy): 2列→esd付き xye / PXC instprm / 標準参照 CIF。
def to_xye_text(two_theta, intensity) -> str: ...
def pxc_instprm_text(wavelength: float, *, zero=0.0, polarization=0.95) -> str: ...
def standard_reference_cif(name: str) -> str: ...  # "CeO2"/"Si"; 未登録は KeyError


def extract_instrument_profile_from_standard(
    data_path: str,
    *,
    wavelength: float,
    standard: str = "CeO2",
    work_dir: str | None = None,
    two_theta_limits: "tuple[float, float] | None" = None,
    zero: float = 0.0,
    polarization: float = 0.95,
    background_coeffs: int = 12,
    refine_sh_l: bool = False,
    runner=None,
) -> InstrumentProfile:
    """**生の 2 列標準データ 1 ファイルから**装置分解能を一括再現する (再現パイプライン)。

    load_xy (2列読込) → to_xye_text (Poisson esd) → standard_reference_cif (CeO2/Si) →
    pxc_instprm_text → extract_instrument_profile。中間ファイルは work_dir (省略時 一時 dir)。
    返す InstrumentProfile に wavelength を記録。scratchpad の手作業を関数化し再現性を担保。
    """
    ...


# =====================================================================
# engine.py の変更 (固定配線)
# =====================================================================


def _fixed_profile_flags(histograms: Sequence[HistogramSpec]) -> list[bool]:
    """各ヒストグラムが装置プロファイル固定か (instrument_profile 指定) を返す (numpy)。"""
    ...


def _seed_instrument_profile(g2hist, profile: InstrumentProfile) -> None:
    """InstrumentProfile.values を GSAS Instrument Parameters に書き込む (GSAS 依存)。

    inst[0][key][1] = value。存在しないキーは無視 (EDGE-001)。
    """
    ...


# _apply_stage(gpx, hists, phases, phase_infos, atom_flag_maps, radiations, stage, fixed_profile)
#   profile / profile_lorentzian / profile_asymmetry の各ループで
#   `if fixed_profile[i]: continue` を追加 (固定ヒストグラムの U,V,W/X,Y/SH·L を解放しない, REQ-101/103)。
#   size_strain は固定対象外 → 試料広がりを担う。
#
# run_auto_rietveld: ステージループ前に固定ヒストグラムへ _seed_instrument_profile、
#   fixed_profile = _fixed_profile_flags(histograms) を _apply_stage に渡す。
