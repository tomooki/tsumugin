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
  "refine": { "status": "idle", "kind": null }, // /api/refine/status と同形 (シェルバッジ用)
  "project_path": null,                // project モード時は project.json の絶対パス
  "ledger": { "count": 1281, "verified": true },
  "status": { "backend_build": "tsumugin 0.3.0", "seed": 0, "mcp_tools": 36, "gsas_available": true },
    // gsas_available: GSAS-II (GSASIIscriptable) が import 可能かの動的判定 (毎回評価, 定数コスト)。
    // false のとき refine/multistart/sequential ジョブ起動は 422
    // {"error": "...", "error_type": "GSASUnavailableError"} へ縮退する (Tier1 sidecar は
    // コア+web extra のみ同梱・GSAS-II はローカル導入前提, desktop/README.md)。
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
  // 左レール PHASES IN MODEL + PHASES タブ (§PHASES タブ) が共有する 1 相 1 行。
  // structure_path 以降は project モードのみ (demo/シードは省略可 = PHASES タブは空表示)。
  "phases":    [{ "id": "p1", "name": "cubic K2Mn[Fe(CN)6]", "swatch": "accent",
                  "space_group": "Fm-3m", "mp_id": "mp-583814", "wt_frac": "62.1(4) %",
                  "structure_path": "data/alpha.cif", "refine_cell": true,
                  "temperature": null,
                  // 精密化後の実格子 (未精密化は null)。esd は揃っていれば併記。
                  "cell": { "a": "9.3721(3)", "b": "9.3721(3)", "c": "6.8861(4)",
                            "alpha": "90", "beta": "90", "gamma": "120" },
                  // この相に触れるレシピ段のラベル (読み取り専用・build_recipe 由来)
                  "stages": ["S1 cell+displacement", "S2 profile+size_strain"] }],
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
    // 相同定の元素系 = **現相集合の CIF から導出**した実際の値 (固定リストではない)。
    // POST /api/phaseid が `identify_pattern(elements=…)` に渡すものと同一の導出
    // (`_elements_from_project`)。相 0 件 / pymatgen 未導入 / 全 CIF 読込失敗は `[]` で、
    // UI は元素の記述自体を出さない (存在しない元素系をでっち上げない)。
    "elements": ["C", "Fe", "K", "Mn", "N", "O"],
    "candidates": [{ "rank": 1, "formula": "KMnFe(CN)6", "source": "MP", "sg": "P21/n",
                     "dara": 0.86, "mwmsx": "41/2/1/3", "strain": "0.4%",
                     "chem_guard": "ok", "guard_fail": false, "mp_id": "mp-19017" }],
                     // mp_id: POST /api/phaseid/add にそのまま渡す MP material_id (A4)
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

## ファイル選択 (Welcome のファイル選択ウィンドウ)

**Web ページからは OS のファイルダイアログを開いてもパスを取得できない** (`<input type=file>` は
内容だけでパスを返さない)。そのため**バックエンドがディレクトリを列挙し、アプリ内にファイル選択
ウィンドウを描く**方式にする (ブラウザでも Tauri でも同一動作)。読み取り専用・localhost 前提で、
プロジェクトの作成/開くが既に任意パスを受ける以上、能力の種類は増えない。

| 呼び出し | 内容 |
|---|---|
| GET `/api/fs/roots` | `{"roots": [{"path": str, "label": str}]}` — ホーム + ドライブ (Windows) / `/` (POSIX) |
| GET `/api/fs/list?path=<abs>` | `{"path", "parent": str\|null, "is_project": bool, "entries": [{"name", "path", "is_dir", "is_project"}]}`。トップレベル `is_project` は**現在地**がプロジェクトか — 「上へ」やルート経由で入ると entry を経由しないため、これが無いと*開けるのに SELECT が押せない*。**ディレクトリと `.json` のみ**返す (中身は返さない)。`is_project` = そのディレクトリ直下に `project.json` があるか (開く先の目印)。存在しない/権限なし/ファイルパス指定は 404・422 error dict |

