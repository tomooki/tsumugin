# m2-sequential 受け入れ基準

**作成日**: 2026-07-03
**関連**: [requirements.md](requirements.md) / [user-stories.md](user-stories.md) / [interview-record.md](interview-record.md)

**【信頼性レベル凡例】**: 🔵 仕様書に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

> 検証は原則 SimulatedBackend の合成シーケンス (格子/scale を軸に沿って変化させたフレーム列) で行う。
> GSAS-II 依存の検証は @gsas 1 本 (E2E smoke) のみ。

---

## REQ-001/002: warm start 逐次精密化 🔵

### Given/When/Then
- Given: 格子 a が線形膨張する合成 20 フレーム
- When: SequentialEngine.run(series)
- Then: 各フレームの精密化格子が真値を追跡し、フレーム i の初期値がフレーム i−1 の結果に一致

- [ ] **TC-101-01**: 線形膨張 20 フレームで格子トラジェクトリが真値 ±0.01 Å を追跡 🔵
- [ ] **TC-101-02**: warm start 継承の検証 — spy backend でフレーム i の入力 phases == フレーム i−1 の出力 🔵
- [ ] **TC-101-03**: 継承対象設定 (lattice のみ継承等) が機能する 🟡
- [ ] **TC-101-04** (決定論): 同一入力 2 回で全トラジェクトリがビット同一 🔵 *REQ-402*
- [ ] **TC-101-05** (EDGE-001): 空フレーム列 → 空トラジェクトリ・例外なし 🔵
- [ ] **TC-101-06** (EDGE-101): 単一フレーム → 長さ 1 のトラジェクトリ 🔵
- [ ] **TC-101-07** (EDGE-002): 中間フレームが chi2=inf 失敗 → 警告記録 + 最後の成功フレームから継続 🟡

## REQ-003/101: changepoint 検出と局所木探索 🔵

- [ ] **TC-102-01**: 中間フレームで相 B が出現する合成シーケンスで、当該フレーム近傍が changepoint 判定される 🔵
- [ ] **TC-102-02**: changepoint フレームでのみ HypothesisTreeSearch が呼ばれる (呼び出し回数を spy で検証) 🔵 *EDGE-104 含む*
- [ ] **TC-102-03**: 局所木探索が新相 B を含む仮説を採択し、以後のフレームは B 込みで継続 🔵
- [ ] **TC-102-04**: 変化のない滑らかなシーケンスで changepoint ゼロ 🔵
- [ ] **TC-102-05** (EDGE-103): 全フレーム changepoint でも完走する 🟡
- [ ] **TC-102-06**: 複合指標 — 格子ジャンプのみ / 残差跳ねのみ / 未マッチピークのみ、それぞれ単独で検出できる 🟡

## REQ-004/201: 相ライフサイクル + ヒステリシス 🔵

- [ ] **TC-103-01**: 相 B が frame 10 で出現 → birth_frame=10 (ヒステリシス確定後) 🔵
- [ ] **TC-103-02**: 相 A が frame 15 で消滅 → death_frame=15 🔵
- [ ] **TC-103-03**: 1 フレームだけの偽出現 (点滅) は birth と認定されない (N=3 ヒステリシス) 🔵
- [ ] **TC-103-04** (REQ-201): death 直後のヒステリシス窓内再出現で death 取り消し 🔵

## REQ-005: トラジェクトリ出力 🔵

- [ ] **TC-104-01**: トラジェクトリに軸値・相ごと格子/scale/wt_frac・Rwp・changepoint・lifecycle が含まれる 🔵
- [ ] **TC-104-02**: to_csv() が stdlib csv で読み戻せるファイルを生成し、行数 = フレーム数 🔵
- [ ] **TC-104-03**: CSV に非有限値が漏れない (失敗フレームは空欄/None 表現) 🟡 *M1 レビュー教訓*

## REQ-006/007/008: 高温モード 🔵

