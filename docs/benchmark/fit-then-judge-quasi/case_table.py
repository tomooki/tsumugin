"""P0 §3.1 (U10) 準 hold-out の事例表: 出発 CIF ↔ 独立参照 CIF の照合 (凍結の作業)。

標準出力に出すのは**判定と件数だけ** (空間群が一致したか・対応の付いた原子数・esd の付いた自由座標の数・
印字精度で全一致したか)。座標・esd・距離は表示しない (P0 §3.1: 照合のために値を表示しない)。
原子の対応表 (ラベルの組)・使った対称操作・sha256 はリポジトリの外の私有ファイルに書く。

    python case_table.py <参照 CIF のディレクトリ> <出発 CIF のディレクトリ (testdata/m7)> <私有の出力 JSON>
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from tsumugin.autorietveld.cif_normalize import read_structure_cif
from tsumugin.prereg_eval.hpub import atom_site_rows
from tsumugin.topas.symmetry import free_coord_axes
from tsumugin.prereg_eval.mapping import esd_of, map_atoms, reference_values, same_to_printed_precision

#: (事例, 相の名前, 出発 CIF の m7 からの相対パス, 参照の COD ID)。順位と候補は P0 v1.6 §3.1 の表で固定済み。
CASES = (
    ("T1", "FAP", "labdata/FAP.cif", "5000041"),
    ("T4-11BM", "NAC", "tofcw/NAC.cif", "1000236"),
)


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _hm(s: str) -> str:
    return s.replace(" ", "").replace("_", "").lower()


def main(ref_dir: Path, start_dir: Path, out: Path) -> None:
    record = {}
    for case, phase, start_rel, cod in CASES:
        start_path, ref_path = start_dir / start_rel, ref_dir / f"{cod}.cif"
        start, ref = read_structure_cif(start_path), read_structure_cif(ref_path)
        mapping = map_atoms(start, ref)

        ref_text = ref_path.read_text(encoding="utf-8", errors="replace")
        ref_rows = {r["_atom_site_label"]: r for r in atom_site_rows(ref_text)}
        esd = {lab: tuple(esd_of(row.get(f"_atom_site_fract_{a}", "")) for a in "xyz") for lab, row in ref_rows.items()}

        start_text = start_path.read_text(encoding="utf-8", errors="replace")
        # 出発 CIF に対称操作のループが無いことがある (T1) — 対応に使ったのと同じ対称操作で自由軸を決める
        ops = tuple(start.symops or ref.symops)
        free = {a.label: tuple(free_coord_axes(ops, (a.x, a.y, a.z))) for a in start.atoms}
        start_rows = {r["_atom_site_label"]: r for r in atom_site_rows(start_text)}
        refs = {v.key: v for v in reference_values(start, ref, mapping, esd, phase=phase)}

        n_free = sum(len(free.get(a.label, ())) for a in start.atoms if a.label in mapping.pairs)
        n_free_esd = 0
        for a in start.atoms:
            v = refs.get(f"coord:{phase}.{a.label}")
            if v is None:
                continue
            raw = tuple(esd.get(mapping.pairs[a.label], (None, None, None)))
            # 出発の軸へ写した esd の有無は、写した RefValue の sigma が全軸そろったときだけ分かる。軸ごとに数えるため
            # 参照側の esd を回転の非零成分で拾う。
            r, _t = mapping.images[a.label]
            for ax in free.get(a.label, ()):
                i = "xyz".index(ax)
                src = [j for j in range(3) if abs(r[i, j]) > 1e-9]
                if src and all(raw[j] is not None for j in src):
                    n_free_esd += 1

        start_raw = {
            f"coord:{phase}.{lab}": tuple(start_rows[lab][f"_atom_site_fract_{a}"] for a in "xyz")
            for lab in mapping.pairs
        }
        ref_vals = {k: tuple(v.value) for k, v in refs.items()}  # type: ignore[arg-type]
        copied = same_to_printed_precision(start_raw, ref_vals)

        print(f"{case}: same_space_group={_hm(start.spacegroup_hm) == _hm(ref.spacegroup_hm)} "
              f"start_atoms={len(start.atoms)} ref_atoms={len(ref.atoms)} mapped={len(mapping.pairs)} "
              f"unmatched={len(mapping.unmatched)} free_coords={n_free} free_coords_with_ref_esd={n_free_esd} "
              f"same_to_printed_precision={copied}")
        record[case] = {
            "phase": phase,
            "start": {"path": start_rel, "sha256": _sha256(start_path)},
            "reference": {"cod_id": cod, "sha256": _sha256(ref_path)},
            "symops_used": list(start.symops or ref.symops),
            "pairs": mapping.pairs,
            "unmatched": list(mapping.unmatched),
            "independent": (not copied) and mapping.ok,
            "free_coords": n_free,
            "free_coords_with_ref_esd": n_free_esd,
        }
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote private record ({len(record)} cases)")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
