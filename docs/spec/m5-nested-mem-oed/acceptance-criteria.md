# m5-nested-mem-oed 受け入れ基準

**作成日**: 2026-07-04
**関連**: [requirements.md](requirements.md) / [user-stories.md](user-stories.md) / [interview-record.md](interview-record.md)

**【信頼性レベル凡例】**: 🔵 仕様書/既存実装に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

> 検証は原則 SimulatedBackend の合成データ + 外部依存モック。実サンプラ (dynesty/ultranest)・実バイナリ
> (Dysnomia)・PyBOED は `@pytest.mark.nested` / `@pytest.mark.mem` / `@pytest.mark.oed` 相当で分離し、
> 未導入環境では自動 skip する。境界・入力生成・提案スキーマ・較正評価は SDK/バイナリ非依存で通常 pytest により網羅する。
> TC 採番は M5 ローカル (TC-501〜) で振る。

---

## REQ-001〜003: Laplace evidence バックエンド 🔵

- [ ] **TC-501-01**: `LaplaceBackend` が `EvidenceBackend` Protocol (name / score) に準拠し `EvidenceResult` を返す 🔵
  - **Given** RefinementMetrics **When** `LaplaceBackend().score(metrics)` **Then** `EvidenceResult(backend="laplace", value=...)` が返る
- [ ] **TC-501-02**: `laplace` の value が IC 系と同一符号規約 (小さいほど良い) で rank に混在比較できる 🔵 *REQ-003*
- [ ] **TC-501-03**: Hessian が特異/取得不能なら BIC 近似へフォールバックし警告を残す 🟡 *REQ-002/EDGE-005*

## REQ-004〜009: nested sampling バックエンド 🔵

- [ ] **TC-502-01**: `NestedBackend` が外部サンプラ未導入で実行されると `NestedUnavailableError` を送出する 🔵 *REQ-005/EDGE-001*
  - **Given** dynesty/ultranest 未導入 **When** nested 実行 API 呼び出し **Then** `NestedUnavailableError`、コア import は成功
- [ ] **TC-502-02**: `import tsumugin` が nested extra なしで成功する (コア依存 numpy のみ) 🔵 *REQ-403*
- [ ] **TC-502-03** (@nested): nested が `EvidenceResult.value` (=-logZ 相当) と `logz_err` を返す 🔵 *REQ-006/REQ-007*
- [ ] **TC-502-04** (@nested): サンプラー種固定で 2 回実行し logZ が誤差 (logz_err) 範囲内で一致する 🔵 *REQ-009/NFR-102/EDGE-014*
- [ ] **TC-502-05**: nested 事前分布が精密化 restraint から自動構成され、手動オブジェクトで上書きできる 🔵 *REQ-008/REQ-301*

## REQ-010〜013/102/201: 階層的裁定 🔵

- [ ] **TC-503-01**: 木探索・枝刈りが bic のまま実行され nested により書き換えられない (探索は bic 固定) 🔵 *REQ-010/REQ-201*
- [ ] **TC-503-02**: `close_competitor=True` (ΔBIC<10) の競合のみが nested 再裁定対象に選ばれる 🔵 *REQ-011*
  - **Given** rank 結果に僅差競合と非競合が混在 **When** 階層裁定 **Then** 競合のみ nested・非競合は bic 一次確定
- [ ] **TC-503-03**: 僅差競合が無い場合 nested 再裁定を発動せず bic 一次判定を最終結果とする 🔵 *REQ-102/EDGE-003*
- [ ] **TC-503-04**: フル nested 運転設定で全生存仮説が nested 裁定される (bic 一次スキップ) 🔵 *REQ-012/EDGE-004*
- [ ] **TC-503-05**: 階層的裁定の bic/nested の振り分けが理由付きで ledger に記録される 🔵 *REQ-013/NFR-105*

## REQ-101/405: nested 時間上限・Laplace 代替 🔵

- [ ] **TC-504-01**: nested 裁定が時間上限 (既定 30 分) 超過で打ち切り + Laplace 代替 + 警告 (例外化しない) 🔵 *REQ-101/EDGE-002/NFR-103*
  - **Given** 時間上限を極小に設定したモック nested **When** 超過 **Then** 打ち切り・Laplace value・警告が返る
- [ ] **TC-504-02**: 打ち切り時も ledger.verify() が True・結果は縮退で返り解析全体が止まらない 🔵 *REQ-101/REQ-401*

## REQ-014〜017/106: 確率較正 🔵

