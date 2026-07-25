# Workbench API 契約 (v1)

バックエンド (`tsumugin.workbench`) とフロントエンド (`frontend/src/api/types.ts`) は
本文書の JSON 形状を正とする。破壊的変更は本文書の更新を伴うこと。
全レスポンスは純 JSON (numpy 型・NaN/inf を出さない。非有限は null)。
既知の失敗は HTTP 4xx + `{"error": str, "error_type": str}`。

## GET /api/state — シェル状態

```jsonc
{
  "project": {
    "name": "K2Mn[Fe(CN)6] operando", "dataset": "SR-XRD λ 0.79958 · 247 frames",
    "frame": "fr091", "echem": { "v": 3.94, "q_mah_g": 41.2, "x_echem": "0.71(2)" } // null 可
  },
  "mode": "manual",                    // "manual" | "auto" (GUI 語彙)
  "final_selection_mode": "human",     // "human" | "agent" (FR-402, エンジン語彙)
  "ledger": { "count": 1281, "verified": true },
  "status": { "backend_build": "tsumugin 0.3.0", "seed": 0, "mcp_tools": 36 },
  "agent": { "tokens": 1240000, "wall_time_s": 1084, "idle": true }  // idle=true (MANUAL)
}
```

## POST /api/mode `{"mode": "manual"|"auto"}` → 200 で新しい state (上と同形)

副作用: `FinalSelectionEngine.set_mode` + ledger 追記 (`kind="mode_switch"`)。
同一モードへの切替は 200 で現 state (ledger 追記なし)。不正値は 422 error dict。

## GET /api/viewmodel — タブ表示データ一式 (v1 は決定論シード)

```jsonc
{
  "datasets":  [{ "id": "sxrd", "name": "SR-XRD", "meta": "λ 0.79958 · 247 fr", "probe": "X", "active": true }],
  "phases":    [{ "id": "p1", "name": "cubic K2Mn[Fe(CN)6]", "swatch": "accent",
                  "space_group": "Fm-3m", "mp_id": "mp-583814", "wt_frac": "62.1(4) %" }],
  "channels":  [{ "id": "echem", "label": "echem", "value": "V 3.94 · I −0.20 mA · Q 41.2" }],
  "snapshots": [{ "id": "S-0310", "note": "before stage 07" }],
  "fit": {
    "metrics": [{ "key": "rwp", "label": "Rwp", "value": "6.71%", "note": "vs manual 16.24%" }],
    "histograms": [{ "id": "sxrd", "label": "SR-XRD λ0.79958", "active": true }],
    "limits_note": "two_theta_limits = [4.0, 38.0] · background 24 terms · Kα1 instprm",
    "phase_ticks": ["cubic K2Mn[Fe(CN)6]"], "two_theta": { "min": 4.0, "max": 38.0 },
    "history": [{ "stage": "06 phase fractions", "rwp": 7.02, "delta_rwp": -0.31,
                  "guard": "", "reverted": false }],
    "validity": [{ "check": "occupancy bounds", "status": "pass", "detail": "0 ≤ occ ≤ 1" }]
  },
  "parameters": {                       // hist id → カード列
    "sxrd": { "released_count": 3, "cards": [{
      "id": "radiation", "title": "RADIATION / WAVELENGTH", "note": "instprm",
      "dropdown": { "label": "source", "value": "synchrotron X-ray",
                    "options": ["synchrotron X-ray", "lab Cu Kα", "lab Mo Kα", "neutron CW", "neutron TOF"] },
      "rows": [{ "field": "wavelength λ / Å", "value": "0.799580", "esd": "±0.000004",
                 "released": false, "locked": false }],
      "footer": "λ/cell is near-singular — keep λ fixed …" }] }
  },
  "hypotheses": {
    "rows": [{ "rank": 1, "id": "H-014", "phases": "cubic + mono + tetra", "p": 0.62,
               "rwp": 6.71, "gof": 1.29, "bic": 39402, "close": true,
               "status": "provisional", "selected": true }],
    "diff": { "vs": "H-011", "rows": [{ "field": "phases", "a": "…", "b": "…", "changed": true }] },
    "evidence": [["evidence backend", "bic → nested"], ["ΔlogZ", "1.2 < 2.5 threshold"]]
  },
  "phase_id": {
    "candidates": [{ "rank": 1, "formula": "KMnFe(CN)6", "source": "MP", "sg": "P21/n",
                     "dara": 0.86, "mwmsx": "41/2/1/3", "strain": "0.4%",
                     "chem_guard": "ok", "guard_fail": false }],
    "unexplained": [{ "two_theta": 12.42, "sn": 8.1, "indexing": "unindexed" }],
    "completeness": { "is_complete": false, "notes": ["tetra fraction non-monotonic …"],
                      "flagged_frames": "fr088–fr101" }
  },
  "sequence": {
    "charts": [{ "id": "rwp", "title": "Rwp vs frame" }],
    "anchors": [{ "id": "fr012", "crossover": false }, { "id": "fr091", "crossover": true }],
    "note": "crossover fr091 · total_bic minimum · x_XRD follows x_echem within esd",
    "segments": [{ "segment": "fr061–fr091", "forward": "cubic+mono", "backward": "cubic+tetra",
                   "rwp": "7.9 / 8.0", "total_bic": "41 208 / 39 402", "selected": "backward" }]
  },
  "structure": {
    "sites": [{ "id": "s1", "label": "K1", "el": "K", "x": "0.2500", "y": "0.2500", "z": "0.2500",
                "occ": "0.71", "uiso": "0.0450", "note": "free_occupancy",
                "lock": { "x": true, "y": true, "z": true },
                "rel": { "x": false, "y": false, "z": false, "occ": true, "uiso": false } }],
    "constraints": [{ "kind": "EqnConstr", "text": "Σ occ(K1) · Z = x_total(t)", "ref": "FR-318" }],
    "mem_peaks": [{ "position": "(0.5, 0.25, 0.0)", "density": "0.82 fm Å⁻³", "assign": "Ow?" }]
  },
  "stages": [{ "nn": "01", "name": "background", "flags": "6→24 terms", "delta_rwp": "−41.2",
               "released": true, "gate": "bkg" }],   // gate: null | bkg|profile|sample|occ|micro
  "review": [{ "id": "rv1", "severity": "close", "title": "close competitor",
               "ref": "ΔlogZ 1.2", "detail": "…", "state": "pending" }],
  "transcript": [
    { "id": "t1", "kind": "user", "text": "…" },
    { "id": "t2", "kind": "agent", "text": "…" },
    { "id": "t3", "kind": "tool", "tool": "check_phase_set", "layer": "MCP ②", "secs": 1.8,
      "args": "{…}", "ret": "{…}" },
    { "id": "t4", "kind": "judgement", "rows": [{ "label": "cubic + tetragonal",
      "rwp": 8.04, "bic": 41208, "chosen": false }], "text": "…" },
    { "id": "t5", "kind": "approval", "action_id": "a1", "title": "…", "rationale": "…",
      "action_json": "{…}", "state": "pending" },   // pending|approved|rejected
    { "id": "t6", "kind": "escalation", "fr": "FR-403", "text": "…" }
  ]
}
```

