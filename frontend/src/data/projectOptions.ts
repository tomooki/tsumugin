// Legal values for the PROJECT tab's HISTOGRAMS add-form (radiation /
// geometry / data_format selects), ported by hand from the backend enums —
// src/tsumugin/ is read-only for this task (parallel backend work), so these
// are a snapshot, not an import, and must be kept in sync manually if the
// Python enums change:
//   - radiation/geometry: `Radiation`/`Geometry` in
//     src/tsumugin/autorietveld/model.py (values are the wire strings, e.g.
//     "xray_lab" — HistogramSpec.to_dict() round-trips them verbatim).
//   - data_format: `_LOADERS` dispatch keys in src/tsumugin/reference/io.py,
//     narrowed to the subset REQ-GUI-016 names for GUI file import
//     (XRDML/XY/XYE/FXYE/GSAS) — INT/IGOR are vendor interop formats
//     (tsumugin.interop) not part of the GUI's direct-upload path.

export interface OptionEntry {
  value: string;
  label: string;
}

export const RADIATION_OPTIONS: OptionEntry[] = [
  { value: "xray_lab", label: "lab X-ray" },
  { value: "xray_synchrotron", label: "synchrotron X-ray" },
  { value: "neutron_cw", label: "neutron CW" },
  { value: "neutron_tof", label: "neutron TOF" },
];

export const GEOMETRY_OPTIONS: OptionEntry[] = [
  { value: "bragg_brentano", label: "Bragg-Brentano" },
  { value: "debye_scherrer", label: "Debye-Scherrer" },
];

export const DATA_FORMAT_OPTIONS: OptionEntry[] = [
  { value: "XRDML", label: "XRDML" },
  { value: "XY", label: "XY" },
  { value: "XYE", label: "XYE" },
  { value: "FXYE", label: "FXYE" },
  { value: "GSAS", label: "GSAS" },
];