UI: Welcome の NEW PROJECT は「保存先を選ぶ」ボタン → ピッカー (ディレクトリ選択モード) +
名前入力。OPEN は「プロジェクトを選ぶ」ボタン → ピッカー (`is_project` のディレクトリ、または
`project.json` を選択)。手入力欄も残す (パスをコピペしたい場合)。

## プロジェクトを閉じる導線

`POST /api/project/close` は V2a から実装済みだが **UI に導線が無かった** (開いたら Welcome に
戻れない)。コンテキストバー右端に CLOSE PROJECT ボタンを常設し、`source != "none"` のとき表示する。
ジョブ実行中は 409 → 非致命メッセージ (「実行中は閉じられません」)。

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
| POST `/api/project/phases/{phase_name}/settings` `{refine_cell: bool}` | 同上 | 相単位の精密化設定 (§PHASES タブ)。`PhaseSpec.refine_cell` を更新 + 自動保存 + ledger |
| POST `/api/project/settings` `{two_theta_limits?, background_coeffs?, max_cyc?}` | 同上 | spec 更新 + ledger |

### PHASES タブ (2026-07-27)

相スコープの精密化制御に居場所を与えるタブ。左レールの PHASES IN MODEL が「今どの相が居るか」
だけを示すのに対し、こちらは**相ごとに何を解放するか**を扱う。