## その他の変更系

| 呼び出し | 成功レスポンス | 副作用 |
|---|---|---|
| POST `/api/hypotheses/{id}/accept` `{"by": "human"\|"agent", "reason": str}` | `{"status": "accepted"\|"recommend_only", ...}` | ledger (エンジン内) |
| POST `/api/revert` `{"hypothesis_id": str, "note": str}` | `{"status": "reverted"}` | ledger |
| POST `/api/review-queue/{id}/resolve` `{"action": "accept"\|"send_back", "note": str}` | `{"item": {...updated}}` | `ReviewQueue.resolve` + ledger |
| POST `/api/structure/apply` `{"sites": [...], "note": str}` | `{"snapshot_id": str, "ledger_index": int}` | SnapshotStore.save + ledger |
| POST `/api/approval/{action_id}` `{"decision": "approve"\|"reject"}` | `{"state": ..., "snapshot_id": str\|null, "ledger_index": int}` | 両経路 ledger、approve のみ snapshot |
| POST `/api/stages/{nn}` `{"action": "release"\|"revert"}` | `{"stage": {...updated}}` | セッション状態 + ledger |
| POST `/api/refine` `{}` | 202 `{"status": "recorded"}` | ledger のみ (runner は M-later) |
| POST `/api/transcript/message` `{"text": str}` | `{"message": {...}}` | transcript 追記 |
| GET `/api/ledger` | `{"entries": [{"index", "time", "actor", "text", "hash", "revert_to"}], "verified": true}` | — |
| GET `/api/review-queue` | `{"items": [...]}` | — |
| GET `/api/hypotheses` | viewmodel.hypotheses と同形 | — |

actor は `"AGENT ③" | "MCP ②" | "CORE ①" | "HUMAN" | "GUARD"` (LEDGER タブの色分けキー)。
