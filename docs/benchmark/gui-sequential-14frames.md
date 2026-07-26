# GUI workbench SEQUENCE 検証 — CaTeO3 全 14 フレーム実データ

milestone/gui-workbench-v3b の SEQUENCE (V2b B1-B3) を、GUI 経路 (`POST /api/project/frames` →
`POST /api/sequential`) のみで CaTeO3 全 14 フレーム実データ
(`scratchpad/cateo3_frames14/NB-LM01MO_{030..420}.XRDML`, Jana2020 Cookbook Example 02.6 "CaTeO3
cyclic") で検証した記録。① `run_sequential_rietveld`/`run_anchored_sequential` を直接呼ばず、
`tests/workbench/test_sequential_14frames_gsas.py` (`@pytest.mark.gsas`) の FastAPI TestClient 経由
で駆動している — GUI が実運用スケールで本当に通るかの検証が目的 (既知挙動は
`docs/benchmark/testdata/m9/README.md`)。

## 設定

- instrument: `docs/benchmark/testdata/m9/cateo3/cateo3_CuKa.instprm` (Cu Kα1 単色)
- 初期相: alpha CaTeO3·H₂O (`alpha_CaTeO3_H2O.cif`) のみ (delta は anchored テストでのみカタログに追加)
- `POST /api/project/settings {"background_coeffs": 24, "max_cyc": 20}` — 既定 (6/12) は実験室 X 線
  では frame030 単体でも不足することが `scratchpad/cateo3_full_mp_gsas.py` の先行検証で分かっており、
  同一設定を GUI 経路でも明示適用した
- two_theta_limits: 各フレーム [12, 70]°

## forward モード (alpha 単相, phase_id 無効)

GUI の `POST /api/sequential {"mode": "forward"}` は ② `sequential_rietveld` に `phase_id` を渡さない
設計 (api-contract.md — 新相追加は B5 承認カード経由のみ、提案≠適用)。したがって本走は **alpha 単相の
まま全 14 フレームを逐次精密化**する。

| # | 温度 / ℃ | Rwp (%) | changepoint |
|---|---|---|---|
| 0 | 30 | **12.57** | false |
| 1 | 60 | 23.71 | false |
| 2 | 90 | 40.76 | false |
| 3 | 120 | **57.40** | false |
| 4 | 150 | 30.38 | false |
| 5 | 180 | 35.39 | false |
| 6 | 210 | 38.38 | false |
| 7 | 240 | 46.97 | false |
| 8 | 270 | 51.59 | false |
| 9 | 300 | 54.39 | false |
| 10 | 330 | 54.53 | false |
| 11 | 360 | 54.68 | false |
| 12 | 390 | 54.79 | false |
| 13 | 420 | 53.10 | false |

frame030 12.57% / frame060 23.71% / frame120 57.40% は `docs/benchmark/testdata/m9/README.md` の
既知値 (12.57 / 23.7 / 57%) と一致。**alpha 単相のまま昇温すると実サンプルが脱水して Rwp が
上がる**という物理どおりの挙動で、GUI 経路が実運用スケール 14 フレームで通ることを確認した。
sequence viewmodel は frames 14 件 + charts 3 本 (rwp / lattice a,c / phase_fraction) が正しく埋まる。

- 所要時間: 約 12 分 (14 フレーム, Cu Kα1 実験室 X 線, 背景 24 項 / max_cyc 20)
- B5 新相提案承認カード: **7 件 (np-1〜np-7)** — 新相候補フレームで承認カードが立つ (提案≠適用: エンジンは相を自動追加しない)
- 進捗ハートビート (`sequential_progress` ledger エントリ): **33 件** (15 秒間隔、`sequential running (mode=…, n_frames=14, elapsed=…s)`)

## anchored モード (frame0=alpha, frame13=delta)

| # | 温度 / ℃ | Rwp (%) | 相 (fraction) |
|---|---|---|---|
| 0 | 30 | 12.57 | alpha 1.0 |
| 1 | 60 | 23.71 | alpha 1.0 |
| 2 | 90 | 40.76 | alpha 1.0 |
| 3 | 120 | 57.40 | alpha 1.0 |
| 4 | 150 | **30.08** | **delta 1.0** |
| 5 | 180 | 29.42 | delta 1.0 |
| 6 | 210 | 23.26 | delta 1.0 |
| 7 | 240 | **17.77** | delta 1.0 |
| 8 | 270 | 29.86 | delta 1.0 |
| 9 | 300 | 27.97 | delta 1.0 |
| 10 | 330 | 25.11 | delta 1.0 |
| 11 | 360 | 21.33 | delta 1.0 |
| 12 | 390 | 16.02 | delta 1.0 |
| 13 | 420 | **13.48** | delta 1.0 |

**転移を正しく捕捉**: frame3→frame4 (120→150 ℃) で alpha から delta へ切り替わり、以降 delta 側の
Rwp が forward (alpha 固定, 53.10%) に対し **frame420 で 13.48%** まで改善する。これは README の
「実測 Jana delta で clean delta フレーム (frame420 単相) Rwp 13.48%」と一致し、M10 のアンカー基準
双方向解析が GUI 経路でも設計どおり機能することを示す。

- anchors: `fr000` (alpha) / `fr013` (delta) — どちらも `crossover: false` (crossover は segments 側に載る)
- segments (crossover): `fr000–fr013`: forward=alpha / backward=delta, rwp `57.40 / 30.08`, total_bic `525676`, selected **`mixed`** (区間内で前方 alpha → 後方 delta が交代する解が総 bic 最小)
- 所要時間: 約 10 分

## GUI 経路で見つけた欠陥と修正

### 進捗可視化 (`進捗 = ledger (frame k/N)` 契約の未達)

api-contract.md §逐次/operando は「進捗 = ledger (frame k/N)」を明記しているが、実装は
`sequential_request` (開始) → (無音) → `sequential_finished`/`sequential_failed` (終了) のみで、
実行中は ledger が一切動かなかった。② `sequential_rietveld`/`anchored_sequential` は同期呼び出しで
フレーム単位の進捗を返さず、① 内部の `Ledger`(`m9_seq_frame` 等)は結果に畳まれるだけで実行中は
外から見えない。frame k/N を厳密に配線するには ①/② 層に session ledger を注入する変更が必要
(本タスクの編集範囲外 — `src/tsumugin/workbench/` 限定)。

**修正 (workbench 限定, session.py のみ)**: `WorkbenchSession.request_sequential` の runner を
バックグラウンドスレッドのハートビートでラップし、`_SEQUENTIAL_HEARTBEAT_INTERVAL_S` (既定 15s)
間隔で `sequential_progress` ledger エントリ (`elapsed_s`) を追記するようにした。①②の呼び出し契約
(instrument spec 経由の runner 構築) は一切変更していないため既存の runner 注入テストに影響しない。
厳密な `frame k/N` ではなく `elapsed_s` のみの縮退だが、「動いているか固まっているか」を LEDGER タブ
から判別できるようにした。フレーム粒度の進捗は ①/② 層 (`run_sequential_rietveld`/
`run_anchored_sequential` の `ledger=` 注入を `sequential_rietveld`/`anchored_sequential` 経由で
session に橋渡しする)への追加配線が必要で、次段の課題として残す。

## 追加/変更ファイル

- `tests/workbench/test_sequential_14frames_gsas.py` (新設): forward/anchored 14 フレーム gated テスト
- `src/tsumugin/workbench/session.py`: `request_sequential` ハートビート追加 (`sequential_progress`
  ledger kind + `_text_for_kind`/`_ACTOR_BY_KIND` 追加)
- `tests/workbench/test_session.py`: ハートビートの高速単体テスト追加
- 本ファイル
