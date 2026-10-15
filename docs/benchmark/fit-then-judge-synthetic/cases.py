"""合成 `S-dev` の事例の定義 (fit-then-judge P0 §6)。生成は `generate.py`、パターンは追跡しない。

構造は COD (CC0) から ID と sha256 で取る。**型で先に決め** (混合占有・極性・結合した特殊位置・多相)、
どの化合物が `H-pub` の候補かを見ずに選んだ (規則: 鉱物名・空間群番号・化学式が一致する最小の COD ID、2026-10-15)。
ここに出る化合物は `H-pub` の候補から除く (P0 §3.2.1-2)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(frozen=True)
class Source:
    cod_id: str
    revision: str  # COD の svnrevision (検索結果の値)
    sha256: str
    formula: str
    mineral: str


#: 化合物 → 出典。取得は qiserver.ugr.es の COD ミラー (2026-10-15)
SOURCES: dict[str, Source] = {
    "ZnO": Source("1011258", "201954", "36048fbb028bb2b080971aa754b20cba27b27bb1b415e4c62d96d9d570fa795f", "Zn O",
                  "zincite"),
    "Mg2SiO4": Source("1572966", "295660", "dc170b976eac15dd037111af3e949125800827d3197d356698b45a354c694a3b",
                      "Mg2 Si O4", "forsterite"),
    "FeS2": Source("5000115", "202022", "2b4f67b13a18079079f987ed2785662a176364ddfae19e10d646da143337344d", "Fe S2",
                   "pyrite"),
    "MgAl2O4": Source("5000120", "176451", "c4102e57cfd9d427196b1ad2a353d87f1b3383eddb3177c7e9bc32c90c99df3f",
                      "Mg Al2 O4", "spinel"),
    "TiO2": Source("9004141", "291351", "99f2f735243120d0e3b9d40619fcd17642048a44f08f1c85bc5a9a7077434cd5", "Ti O2",
                   "rutile"),
}


@dataclass(frozen=True)
class PhaseDef:
    compound: str
    wt: float
    in_model: bool = True  # False = 真値にだけある相 (欠陥 #5 欠落相)
    mixed_fe: float | None = None  # 真値で Mg 席に Fe をこの割合で混ぜる (混合占有の型)
    preferred_orientation: tuple[float, tuple[int, int, int]] | None = None  # 真値の選択配向 (#10)
    refine_cell: bool = True  # False = 出発で格子を凍結 (#8)


@dataclass(frozen=True)
class CaseDef:
    case_id: str
    instrument: str
    max_counts: float
    phases: tuple[PhaseDef, ...]
    defects: tuple[tuple[int, str], ...] = ()  # (欠陥の番号, 対象 "<化合物>.<ラベル>" など)
    mismatches: tuple[str, ...] = ()
    seed: int = 0
    note: str = ""
    extra: dict = field(default_factory=dict)


CASES: tuple[CaseDef, ...] = (
    CaseDef("sdev01_zno_control", "lab_bb", 1e4, (PhaseDef("ZnO", 1.0),), seed=101,
            note="対照 (欠陥なし・不一致なし)"),
    CaseDef("sdev02_zno_polar_shift", "sync_ds", 1e5, (PhaseDef("ZnO", 1.0),), defects=((9, "ZnO.z"),),
            mismatches=("asymmetry",), seed=102),
    CaseDef("sdev03_zno_zero", "lab_bb", 1e4, (PhaseDef("ZnO", 1.0),), defects=((7, "instrument.zero"),),
            mismatches=("kalpha2_ratio",), seed=103),
    CaseDef("sdev04_zno_pref", "lab_bb", 1e5, (PhaseDef("ZnO", 1.0, preferred_orientation=(0.8, (0, 0, 1))),),
            defects=((10, "ZnO.001"),), seed=104),
    CaseDef("sdev05_fo_displaced", "sync_ds", 1e5, (PhaseDef("Mg2SiO4", 1.0),), defects=((4, "Mg2SiO4.O3"),),
            mismatches=("impurity_peak",), seed=105, note="O3 は一般位置 (8d)"),
    CaseDef("sdev06_fo_cell", "lab_bb", 1e4, (PhaseDef("Mg2SiO4", 1.0),), defects=((6, "Mg2SiO4.cell"),),
            seed=106),
    CaseDef("sdev07_fo_mixed", "sync_ds", 1e5, (PhaseDef("Mg2SiO4", 1.0, mixed_fe=0.15),),
            defects=((3, "Mg2SiO4.M2"),), mismatches=("amorphous_hump",), seed=107,
            note="真値は (Mg0.85Fe0.15)2SiO4。出発は M2 の比をずらす"),
    CaseDef("sdev08_fo_missing_atom", "lab_bb", 1e5, (PhaseDef("Mg2SiO4", 1.0),), defects=((2, "Mg2SiO4.O1"),),
            seed=108),
    CaseDef("sdev09_spinel_swap", "lab_bb", 1e4, (PhaseDef("MgAl2O4", 1.0),), defects=((1, "MgAl2O4.Mg1/Al1"),),
            mismatches=("asymmetry",), seed=109, note="(x,x,x) の O と 8a/16d の取り違え"),
    CaseDef("sdev10_pyrite_control", "sync_ds", 1e4, (PhaseDef("FeS2", 1.0),), mismatches=("amorphous_hump",),
            seed=110, note="(x,x,x) の S。欠陥なし"),
    CaseDef("sdev11_mix_missing_phase", "sync_ds", 1e5,
            (PhaseDef("ZnO", 0.95), PhaseDef("TiO2", 0.05, in_model=False)), defects=((5, "TiO2"),),
            mismatches=("asymmetry",), seed=111),
    CaseDef("sdev12_mix_minor_frozen", "lab_bb", 1e5,
            (PhaseDef("ZnO", 0.9), PhaseDef("FeS2", 0.1, refine_cell=False)), defects=((8, "FeS2.cell"),),
            mismatches=("impurity_peak",), seed=112),
)