- [ ] **TC-505-01**: 仮説確率が softmax + 温度較正で出力され temperature を設定できる 🔵 *REQ-014*
- [ ] **TC-505-02**: 確率出力に用いた evidence backend 名が応答/レポートに含まれる (BIC 近似 vs logZ 明記) 🔵 *REQ-015/NFR-004*
- [ ] **TC-505-03**: reliability diagram / ECE を正解ラベル付きデータから決定論的に計算する 🔵 *REQ-016/REQ-017*
- [ ] **TC-505-04**: 較正評価が bic と nested を別系列で出力する 🔵 *REQ-016/REQ-106/EDGE-012*

## REQ-018〜023: MEMBackend 境界・入力生成 🔵

- [ ] **TC-506-01**: `MEMBackend` Protocol が定義され RefinementBackend/EvidenceBackend と同型の交換可能境界である 🔵 *REQ-018*
- [ ] **TC-506-02**: Dysnomia 未導入で MEM 実行 API が `MEMUnavailableError` へ縮退する (M4 errors.py と整合) 🔵 *REQ-019/REQ-020/EDGE-006*
- [ ] **TC-506-03**: 精密化済み仮説から F_obs (位相モデル由来) を抽出し MEM 入力を自動生成する 🔵 *REQ-021*
- [ ] **TC-506-04**: X線 → 電子密度・中性子 → 核密度の密度種別が probe に応じて選択される 🔵 *REQ-022*
  - **Given** joint 検証済み仮説 (X線+中性子) **When** MEM 入力生成 **Then** probe ごとに正しい密度種別が選ばれる
- [ ] **TC-506-05**: MEM 入力生成が決定論的 (反射順/F_obs 順固定) でビット同一である 🔵 *REQ-023/NFR-102*

## REQ-024〜026/107/202: MEM-Rietveld 反復 🔵

- [ ] **TC-507-01**: MEM-Rietveld 反復が既定オフである (明示有効化なしでは反復しない) 🔵 *REQ-024*
- [ ] **TC-507-02**: 反復の各サイクルが子スナップショットとして追記され親仮説/joint 結果は不変 🔵 *REQ-025/REQ-202/NFR-005*
- [ ] **TC-507-03**: 反復が収束判定 or 最大反復到達で停止し停止理由が ledger 記録される 🔵 *REQ-026/EDGE-009*
- [ ] **TC-507-04**: 反復発散 (密度負値/R 悪化) 時に当該サイクルを子スナップショットに残し停止・ledger 記録 (破壊しない) 🟡 *REQ-107/EDGE-008*

## REQ-027〜029: MEM 出力 🔵

- [ ] **TC-508-01**: 密度マップ (VESTA 互換 .grd 等) を出力する 🔵 *REQ-027*
- [ ] **TC-508-02**: 指定サイト/結合経路に沿った 1D/2D 断面を出力する 🔵 *REQ-028*
- [ ] **TC-508-03**: ボンド経路の最小密度値 (伝導パス評価) を抽出・出力する 🔵 *REQ-029*

## REQ-030/031/103: MEM 適用ガード 🔵

- [ ] **TC-509-01**: 推奨条件 (joint 済み単相/主相支配) を判定できる 🔵 *REQ-030*
- [ ] **TC-509-02** (最重要): 多相/低統計への適用時に信頼性警告を出すが MEM 実行は継続・仮説除外しない 🔵 *REQ-031/REQ-103/EDGE-007*
  - **Given** 多相/低統計データ **When** MEM 実行 **Then** 警告付きで実行継続・どの仮説も除外されない (Dara 教訓)

## REQ-032: MEM フレームスポット解析 🔵

- [ ] **TC-510-01**: シーケンシャルの指定フレーム (充電端/放電端/転移前後) に MEM をスポット実行できる 🔵 *REQ-032*
- [ ] **TC-510-02**: スポット解析が spot 単位で完結し全フレーム自動反復を既定にしない 🔵 *REQ-405*

## REQ-033/034/104: MCP run_mem 実体化 🔵

- [ ] **TC-511-01**: `mcp/mem.py::run_mem_boundary` が MEMBackend へ委譲するよう接続され M4 placeholder スキーマと整合 🔵 *REQ-033*
  - **Given** MEMBackend 実装済み session **When** run_mem 呼び出し **Then** 密度マップパス等の素の型 dict が返る
- [ ] **TC-511-02**: run_mem が破壊的操作を伴わない (子スナップショット追記のみ・削除/上書きなし) 🔵 *REQ-034/P2*
- [ ] **TC-511-03**: MEMBackend 未導入で run_mem MCP を呼ぶと `MEMUnavailableError` が MCP エラー dict へ変換されクラッシュしない 🔵 *REQ-104/EDGE-006*
- [ ] **TC-511-04**: run_mem MCP が MEM 実行結果を素の型 dict で返す (json.dumps allow_nan=False 安全) 🔵 *REQ-034/EDGE-013*

