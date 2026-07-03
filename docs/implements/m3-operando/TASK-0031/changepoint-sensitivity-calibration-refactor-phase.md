# TASK-0031 Refactor フェーズ記録: changepoint 感度較正 (Issue #3)

**機能名**: changepoint-sensitivity-calibration / **タスクID**: TASK-0031 / **要件名**: m3-operando
**フェーズ**: Refactor (品質改善) / **実施日時**: 2026-07-04

> すべてのパスはプロジェクトルートからの相対パス。

---

## 1. 結論 (先出し)

**持続カウンタ周りは変更不要 (YAGNI) と判断した。** Green 実装の
`_unmatched_observed_peaks` / `_gate_new_unmatched` / `_position_bin` +
`run()` 逐次状態 `persistence_counter` は、既に単一責任・決定論・十分な日本語コメントを
備えており、機能変更を伴わない安全な改善余地が乏しい。コード品質は「高品質」水準にあり、
functional な変更を避けるリファクタ原則に照らして無改変を選択した。

- テスト: `tests/test_changepoint.py tests/test_sequential_engine.py` → **46 passed** (無改変維持)。
- Lint: `uvx ruff@latest check src/tsumugin/sequential/engine.py src/tsumugin/sequential/changepoint.py`
  → **All checks passed!**

---

## 2. 持続カウンタ周りの凝集度レビュー

対象 (`src/tsumugin/sequential/engine.py`):

| 要素 | 責任 | 評価 |
| --- | --- | --- |
| `run()` の `persistence_counter: dict[int, int]` | 位置ビンごと連続出現の逐次状態保持 | `rwp_history`/`lattice_history` と同格クラスタで一貫 🔵 |
| `_unmatched_observed_peaks(...)` | 未マッチ観測ピーク (位置+高さ) の抽出 | simulate→find_peaks→match_score→unmatched の単一責任 🔵 |
| `_gate_new_unmatched(...)` | 強度ゲート→ビン量子化→連続カウンタ更新→持続ゲート | 単一責任。`prev_counter` を破壊せず新 dict を返す不変スタイルで決定論に寄与 🔵 |
| `_position_bin(...)` | 2θ の決定論ビンキー量子化 | static ヘルパへ分離済み・純関数 🔵 |

- **抽出 (unmatched) と ゲート (gate) の分離は意図的な継ぎ目**であり、両者を融合すると
  可読性・テスト観点の独立性を損なう。融合は不採用。
- `_gate_new_unmatched` の不変更新 (前カウンタを mutate せず `new_counter` を返す) は
  NFR-102 決定論と再実行ビット同一性に資する望ましい形。維持。
- コメントは `comment_template` の水準 (機能概要/実装方針/テスト対応/信頼性レベル) を満たしており、
  追加強化の必要性は低い。

## 3. Green フェーズ提示の改善候補に対する判断 (YAGNI)

| 候補 | 判断 | 理由 (信頼性) |
| --- | --- | --- |
| `_unmatched_observed_peaks` を `tree.py` の未マッチ算出と共通化 | **不採用 (据え置き)** | クロスモジュール結合・依存方向の逆転リスク。無関係な既存テスト面へ波及し「既存テスト無改変 green」(後方互換) を脅かす 🟡 |
| ビン幅定数 `_NEW_PEAK_BIN_WIDTH_DEG` と `SearchConfig.match_tol_deg` の結合 | **不採用 (独立維持)** | 要件は両者を独立に保つ設計。投機的結合は YAGNI 違反 🔵 |
| 強度ゲートと `find_peaks(min_height_frac)` の二重適用整理 | **不採用 (役割分担維持)** | 設計 D7 が別ゲートとして意図した役割分担。冗長に見えるが意図どおり 🔵 |

## 4. セキュリティレビュー

- 【入力面】: 外部入力・ネットワーク・DB・テンプレート描画なし。数値配列処理に閉じる → SQLi/XSS/CSRF 非該当。
- 【0 除算/非有限】: `max_height > 0.0` ガードで相対高さ比較の 0 除算を回避。非有限 chi2 の失敗フレームは
  `continue` で `persistence_counter` 据え置き (漏洩なし, M1 教訓遵守)。
- 【機微情報】: ログ・例外に秘匿情報を含めない。
- **結論**: 重大な脆弱性なし。🔵

## 5. パフォーマンスレビュー

- `_gate_new_unmatched`: 未マッチピーク数 k に対し O(k log k) (`sorted(current_bins)`)。k は小さく実質的影響なし。
- `persistence_counter`: **有界**。非継続ビンは新 dict に載せず脱落するため、活動中ビン数のみを保持し
  フレーム数に対して単調増加しない (メモリリークなし)。
- 支配項は `_unmatched_observed_peaks` の相ごと simulate+find_peaks で、これは TASK-0031 以前と同一計算量。
  探索起動は「発火フレーム数 == 探索回数」(TC-CP-N03) に較正で抑制され、計算量制御 P5 を維持。
- 【テスト実行時間】: 2 秒超の遅いテストは検出されなかった (対象 46 件は即時完了)。
- **結論**: 重大な性能課題なし。🔵

## 6. 参考: ファイルサイズに関する注記 (今回スコープ外)

- `src/tsumugin/sequential/engine.py` は 623 行で 500 行ガイドラインを超過。
- ただし分割は「持続カウンタ凝集度」という本タスク範囲を大きく越える構造変更であり、
  無関係な既存経路 (frame 精密化/採択/系譜組立) に波及して後方互換 green を脅かすため、
  **本 Refactor では実施しない**。将来 engine の責務分割を独立タスクで扱う際の候補として記録する。🟡

## 7. 品質判定

```
✅ 高品質:
- テスト結果: 対象 46 passed 継続成功 (無改変)
- セキュリティ: 重大な脆弱性なし
- パフォーマンス: 重大な性能課題なし・遅いテストなし
- リファクタ品質: 目標 (持続カウンタ凝集度) 達成 = 既に高凝集につき無改変が最適
- コード品質: 適切 (lint clean・十分なコメント)
- ドキュメント: 完成
```

## 8. 次フェーズ要求

`/tsumiki:tdd-verify-complete m3-operando TASK-0031` で完全性検証 (全体 green・完了条件網羅) を実施する。