- [ ] **TC-105-01**: ExternalChannel(temperature) の frame→T 同期がトラジェクトリに反映される 🔵
- [ ] **TC-105-02** (EDGE-102): チャネル欠損フレームは軸値 None + 警告 (例外なし) 🟡
- [ ] **TC-105-03**: 線形熱膨張 + 転移ジャンプの合成データで、ベースライン係数が真値近傍・
      逸脱フレームが正しく分離される 🔵
- [ ] **TC-105-04**: 相分率が T で遷移する合成データで midpoint が真値 ±1 フレーム間隔、
      onset < midpoint、σ > 0 🔵
- [ ] **TC-105-05** (決定論): 転移温度推定が 2 回実行でビット同一 🔵

## REQ-010/011/012/401: 永続化 🔵

- [ ] **TC-106-01**: PersistentLedger へ append → 再オープン → verify() True + エントリ全量一致 🔵
- [ ] **TC-106-02**: 再オープン後の append でハッシュチェーンが正しく連結 (verify True) 🔵
- [ ] **TC-106-03**: PersistentSnapshotStore の save → 再オープン → revert で状態復元 🔵
- [ ] **TC-106-04** (EDGE-003): ファイル 1 行改竄 → verify() False + 明示エラー、ファイル無変更 🔵
- [ ] **TC-106-05**: 削除・上書き API が存在しない (hasattr 否定, in-memory 版と同一検証) 🔵
- [ ] **TC-106-06**: 既存エンジンに PersistentLedger を注入して M0/M1 経路が無改変で動く 🔵 *REQ-012*
- [ ] **TC-106-07**: JSONL が追記のみで成長する (書き込み前後の先頭バイト列不変) 🔵 *NFR-203*

## REQ-013/014/015/102/103/104: 最終選択 2 モード 🔵

- [ ] **TC-107-01** (agent): 明確な最良仮説 → 自動 accepted、accepted_by="agent"、根拠 ledger 記録 🔵
- [ ] **TC-107-02** (agent+僅差): close_competitor あり → accepted 化せず暫定裁定 + Review Queue 追加 🔵
- [ ] **TC-107-03** (human): 推奨のみ提示され accepted 化されない。human accept API で accepted_by="human" 🔵
- [ ] **TC-107-04**: モード切替が ledger に記録される 🔵
- [ ] **TC-107-05** (REQ-202): accept 済み仮説の差し戻し → superseded + 履歴保持 🟡
- [ ] **TC-107-06**: エスカレーション 4 条件 (高R/未知相/僅差/ガード3連続) がそれぞれ Queue に入る 🔵
- [ ] **TC-107-07**: Review Queue は追記型 (resolve はマーク追記、削除 API なし) 🔵
- [ ] **TC-107-08** (EDGE-004): 裁定対象ゼロ → accept なし + エスカレーションのみ 🟡

## 統合 E2E

- [ ] **TC-108-01**: 昇温合成シーケンス (熱膨張 + frame 途中で相転移) の一気通貫 —
      逐次精密化 → changepoint → 局所探索で新相 → lifecycle → 転移温度 → agent 裁定 →
      永続 ledger verify() True → CSV 出力、まで完走 🔵
- [ ] **TC-108-02** (@gsas): GSASIIBackend で短い 3 フレーム逐次精密化が完走する (smoke) 🔵
- [ ] **TC-108-03** (NFR-001/REQ-403): 合成 100 フレーム (changepoint なし) が 60 秒以内 🟡

---

## テストケースサマリー

| カテゴリ | 件数 |
|---|---|
| 逐次精密化 (REQ-001/002) | 7 |
| changepoint/局所探索 | 6 |
| ライフサイクル | 4 |
| トラジェクトリ | 3 |
| 高温モード | 5 |
| 永続化 | 7 |
| 2 モード | 8 |
| 統合 E2E | 3 |
| **合計** | **43** |

### 信頼性レベル分布
- 🔵: 33 (77%) / 🟡: 10 (23%) / 🔴: 0 — **品質評価**: 高品質