## REQ-035〜038/105: OED / 測定フィードバック 🔵

- [ ] **TC-512-01**: 僅差競合時に判別測定提案 (高統計再測定/追加温度点/中性子測定/組成分析) を情報利得順の JSON で生成する 🔵 *REQ-035*
- [ ] **TC-512-02**: OED 提案が非破壊 (ledger 追記のみ・状態変更なし・accepted/rejected 化しない) 🔵 *REQ-037*
- [ ] **TC-512-03**: 僅差競合 (close_competitor/ΔlogZ<閾値) が無い場合は提案 JSON が空配列・状態変更なし 🔵 *REQ-038/EDGE-010*
- [ ] **TC-512-04**: PyBOED 未導入で獲得関数接続 API を呼ぶと `OEDUnavailableError` へ縮退し提案生成 (v1) は動作する 🔵 *REQ-036/REQ-105/EDGE-011*
- [ ] **TC-512-05**: 提案ごとに推定情報利得スカラを JSON に含められる (v1 簡易近似) 🟡 *REQ-304*

## REQ-203: final_selection_mode 整合 🔵

- [ ] **TC-513-01**: human モードでは nested 再裁定/OED 提案/MEM 結果が推奨提示に留まり accepted 化は人間操作のみ 🔵 *REQ-203/FR-402*

## REQ-401〜406: 制約・非破壊・決定論 🔵

- [ ] **TC-514-01**: nested 裁定・MEM 反復 (子スナップショット)・OED 提案・較正評価を通しても ledger.verify() が True 🔵 *REQ-401/NFR-105*
- [ ] **TC-514-02**: 全新機能に削除/上書き API が存在しない (P2 の API 表面走査) 🔵 *REQ-401/NFR-101*
- [ ] **TC-514-03** (決定論): MEM 入力生成/OED 提案/較正評価が同一入力でビット同一 (反射順/提案順/ビン順固定) 🔵 *REQ-402/NFR-102*
- [ ] **TC-514-04**: コア import が numpy のみに依存 (nested/mem/oed extra なしで tsumugin が import 可能) 🔵 *REQ-403*
- [ ] **TC-514-05**: 新規シンボル (LaplaceBackend/NestedBackend/MEMBackend/MEMResult/OEDProposal/CalibrationReport 等) が `__all__` へ末尾追加され昇順が維持される 🔵 *REQ-404*
- [ ] **TC-514-06**: Dysnomia/dynesty/ultranest/pyboed の contract test がバージョン固定で分離される 🔵 *REQ-406/NFR-106*

## 統合 E2E

- [ ] **TC-515-01**: nested 一気通貫 — bic 探索 → 生存仮説 rank → 僅差競合抽出 → nested 再裁定 (logZ±誤差) → 確率較正 → ledger verify、まで完走 🔵
- [ ] **TC-515-02** (@nested): 実 dynesty/ultranest で 2 仮説の nested 裁定 smoke (30 分上限内) 🟡 *NFR-103*
- [ ] **TC-515-03**: MEM 一気通貫 — joint 検証済み仮説 → MEM 入力生成 → (モック MEM) 密度マップ/断面/最小密度 → 適用ガード警告 → 子スナップショット → ledger verify 🔵
- [ ] **TC-515-04** (@mem): 実 Dysnomia バイナリで単相 joint 済み仮説の MEM smoke 🟡 *FR-602/NFR-106*
- [ ] **TC-515-05**: OED 一気通貫 — 僅差競合検出 → 判別測定提案 JSON (情報利得順) → ledger 追記のみ (非破壊) 🔵
- [ ] **TC-515-06**: MCP E2E — submit_analysis → 僅差競合 → run_mem (MEMBackend 実体化) → 密度マップ dict → ledger verify 🔵

---

## テストケースサマリー

| カテゴリ | 件数 |
|---|---|
| Laplace evidence | 3 |
| nested バックエンド | 5 |
| 階層的裁定 | 5 |
| nested 時間上限・Laplace 代替 | 2 |
| 確率較正 | 4 |
| MEMBackend 境界・入力生成 | 5 |
| MEM-Rietveld 反復 | 4 |
| MEM 出力 | 3 |
| MEM 適用ガード | 2 |
| MEM フレームスポット | 2 |
| MCP run_mem 実体化 | 4 |
| OED / 測定フィードバック | 5 |
| final_selection_mode 整合 | 1 |
| 制約・非破壊・決定論 | 6 |
| 統合 E2E | 6 |
| **合計** | **57** |

### 信頼性レベル分布
- 🔵: 51 (89%) / 🟡: 6 (11%) / 🔴: 0 — **品質評価**: 高品質