| 列 | 出所 | 編集 |
|---|---|---|
| 相名 / 空間群 / mp_id | `viewmodel.phases[]` | ― |
| wt% (esd) | 精密化後 `phase_weight_fractions` | ― |
| 格子 a/b/c/α/β/γ | 精密化後 `refined_cells` + `cell_esd` | ― |
| 構造ファイル | `structure_path` | ― |
| **REFINE CELL** | `PhaseSpec.refine_cell` | ✔ (相単位, Issue #47: 副相のセル固定) |
| 触れる段 | `build_recipe` 由来 (読み取り専用) | ― |
| REMOVE | ― | ✔ |

**⚠ 相単位で制御できるのは今のところ `refine_cell` だけ**である (黙って未露出にしない宣言):
`size_strain` / `preferred_orientation` / `hydrostatic_strain` も物理的には相スコープだが、
engine (`_apply_stage`) は**全相へ一律に**適用しており相単位のスイッチを持たない。したがって
これらは段 (レシピ) 単位の ON/OFF でしか制御できず、本タブでは読み取り専用の「触れる段」列で
示すに留める。相単位化はレシピのルール化 (段階解放順序の GUI 制御) と同じ作業単位で扱う。

## 解析ループ (V2a' — A2〜A6)

| 呼び出し | 成功レスポンス | 副作用 / 備考 |
|---|---|---|
| (viewmodel) `structure.sites` | 精密化完了後、**gpx から実サイト** (label/el/x/y/z/occ/uiso + esd 併記 note + 特殊位置 lock) が入る (A2)。未精密化 project は空 (empty-state)。demo は従来シード | — |
| POST `/api/structure/apply` | 従来どおり + **適用済み revisions は次回 refine に実反映** (occ → `initial_occupancies`、site 削除等の構造編集は v2a' では occ/uiso のみ対象と明記) (A3) | snapshot + ledger (従来) |
| POST `/api/phaseid` `{"mode": "pattern"\|"residual", "top_k"?: int, "elements"?: [str]}` | 202 `{"status": "started"}` / 409 | 相同定ジョブ (A4): `identify_pattern` を MP 供給元 (env `MATERIALS_PROJECT_API`) で実行。**元素系は `elements` で明示指定でき**、省略時のみ現相集合の CIF から導出する (下記)。完了で viewmodel.phase_id.candidates が実候補に。key 未設定は 422 error dict |
| GET `/api/phaseid/status` | refine/status と同形 | ポーリング (refine と同一ジョブ枠 = 同時実行 409) |
| POST `/api/phaseid/add` `{"formula": str, "mp_id": str}` | state | ADD AS PHASE (A4): 候補 CIF を物質化して `data/` へ保存 → `add_phase` (ledger)。再精密化はユーザーが RUN で明示 |
| POST `/api/multistart` `{"n_starts"?: int (既定3), "scale"?: float (既定0.007)}` | 202 / 409 | `run_multistart_rietveld` ジョブ (A5)。完了で viewmodel.hypotheses.basin (points: x=主格子軸 a, y=Rwp, label=start) + `corroborated` 行が evidence に |
| GET `/api/multistart/status` | 同形 | ポーリング (同一ジョブ枠) |
| GET `/api/export/gpx` | gpx ファイル (application/octet-stream) / 404 (未精密化) | keep_gpx 生成物のダウンロード (A6, FR-424: ファイル名に project 名) |

ジョブ枠は 1 つ (refine/phaseid/multistart は相互に 409) — GSAS 直列実行の前提を単純に保つ。

### 相同定の元素系 (2026-07-27 改訂)

**未知試料の単一パターン解析では「CIF を読み込んでから相同定」という順序は成り立たない** —
どの相か判らないから同定するのであって、相の CIF は同定の**結果**である。よって元素系は
`POST /api/phaseid` の `elements` で**直接指定できる**ことを第一の経路とする。

| `elements` | 挙動 |
|---|---|
| 指定あり (非空) | その元素系をそのまま使う。**相 0 件のプロジェクトでも同定できる** (これが主経路) |
| 省略 / `null` | 現相集合の CIF から導出 (`_elements_from_project`)。既存の operando 経路の互換 |
| `[]` (空配列) | 422 — 明示的に空を渡すのは意味を成さない (省略とは区別する) |
| 未知の元素記号を含む | 422 `{"error": "unknown element symbol: …"}`。ジョブは起動しない。`"D"` は H の同位体で MP の chemsys には無いため個別に案内する |

指定値は重複排除 + 昇順ソートで正規化する (NFR-102 決定性)。`viewmodel.phase_id.elements` は
**直近の同定で実際に使われた元素系**を返し、まだ一度も走っていなければ CIF 由来の導出値
(= UI の初期選択) を返す。`POST /api/phaseid/add` (ADD AS PHASE) も同じ元素系を使う —
相 0 件のプロジェクトでも同定 → 追加まで通る。

## 逐次 / operando (V2b — B1〜B5)

project.json は任意の `"frames": [{"data_path", "axis_value", "label"?}]` +
`"frame_axis": "temperature"|"time"|"index"` を持てる (B1)。フレーム列の装置条件は
histograms[0] (instrument_path/radiation/geometry/data_format/two_theta_limits) を共有する
(M9 の系列 = 単一装置の前提)。ジョブ枠は既存と同一 (kind に "sequential" が加わる)。

| 呼び出し | 成功レスポンス | 副作用 / 備考 |
|---|---|---|
| POST `/api/project/frames` `{"frames": [...]}` | state | フレーム列を**全置換** (冪等 set)。spec 自動保存 + ledger。パスは data/ 基準絶対化・実在検証 |
| POST `/api/sequential` `{"mode": "forward"\|"anchored", "anchor_table"?: {frame_index: [phase,...]}, "use_charge_constraint"?: bool}` | 202 / 409 | ② `sequential_rietveld`/`anchored_sequential` の instrument JSON spec 経路をジョブ化 (B2/B3)。frames 未設定は 422。**進捗 = ledger の `sequential_progress` ハートビート (15s 間隔・`elapsed_s`)** — 「動いているか固まっているか」を LEDGER タブで判別できる粒度。厳密な frame k/N は ①/② への ledger 注入が要るため次段 (`docs/benchmark/gui-sequential-14frames.md`)。**operando 既定は anchored を推奨** (CLAUDE.md: 相数は bic で抑制) |
| GET `/api/sequential/status` | refine/status と同形 (kind="sequential") | ポーリング |
| (viewmodel) `sequence` | 完了後: charts 3 本の series 実データ (rwp / lattice a,c per 相 / **phase_weight_fractions** [Scale でなく出版値] + x_echem overlay)、anchors (anchored 時: crossover=total_bic 最小)、segments (crossovers 写像)、per-frame 表 `sequence.frames[]` ({frame, label, axis_value, rwp, cells, fractions, changepoint}) | — |
| POST `/api/echem` `{"mpr_path": str, "offset_s": float, "interval_s": float, "sign": -1\|1, "x0"?: float}` | `{"curve", "targets", ...}` (② align_echem+alkali_budget の出力) | 同期実行 (軽量)。mpr は upload (kind="echem") 経由も可。結果はセッション保持 → channels 実値 + fraction chart overlay + sequential の charge_constraint に使用可 (B4)。galvani 未導入/ファイル不正は 422 |
| (B5 新相提案) | — | sequential 完了時、changepoint/未説明残差のフレームがあれば **ModelAction 承認カード** (transcript approval) を生成: 「frame N で新相を同定して追加するか」。APPROVE → phaseid ジョブ (残差, elements は現相集合由来) → top 候補を物質化して相追加 (ledger)。再実行はユーザーの明示 RUN。REJECT → 提案は ledger に残る。**エンジン内自動受理は GUI 経路では使わない** (提案≠適用) |
| (B5 異方セル補正, Issue #20) | — | APPROVE は ② `identify_and_add_phase` に **`known_phases`** (現相集合 + そのフレームの `refined_cells`) と **instprm 実波長** を渡す。これが無いと候補 CIF は MP(DFT) 素の格子のまま返り (実測 CaTeO3: c 軸 +3.42%)、Rietveld の収束半径 ~2% を超えて Rwp が高止まりする。**波長が読めない系 (instprm 不在・TOF) は `known_phases` を渡さない** — 誤波長で既知相を引くと残差自体が壊れ、補正なしより悪い。結果は LEDGER に `approval ... · cell prealign: residual (known=N, λ=…Å)` / `skipped (DFT cell kept: …)` として出る (「Rwp が下がらない」の第一容疑がセル誤差かを判別する信号) |
| (B4 FR-403) | — | alkali feasibility infeasible フレームは ReviewQueue へ自動追加 (severity=echem) |

## アプリ設定 (資格情報) — Materials Project トークン

MP API キーを**環境変数/.env でなく GUI から**入力できるようにする。プロジェクトではなく
**ユーザ単位の設定** (`~/.tsumugin/settings.json`, POSIX では 0600) に保存する — project.json は
共有・zip される想定であり、資格情報を置いてはならない。

**取り扱いの絶対規則**:
- **API はキー本体を返さない**。`GET /api/settings` は `{"mp_api_key_set": bool, "mp_api_key_hint": str|null, "mp_api_key_source": "settings"|"env"|null}` のみ (hint は末尾 4 文字程度のマスク表示)。
- **ledger にキーを書かない**。記録するのは `settings_change` (payload は `{"key": "mp_api_key", "action": "set"|"clear"}` のみで値を含まない)。
- **エージェントに読ませない**: shim にキーを返すツールを作らない。`get_state` に載るのは `mp_available: bool` だけ。
- 優先順位: 設定ファイル > 環境変数 `MATERIALS_PROJECT_API` > `.env`。**判定は実際にキーを解決する `MPRestClient` と同じ順序にする** — `.env` を見ないと「実際は動くのに `mp_available=false` で IDENTIFY が disabled」という*使えるのに使わせない*誤判定になる (実機で踏んだ)。`.env` 由来は利用者視点で `source: "env"` に含める。保存時にプロセスの環境変数へも反映し、既存の `MPRestClient()` 遅延構築経路がそのまま使えるようにする (① の変更なし)。

| 呼び出し | 内容 |
|---|---|
| GET `/api/settings` | 上記のマスク済み状態 |
| POST `/api/settings` `{"mp_api_key": str}` | 保存 + プロセス env 反映 + ledger (値なし)。空文字は 422 |
| POST `/api/settings/clear` `{"key": "mp_api_key"}` | 削除 + env から除去 + ledger |
| GET `/api/state` の `status.mp_available` | 設定 or env にキーがあるか (相同定ボタンの事前 disabled に使う。`gsas_available` と同じ流儀) |

UI: タイトルバー右の歯車 → SETTINGS モーダル (Welcome 画面からも開ける)。入力は `type="password"`、
保存後は本体を表示せずマスク + 「設定済み (env / settings)」表示と CLEAR ボタン。

## MEM 密度マップ (V3b — FR-601)

精密化済み gpx から実 Dysnomia MEM を回し、断面を STRUCTURE タブに描く。ジョブ枠は共有
(kind に `"mem"` が加わる — GSAS/Dysnomia 直列実行の前提を保つ)。Dysnomia バイナリ不在は 422
(`error_type: "MEMUnavailableError"`)。

| 呼び出し | 内容 |
|---|---|
| POST `/api/mem` `{"phase"?: str, "hist"?: str, "map_type"?: "Fobs"\|"delt-F", "dmin"?: float, "grid_step"?: float}` | 202 / 409。② `mem_density` をジョブ実行。未精密化 (gpx 無し) は 422 |
| GET `/api/mem/status` | refine/status と同形 (kind="mem") |
| (viewmodel) `structure.mem` | 完了後: `{"map": {"axis": "c", "index": 0, "nx": int, "ny": int, "values": [[...]], "vmin": float, "vmax": float, "unit": str}, "peaks": [...], "note": str}`。**values は ≤128×128 に縮約** (大配列を境界で無制限に跨がせない)。縮約は点サンプリングではなく**ブロック内の絶対値最大** — 隙間に落ちたピークが図から消えて「未モデル密度なし」と誤読されるのを防ぐ (Fobs の正ピーク・delt-F の負ローブとも保存、代わりに幅は 1 セル広く見える)。ピーク一覧 `peaks` は生グリッドから算出され本縮約の影響を受けない。null = 未実行 (empty-state) |
| (viewmodel) `structure.mem_peaks` | 既存キー。実 MEM のピーク (position/density/assign) に差し替わる |

断面は既定で c 軸に垂直な中央スライス。フロントは SVG heatmap (トークンの neutral↔accent
ランプで塗り分け、凡例に vmin/vmax + 単位)。**エージェントには `run_mem` を SafeAction として
公開** (再実行可能な計算であり ledger に残る)。

## AUTO 実 LLM ブリッジ (V3a — ローカル Claude Code サブスクリプション)

③ = ローカル `claude` CLI (claude-agent-sdk 経由, optional extra `agent`)。エージェントは
**専用 MCP shim** (`tsumugin.workbench.agent_mcp`, stdio) 越しに workbench HTTP API を叩く —
人間と同じ custody ガード (ledger/409/422) が全て適用される。

**権限境界 (FR-402)**: 2 段構え。
1. **SafeAction — エージェントが直接実行してよい**: 読み取り (state/viewmodel/ledger/status) と
   ジョブ起動 (refine/sequential/phaseid/multistart/echem)。再実行可能な計算であり
   ledger 追記 + revert 可能なため、自律走行のために許可する。
2. **ModelAction — エージェントが「起票」でき、人間の承認で実行される**: structure apply
   (ReviseStructure)・review 解決・相の追加/除去・精密化設定変更。shim の `propose_*` ツールが
   **承認カード (transcript kind=approval, state=pending) を作るだけ**で、実行は人間が
   `POST /api/approval/{id}` を approve した時のみ。エージェントが散文で頼むのではなく
   ワンクリック承認できる構造化アクションとして起票することで、自律ループを切らさない。
3. **人間専用 (エージェントに口を作らない — 唯一の絶対境界)**: `POST /api/approval/{id}` 自体
   (= 自己承認の禁止) と project ライフサイクル (create/open/close/demo — セッションと ledger の
   すり替えに相当)。

shim のツール表がこの境界の単一情報源であり、逸脱 (特に承認解決ツールの追加) はテストで fail
させる。**「厳密な安全証明」ではなく「人間が最終決定を握る」ことが目的** — 解析は全て
revert 可能なので、過剰な制限より自律性を優先する (2026-07-26 方針)。

### エージェント権限モード (`agent_policy`) — 人間が切り替える

上の 2 段構えは既定 (`approve`) の挙動。**人間はいつでもモードを切り替えられる**。

| モード | ModelAction (structure/review/phase/settings) | project ライフサイクル (create/open/close/demo) |
|---|---|---|
| `approve` (既定) | `propose_*` で起票 → **人間の承認で実行** | 人間専用 |
| `auto` (自動) | `propose_*` が**即時自動適用** (カードは `auto_applied` として記録) | 人間専用 |
| `bypass` (許可をバイパス) | 即時自動適用 | **エージェントにも開放** |

**全モード共通で変わらないもの (安全弁ではなく監査可能性の担保)**:
- ledger 追記 + snapshot は常に記録され **revert 可能** (P2)。auto/bypass でも「何が起きたか」は
  完全に追跡でき、いつでも巻き戻せる。**未決の承認カードも例外ではない**: project ライフサイクル
  (create/open/close/demo) がセッションを差し替える直前、旧セッションに残る pending カード
  (np-/sr-/rv-/pc-/st-) は 1 件ごと `approval_abandoned` として ledger に記録してから破棄される
  (`WorkbenchSession.abandon_pending_approvals`) — 記録は人間の swap 操作をブロックしない。
- **`agent_policy` の変更はエージェントから不可** (shim にツールを作らない) — 自己昇格の禁止。
  自己承認 (`POST /api/approval/{id}`) の禁止と同じ理由で、これがモード分けを意味あるものにする
  唯一の絶対境界。
- **CLI ビルトインツール (Bash/Read/Write/WebFetch 等) は全モードで無効** (`tools=[]`)。
  bypass は「workbench の操作権限」を渡すモードであり、ローカルマシンへのシェルアクセスとは
  別軸 (そちらは revert 不能なので開けない)。

| 呼び出し | 内容 |
|---|---|
| GET `/api/state` | `agent.policy: "approve"\|"auto"\|"bypass"` を含む |
| POST `/api/agent/policy` `{"policy": ...}` | 切替 + **ledger 追記** (`agent_policy_change`)。エージェントのターン実行中は 409。不正値 422 |

UI: AGENT SESSION ヘッダに 3 択セグメント (承認 / 自動 / バイパス)。auto/bypass 選択時は
ヘッダに反転チップで現モードを明示 (「今エージェントが何をできるか」を常に見えるように)。

### `propose_*` ツールと承認カード

| shim ツール | 承認カード action_id | approve 時に実行される操作 |
|---|---|---|
| `propose_structure_revision(sites, rationale)` | `sr-<n>` | `POST /api/structure/apply` 相当 (子スナップショット + ledger) |
| `propose_review_resolution(item_id, action, rationale)` | `rv-<n>` | `ReviewQueue.resolve` (FR-423) |
| `propose_phase_change(op, phase_name, structure_path?, rationale)` | `pc-<n>` | `add_phase` / `remove_phase` |
| `propose_settings_change(two_theta_limits?, background_coeffs?, max_cyc?, rationale)` | `st-<n>` | `update_settings` |
| `list_pending_approvals()` (読み取り) | — | 自分の起票の状態確認 (approve はできない) |

既存の新相カード (`np-<frame>`) と同じ機構。共通規約: 起票時は ledger に `agent_proposal`
(payload に kind/rationale/action)、approve/reject 時に `approval_decision` + 実操作の ledger。
reject でも提案は ledger に残る。approve 時の実行失敗は error dict + カードは pending 復帰
(再試行可)。payload の各引数は他ツールの出力から作れること (§4.5 到達可能性) — sites は
`get_viewmodel().structure.sites`、item_id は `.review[].id`、phase_name は `.project.phases[]`。

| 呼び出し | 内容 |
|---|---|
| POST `/api/transcript/message` | mode=auto かつ agent 利用可能時: メッセージをエージェントセッションへ送り**非同期実行** (従来の記録のみ動作は demo/manual/不可用時のフォールバック)。202 `{"status": "agent_started"}` / 実行中 409 |
| GET `/api/agent/status` | `{"status": "idle"\|"running"\|"failed", "available": bool, "tokens": int, "wall_time_s": float, "error": str\|null}` — tokens/wall は FR-404 (=$ 表示なし)。available=false は CLI/SDK 不在 |
| (transcript) | エージェントのテキスト/ツール呼び出し (kind=agent/tool, args/ret JSON) が実行中に逐次 append される。フロントは running 中 2s で viewmodel を再フェッチ |
| state.agent | tokens/wall_time_s が実測値に。`available` 追加 |

エージェント実行は GSAS ジョブ枠とは独立 (エージェントが起動する refine 等は HTTP 経由で
既存の共有枠 409 に従う)。モデル/ターン数上限は `~/.tsumugin/agent.json` (任意) で設定、
既定は SDK 既定モデル + max_turns 25。

## その他の変更系

| 呼び出し | 成功レスポンス | 副作用 |
|---|---|---|
| POST `/api/hypotheses/{id}/accept` `{"by": "human"\|"agent", "reason": str}` | `{"status": "accepted"\|"recommend_only", ...}` | ledger (エンジン内) |
| POST `/api/revert` `{"hypothesis_id": str, "note": str}` | `{"status": "reverted"}` | ledger |
| POST `/api/review-queue/{id}/resolve` `{"action": "accept"\|"send_back", "note": str}` | `{"item": {...updated}}` | `ReviewQueue.resolve` + ledger |
| POST `/api/structure/apply` `{"sites": [...], "note": str}` | `{"snapshot_id": str, "ledger_index": int}` | SnapshotStore.save + ledger |
| POST `/api/approval/{action_id}` `{"decision": "approve"\|"reject"}` | `{"state": ..., "snapshot_id": str\|null, "ledger_index": int}` | 両経路 ledger、approve のみ snapshot |
| POST `/api/stages/{nn}` `{"action": "release"\|"revert"}` | `{"stage": {...updated}}` | セッション状態 + ledger |
| POST `/api/refine` `{"stages_on"?: {"01": bool, ...}}` | 202 `{"status": "started"}` / 409 (実行中) | 実 `run_auto_rietveld` をバックグラウンドスレッドで起動 + ledger (`refine_request`)。`stages_on` (任意) は staged release recipe の ON/OFF — false の段は recipe から**実際にスキップ**され stage 履歴に現れない (A1: UI のゲートを実 run に反映する唯一の経路)。省略 = 全段既定。不明キーは 422。demo モード (project 未接続) は従来どおり 202 `{"status": "recorded"}` + ledger のみ |
| GET `/api/refine/status` | `{"status": "idle"\|"running"\|"done"\|"failed", "elapsed_s": float\|null, "last_event": str\|null, "error": str\|null, "kind": "refine"\|"phaseid"\|"multistart"\|null}` | — (ポーリング用。完了時はフロントが state/viewmodel を再フェッチ)。`kind` はセルフレビュー指摘 #1: 共有ジョブ枠 (refine/phaseid/multistart) のうち今 (または最後に) 動いているのがどれかを示す — `/api/phaseid/status`・`/api/multistart/status` も同形で `kind` を返す (共通実装)。一度も起動していない `idle` のときのみ `null` |
| POST `/api/transcript/message` `{"text": str}` | `{"message": {...}}` | transcript 追記 |
| GET `/api/ledger` | `{"entries": [{"index", "time", "actor", "text", "hash", "revert_to", "rwp", "bic"}], "verified": true}` | — |
| GET `/api/review-queue` | `{"items": [...]}` | — |
| GET `/api/hypotheses` | viewmodel.hypotheses と同形 | — |

actor は `"AGENT ③" | "MCP ②" | "CORE ①" | "HUMAN" | "GUARD"` (LEDGER タブの色分けキー)。

`rwp` / `bic` (`float | null`) は**そのエントリが精密化結果を伴うときだけ**入る適合度である
(`m7_stage` = 段階ごと、`refine_finished` = 最終)。台帳を時系列に読むだけで「その操作で適合が
どう動いたか」が判るようにするための表示専用フィールドで、payload の**生の事実から導出**する
(`rwp`, `gof`, `n_params`, `n_obs`)。BIC = χ² + n_params·ln(n_obs)、χ² = GOF²·(n_obs − n_params)
— `insitu.anchor.select.frame_bic` および FIT メトリクスの χ² と同一定義 (相数の比較に Rwp を
使わない CLAUDE.md の規律と同じ式を GUI 側でも使う)。適合度を持たないエントリ (モード切替・
承認・設定変更など) は両方 `null` で、UI は**空欄**にする (`―` は「あるはずの値が欠けている」
の意味に予約する)。導出不能 (非有限 GOF、n_obs ≤ n_params、n_obs 欠落) も `null`。

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
