"""P0 §3.1 (U10) 準 hold-out の事例表 (凍結の作業): 事例ごとのファイル・宣言・参照構造・原子の対応。

参照のある事例では出発 CIF ↔ 独立参照 CIF を照合する。標準出力に出すのは**判定と件数だけ** (空間群が一致したか・
対応の付いた原子数・esd の付いた自由座標の数・印字精度で全一致したか)。座標・esd・距離は表示しない
(P0 §3.1: 照合のために値を表示しない)。書き出す事例表 (public) もファイルの sha256・宣言・ラベルの組・
対称操作の記号だけで、値を含まない。データファイルは sha256 を取るだけで開かない。

    python case_table.py <参照 CIF のディレクトリ> <testdata のディレクトリ> <事例表 JSON>
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from tsumugin.autorietveld.cif_normalize import read_structure_cif
from tsumugin.prereg_eval.hpub import atom_site_rows
from tsumugin.prereg_eval.mapping import esd_of, map_atoms, reference_values, same_to_printed_precision
from tsumugin.topas.symmetry import free_coord_axes

_LAB_BB = {"radiation": "xray_lab", "geometry": "bragg_brentano"}
_SYNC_DS = {"radiation": "xray_synchrotron", "geometry": "debye_scherrer"}
#: P0 §3.1: 内部標準の宣言は無い → 格子は全事例 relative (§1.3 の格子比較は全事例 unevaluated)
_COMMON = {"internal_standard": None, "lattice_scope": "relative"}

#: 事例 → ファイル (testdata からの相対)・宣言・相 (出発 CIF と参照)。順位と候補は P0 v1.6 §3.1 の表で固定済み。
CASES: dict[str, dict] = {
    "T1": {
        "data": "m7/labdata/FAP.XRA", "instrument": "m7/labdata/INST_XRY.PRM", "declaration": _LAB_BB,
        "phases": {"FAP": {"start": "m7/labdata/FAP.cif", "reference": "5000041"}},
    },
    "T3-xray": {
        "data": "PBSO4.XRA", "instrument": "INST_XRY.PRM", "declaration": _LAB_BB,
        "phases": {"PbSO4": {"start": "PbSO4-Wyckoff.cif", "reference": None}},
    },
    "T4-11BM": {
        "data": "m7/tofcw/11BM_NAC.fxye", "instrument": "m7/tofcw/11bm_gsas.prm", "declaration": _SYNC_DS,
        # CaF2 は全原子が特殊位置で自由座標が無く比較集合に入らない (P0 §3.1)
        "phases": {"NAC": {"start": "m7/tofcw/NAC.cif", "reference": "1000236"},
                   "CaF2": {"start": "m7/tofcw/CaF2.cif", "reference": None}},
    },
    "CaTeO3-030": {
        "data": "m9/cateo3/NB-LM01MO_030.XRDML", "instrument": "m9/cateo3/cateo3_CuKa.instprm", "declaration": _LAB_BB,
        "phases": {"alpha": {"start": "m9/cateo3/alpha_CaTeO3_H2O.cif", "reference": None}},
    },
    "CaTeO3-180": {
        "data": "m9/cateo3/NB-LM01MO_180.XRDML", "instrument": "m9/cateo3/cateo3_CuKa.instprm", "declaration": _LAB_BB,
        "phases": {"alpha": {"start": "m9/cateo3/alpha_CaTeO3_H2O.cif", "reference": None},
                   "delta": {"start": "m9/cateo3/delta_CaTeO3.cif", "reference": None}},
    },
}


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _hm(s: str) -> str:
    return s.replace(" ", "").replace("_", "").lower()


def _check_reference(phase: str, start_path: Path, ref_path: Path) -> dict:
    start, ref = read_structure_cif(start_path), read_structure_cif(ref_path)
    mapping = map_atoms(start, ref)
    ref_rows = {r["_atom_site_label"]: r for r in atom_site_rows(ref_path.read_text(encoding="utf-8", errors="replace"))}
    esd = {lab: tuple(esd_of(row.get(f"_atom_site_fract_{a}", "")) for a in "xyz") for lab, row in ref_rows.items()}
    start_rows = {r["_atom_site_label"]: r
                  for r in atom_site_rows(start_path.read_text(encoding="utf-8", errors="replace"))}
    # 出発 CIF に対称操作のループが無いことがある (T1) — 対応に使ったのと同じ対称操作で自由軸を決める
    ops = tuple(start.symops or ref.symops)
    free = {a.label: tuple(free_coord_axes(ops, (a.x, a.y, a.z))) for a in start.atoms}
    refs = {v.key: v for v in reference_values(start, ref, mapping, esd, phase=phase)}

    n_free = sum(len(free.get(a.label, ())) for a in start.atoms if a.label in mapping.pairs)
    n_free_esd = 0
    for a in start.atoms:
        if a.label not in mapping.pairs:
            continue
        raw = esd.get(mapping.pairs[a.label], (None, None, None))
        r, _t = mapping.images[a.label]
        for ax in free.get(a.label, ()):
            # 出発の軸 i に写る参照の軸 (回転の非零成分) にすべて esd があるか
            src = [j for j in range(3) if abs(r["xyz".index(ax), j]) > 1e-9]
            if src and all(raw[j] is not None for j in src):
                n_free_esd += 1

    start_raw = {f"coord:{phase}.{lab}": tuple(start_rows[lab][f"_atom_site_fract_{a}"] for a in "xyz")
                 for lab in mapping.pairs}
    copied = same_to_printed_precision(start_raw, {k: tuple(v.value) for k, v in refs.items()})  # type: ignore[arg-type]
    same_sg = _hm(start.spacegroup_hm) == _hm(ref.spacegroup_hm)
    print(f"  {phase}: same_space_group={same_sg} start_atoms={len(start.atoms)} ref_atoms={len(ref.atoms)} "
          f"mapped={len(mapping.pairs)} unmatched={len(mapping.unmatched)} free_coords={n_free} "
          f"free_coords_with_ref_esd={n_free_esd} same_to_printed_precision={copied}")
    return {
        "sha256": _sha256(ref_path),
        "same_space_group": same_sg,
        "symops_used": list(ops),
        "transform": "identity (出発の対称操作の像で直接対応)",
        "pairs": dict(sorted(mapping.pairs.items())),
        "unmatched": list(mapping.unmatched),
        "independent": bool(same_sg and mapping.ok and not copied),
        "free_coords": n_free,
        "free_coords_with_ref_esd": n_free_esd,
    }


def main(ref_dir: Path, testdata: Path, out: Path) -> None:
    table: dict[str, dict] = {}
    for case, spec in CASES.items():
        print(case)
        phases = {}
        for phase, ph in spec["phases"].items():
            start_path = testdata / ph["start"]
            entry: dict = {"start": {"path": ph["start"], "sha256": _sha256(start_path)}}
            if ph["reference"] is None:
                entry["reference"] = {"cod_id": None, "evaluation": "P0 §1.4 (独立参照なし)"}
            else:
                entry["reference"] = {"cod_id": ph["reference"],
                                      **_check_reference(phase, start_path, ref_dir / f"{ph['reference']}.cif")}
            phases[phase] = entry
        table[case] = {
            "data": {"path": spec["data"], "sha256": _sha256(testdata / spec["data"])},
            "instrument": {"path": spec["instrument"], "sha256": _sha256(testdata / spec["instrument"])},
            "declaration": {**spec["declaration"], **_COMMON},
            "phases": phases,
        }
    out.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote case table ({len(table)} cases)")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
