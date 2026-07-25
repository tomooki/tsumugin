# Workbench API 契約 (v1)

バックエンド (`tsumugin.workbench`) とフロントエンド (`frontend/src/api/types.ts`) は
本文書の JSON 形状を正とする。破壊的変更は本文書の更新を伴うこと。
全レスポンスは純 JSON (numpy 型・NaN/inf を出さない。非有限は null)。
既知の失敗は HTTP 4xx + `{"error": str, "error_type": str}`。
FastAPI 自身のリクエスト検証エラー (例: body が dict でない) は `{"detail": [...]}` 形状の 422 で
返る。クライアントはこの形状もエラーとして扱う (`client.ts` の `http_error` フォールバック)。

## GET /api/state — シェル状態

```jsonc
{
  "project": {
    "name": "K2Mn[Fe(CN)6] operando", "dataset": "SR-XRD λ 0.79958 · 247 frames",
    "frame": "fr091", "echem": { "v": 3.94, "q_mah_g": 41.2, "x_echem": "0.71(2)" } // null 可
  },
  "mode": "manual",                    // "manual" | "auto" (GUI 語彙)
  "final_selection_mode": "human",     // "human" | "agent" (FR-402, エンジン語彙)
  "source": "none",                    // "none" | "demo" | "project"
                                       //   none = プロジェクト未読込 (フロントは Welcome 画面)
  "refine": { "status": "idle" },      // /api/refine/status と同形 (シェルバッジ用)
  "project_path": null,                // project モード時は project.json の絶対パス
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
                  "guard": "", "reverted": false }],   // delta_rwp: 実 run の先頭ステージは null (前段なし)
    "validity": [{ "check": "occupancy bounds", "status": "pass", "detail": "0 ≤ occ ≤ 1" }],
    // 実プロット曲線 (hist id →)。null = 曲線なし (placeholder 表示)。配列は
    // バックエンドで ≤2000 点に間引き済み (大配列を境界で無制限に跨がせない)。
    // yobs のみ = 精密化前 (load_pattern による生データ)。ycalc/ybkg/residual/ticks
    // は精密化完了後に gpx から抽出して埋まる。
    "plot": { "sxrd": { "x": [4.0], "yobs": [123.0], "ycalc": null, "ybkg": null,
                        "residual": null, "ticks": { "alpha CaTeO3·H2O": [10.2] } } }
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
    "evidence": [["evidence backend", "bic → nested"], ["ΔlogZ", "1.2 < 2.5 threshold"]],
    // basin 散布 (マルチスタート格子ベイスン)。null = データなし (empty-state)。
    // ※ v1 時点では demo/project ともデータソース未配線 (run_multistart_rietveld 接続後に供給)
    "basin": { "points": [{ "x": 9.372, "y": 6.71, "label": "start 1" }] }
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
    // series: null = データ未取得 (empty-state 表示)。labels は系列名 (凡例)。
    "charts": [{ "id": "rwp", "title": "Rwp vs frame",
                 "series": { "x": [0], "ys": [[13.4]], "labels": ["Rwp"] } }],
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
  // PROJECT タブ用の入力設定 (V2a)。project モードで供給、demo/none では省略可
  // (省略 = 空表示。行を偽装しない)。HistogramSpec/PhaseSpec の設定を 1:1 で映す。
  "project": {
    "histograms": [{ "id": "h0", "data_path": "data/NB-LM01MO_030.XRDML",
                     "instrument_path": "data/cateo3_CuKa.instprm", "radiation": "xray_lab",
                     "geometry": "bragg_brentano", "data_format": "XRDML",
                     "two_theta_limits": [12.0, 70.0], "bank": null }],
    "phases": [{ "name": "alpha", "structure_path": "data/alpha_CaTeO3_H2O.cif" }],
    "settings": { "two_theta_limits": [12.0, 70.0], "background_coeffs": 24, "max_cyc": 20 }
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

## プロジェクトライフサイクル (V2a — アプリ基盤)

プロジェクト = ディレクトリ + `project.json` (spec スキーマは ② `auto_rietveld` と同一) +
`data/` (取り込みファイル) + `ledger.jsonl` (PersistentLedger) + `snapshots.jsonl` +
`workbench_out/`。**project.json は全ての設定変更で自動保存**。設定変更は ledger 記録。
refine 実行中のプロジェクト変更系は 409。

| 呼び出し | 成功レスポンス | 副作用 |
|---|---|---|
| POST `/api/project` `{"name": str, "directory": str}` | state | `<directory>/<name>/` 作成 + 空 project.json + 永続 ledger 開始。既存ディレクトリは 409 |
| POST `/api/project/open` `{"path": str}` | state | project.json (またはそのディレクトリ) を読みセッション切替。永続 ledger/snapshot を再オープン (verify 必須) |
| POST `/api/project/close` `{}` | state (source=none) | セッション解放 (refine 実行中 409)。ledger はファイルに残る |
| POST `/api/project/demo` `{}` | state (source=demo) | シードのデモセッション (サンプル閲覧用) |
| GET `/api/project/recent` | `{"projects": [{"name","path","last_opened"}]}` | — (`~/.tsumugin/workbench_recent.json`) |
| POST `/api/project/upload` (multipart: `file`, `kind`=`data`\|`instrument`\|`structure`) | `{"stored_path": str}` | プロジェクト `data/` へ保存 (自己完結性のためコピー方式) |
| POST `/api/project/histograms` `{data_path, instrument_path, radiation, geometry, data_format, two_theta_limits?, bank?}` | state+viewmodel 反映 | spec 追記 + 自動保存 + ledger |
| POST `/api/project/histograms/{hist_id}/remove` `{}` | 同上 | spec から除去 + ledger (**DELETE ルートは使わない** — P2 構造ガード維持。解析履歴 ledger/snapshot は不可侵、除去できるのは入力設定のみ) |
| POST `/api/project/phases` `{structure_path, phase_name}` | 同上 | spec 追記 + ledger |
| POST `/api/project/phases/{phase_name}/remove` `{}` | 同上 | spec から除去 + ledger |
| POST `/api/project/settings` `{two_theta_limits?, background_coeffs?, max_cyc?}` | 同上 | spec 更新 + ledger |

## その他の変更系

| 呼び出し | 成功レスポンス | 副作用 |
|---|---|---|
| POST `/api/hypotheses/{id}/accept` `{"by": "human"\|"agent", "reason": str}` | `{"status": "accepted"\|"recommend_only", ...}` | ledger (エンジン内) |
| POST `/api/revert` `{"hypothesis_id": str, "note": str}` | `{"status": "reverted"}` | ledger |
| POST `/api/review-queue/{id}/resolve` `{"action": "accept"\|"send_back", "note": str}` | `{"item": {...updated}}` | `ReviewQueue.resolve` + ledger |
| POST `/api/structure/apply` `{"sites": [...], "note": str}` | `{"snapshot_id": str, "ledger_index": int}` | SnapshotStore.save + ledger |
| POST `/api/approval/{action_id}` `{"decision": "approve"\|"reject"}` | `{"state": ..., "snapshot_id": str\|null, "ledger_index": int}` | 両経路 ledger、approve のみ snapshot |
| POST `/api/stages/{nn}` `{"action": "release"\|"revert"}` | `{"stage": {...updated}}` | セッション状態 + ledger |
| POST `/api/refine` `{}` | 202 `{"status": "started"}` / 409 (実行中) | 実 `run_auto_rietveld` をバックグラウンドスレッドで起動 + ledger (`refine_request`)。demo モード (project 未接続) は従来どおり 202 `{"status": "recorded"}` + ledger のみ |
| GET `/api/refine/status` | `{"status": "idle"\|"running"\|"done"\|"failed", "elapsed_s": float\|null, "last_event": str\|null, "error": str\|null}` | — (ポーリング用。完了時はフロントが state/viewmodel を再フェッチ) |
| POST `/api/transcript/message` `{"text": str}` | `{"message": {...}}` | transcript 追記 |
| GET `/api/ledger` | `{"entries": [{"index", "time", "actor", "text", "hash", "revert_to"}], "verified": true}` | — |
| GET `/api/review-queue` | `{"items": [...]}` | — |
| GET `/api/hypotheses` | viewmodel.hypotheses と同形 | — |

actor は `"AGENT ③" | "MCP ②" | "CORE ①" | "HUMAN" | "GUARD"` (LEDGER タブの色分けキー)。

## 語彙 (enum) — 両側で固定

契約の enum 語彙は以下に限る。バックエンドは逸脱を出さない (`tests/workbench/test_seed.py::
TestEnumVocabulary` がガード)。フロントは未知語彙を受けても**クラッシュせず** raw 表示へ
フォールバックする (将来の語彙追加を UI 全損にしないため)。

| フィールド | 語彙 |
|---|---|
| `review[].severity` | `close` \| `unknown` \| `guard` \| `echem` |
| `review[].state` | `pending` \| `accepted` \| `sent_back` |
| `stages[].gate` | `null` \| `bkg` \| `profile` \| `sample` \| `occ` \| `micro` |
| `transcript[].kind` | `user` \| `agent` \| `tool` \| `judgement` \| `approval` \| `escalation` |
| `fit.validity[].status` | `pass` \| `warn` \| `fail` |
| `ledger.entries[].actor` | `AGENT ③` \| `MCP ②` \| `CORE ①` \| `HUMAN` \| `GUARD` |
| `mode` / `final_selection_mode` | `manual`/`auto` ↔ `human`/`agent` (FR-402) |
