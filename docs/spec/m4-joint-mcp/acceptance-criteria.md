# m4-joint-mcp 受け入れ基準

**作成日**: 2026-07-04
**関連**: [requirements.md](requirements.md) / [user-stories.md](user-stories.md) / [interview-record.md](interview-record.md)

**【信頼性レベル凡例】**: 🔵 仕様書/既存実装に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

> 検証は原則 SimulatedBackend の合成データ。@gsas は joint E2E smoke 1 本のみ。
> MCP は SDK 非依存のツール実処理関数を通常 pytest で網羅し、SDK 依存アダプタは `@pytest.mark.mcp` 等で分離。

---

## REQ-001〜003: 中性子・マルチヒストグラム取り込み 🔵

- [ ] **TC-401-01**: `HistogramRef(probe="neutron_cw")` / `probe="neutron_tof"` が生成でき、既存 xray と共存する 🔵
  - **Given** 中性子 CW/TOF の probe 指定 **When** HistogramRef を生成 **Then** probe/instprm_ref/bank_id が保持される
- [ ] **TC-401-02**: `TofBankParams` (DIFC/DIFA/ZERO) が生成でき、HistogramRef へ非破壊追加されている 🔵
  - **Given** バンク別 DIFC 系 **When** HistogramRef に付与 **Then** 既存フィールドは不変・末尾追加で後方互換
- [ ] **TC-401-03**: 1 Frame に X線 + 中性子 (+複数バンク) 複数 HistogramRef を保持できる 🔵
- [ ] **TC-401-04**: `TofBankParams` シリアライズが往復対称 (phase_to/from_dict 拡張の無退行) 🟡

## REQ-004〜007: joint 精密化 🔵

- [ ] **TC-402-01**: `JointRefinementModel` が構造共有 free_params とヒスト独立 free_params を分離保持する 🔵
  - **Given** X線+中性子 2 ヒスト **When** joint モデル構築 **Then** 格子/占有率は共有・scale/bg/profile はヒスト別
- [ ] **TC-402-02**: SimulatedBackend で 2 ヒスト χ² 合算の joint 精密化が収束し、共有構造の真値を回収する 🔵
- [ ] **TC-402-03**: joint 結果がヒスト別 Rwp/scale と共有構造 (±σ) を単一 RefinementResult に集約する 🟡 *REQ-006*
- [ ] **TC-402-04**: 1 ヒストの精密化失敗が chi2=inf に変換され joint 全体はクラッシュしない 🔵 *EDGE-001*
- [ ] **TC-402-05** (決定論): joint 一式が 2 回実行でビット同一 (ヒスト順固定) 🔵 *NFR-102*

## REQ-008/009/301: ヒストグラム重み 🔵

- [ ] **TC-403-01**: 既定で統計重みが適用される 🔵
- [ ] **TC-403-02**: 経験重み (信頼度スカラ) で上書きでき、ヒスト寄与が変わる 🔵 *REQ-301*
- [ ] **TC-403-03**: σ の由来 (共分散/ヒスト重み) がレポート/警告に明示される 🔵 *NFR-107*

## REQ-010〜012/103/104: コントラスト占有率解放推奨 🔵

- [ ] **TC-404-01**: |f_norm − b_norm| > 閾値のサイトが検出され、コントラスト十分と判定される (中性子 b 静的テーブル参照) 🔵
- [ ] **TC-404-02**: joint データがある場合のみ占有率解放が戦略へ追加提案される 🔵 *REQ-011*
- [ ] **TC-404-03**: 単一ヒスト (joint なし) では推奨が発動しない 🔵 *REQ-104/EDGE-004*
- [ ] **TC-404-04**: 全サイトで閾値未満 → 提案空・警告なく続行 🟡 *REQ-103/EDGE-003*
- [ ] **TC-404-05**: 推奨がサイトと理由付きで ledger に記録される 🔵 *REQ-012*
- [ ] **TC-404-06**: 推奨は提案のみで自動適用・自動採択しない (占有率が勝手に解放されない) 🔵 *REQ-011*

## REQ-013/014/202: 探索プライマリ・検証 joint 🔵

- [ ] **TC-405-01**: 木探索がプライマリヒストグラム 1 本で実行される (HypothesisTreeSearch 再利用) 🔵
- [ ] **TC-405-02**: 生存仮説のみが joint 検証精密化に渡る (探索段は joint 化されない) 🔵 *REQ-014*
- [ ] **TC-405-03**: joint 検証中もプライマリ探索結果は不変 (joint は探索を書き換えない) 🔵 *REQ-202*

## REQ-015〜020/105: ChemPlausibility 🔵

- [ ] **TC-406-01**: `ChemPlausibility` Protocol・`PlausibilityResult{score[0,1],rationale,source}`・`SynthesisContext` が定義される 🔵
- [ ] **TC-406-02**: v1 最小ルール (大気下の単体アルカリ金属を降格) が該当相に低スコアを返す 🔵 *REQ-017*
- [ ] **TC-406-03**: 複数モジュールのスコアが重み付き幾何平均で合成される 🔵 *REQ-018*
- [ ] **TC-406-04** (最重要): 低スコア相は rank で順位が下がるが**候補から除外されない** (rank に残る) 🔵 *REQ-019/EDGE-005*
- [ ] **TC-406-05**: ChemPlausibility 未登録時は降格なしの素の evidence 順位 🟡 *REQ-105/EDGE-006*
- [ ] **TC-406-06**: 1 モジュールが score=0 を返すと幾何平均で降格が伝播する (除外はしない) 🟡 *EDGE-007*
- [ ] **TC-406-07**: `PhaseRef` が生成でき score へ渡せる (PhaseInstance.phase_ref と整合) 🟡 *REQ-020*

## REQ-021〜025/101/102/106/201: MCP Server 🔵

- [ ] **TC-407-01**: 8 ツール (submit_analysis/list_hypotheses/compare_hypotheses/accept_hypothesis/revert/get_trajectory/export_gpx/run_mem) の実処理関数が存在する 🔵
- [ ] **TC-407-02**: 各ツール実処理が M0〜M3 資産へ委譲する (submit→pipeline, accept/revert→FinalSelectionEngine, get_trajectory→Trajectory, export_gpx→export.gpx, list/compare→SearchResult/rank) 🔵
- [ ] **TC-407-03**: `accept_hypothesis`/`revert` が final_selection_mode を同一適用する 🔵 *REQ-023*
- [ ] **TC-407-04**: `revert` が superseded 化 (追記型) で、accept 履歴が残り件数が減らない 🔵 *REQ-024/P2*
- [ ] **TC-407-05**: human モードで agent による `accept_hypothesis` が accepted 化を拒否し推奨提示に留まる 🔵 *REQ-106/REQ-201/EDGE-010*
- [ ] **TC-407-06**: MCP 経由の submit/accept/revert/mode 切替が理由付きで ledger に記録される 🔵 *REQ-025*
- [ ] **TC-407-07**: `run_mem` が明示エラー (NotImplementedError 相当) or プレースホルダを返し、破壊的操作を伴わない 🔵 *REQ-101/EDGE-008*
- [ ] **TC-407-08**: MCP SDK 未導入でサーバ起動 API が friendly error に縮退し、ツール実処理関数は動作する 🔵 *REQ-102/EDGE-009*
- [ ] **TC-407-09**: MCP ツールに破壊的操作 (削除/上書き) が存在しない (API 表面の走査) 🔵 *REQ-024/NFR-101*
- [ ] **TC-407-10**: `export_gpx` を GSAS-II 未導入で呼ぶと GSASUnavailableError が MCP エラーへ変換されクラッシュしない 🟡 *EDGE-011*

## REQ-401〜405: 制約・非破壊・決定論 🔵

- [ ] **TC-408-01**: joint 昇格・コントラスト提案・ChemPlausibility 降格・MCP 操作を通しても ledger.verify() が True 🔵 *REQ-401/NFR-105*
- [ ] **TC-408-02**: 全新機能に削除/上書き API が存在しない (P2) 🔵 *REQ-401*
- [ ] **TC-408-03** (決定論): joint/コントラスト/スコア合成/MCP 応答が同一入力でビット同一 🔵 *REQ-402/NFR-102*
- [ ] **TC-408-04**: コア import が numpy のみに依存 (mcp/xraylib なしで tsumugin が import 可能) 🔵 *REQ-403*
- [ ] **TC-408-05**: 新規シンボルが `__all__` へ末尾追加され昇順が維持される (test_m4_symbols_sorted) 🔵 *REQ-404*

## 統合 E2E

- [ ] **TC-409-01**: joint 一気通貫 — プライマリ探索 → 生存仮説 joint 検証 (X線+中性子) → コントラスト推奨 →
      ChemPlausibility 降格 → 最終選択 → ledger verify、まで完走 🔵
- [ ] **TC-409-02** (@gsas): GSASIIBackend で 2 ヒスト joint の smoke 🔵
- [ ] **TC-409-03**: MCP E2E — submit_analysis → list_hypotheses → compare_hypotheses → accept_hypothesis (agent) →
      revert → get_trajectory → export_gpx を実処理関数経由で通し、ledger verify 🔵
- [ ] **TC-409-04** (NFR-001): 2 ヒスト joint 検証精密化が 30 秒以内 🟡

---

## テストケースサマリー

| カテゴリ | 件数 |
|---|---|
| 中性子・マルチヒスト取り込み | 4 |
| joint 精密化 | 5 |
| ヒストグラム重み | 3 |
| コントラスト占有率解放推奨 | 6 |
| 探索プライマリ・検証 joint | 3 |
| ChemPlausibility | 7 |
| MCP Server | 10 |
| 制約・非破壊・決定論 | 5 |
| 統合 E2E | 4 |
| **合計** | **47** |

### 信頼性レベル分布
- 🔵: 38 (81%) / 🟡: 9 (19%) / 🔴: 0 — **品質評価**: 高品質
