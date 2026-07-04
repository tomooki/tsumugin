# TASK-0026 TDD Refactor フェーズ — backends 拡張 (global パラメータ文法 + 吸収補正 v1)

**機能名**: backends-absorption / **タスクID**: TASK-0026 / **要件名**: m3-operando
**フェーズ**: Phase 2 / **実施日**: 2026-07-04 / **ブランチ**: milestone/m3-operando

> すべてのパスはプロジェクトルート相対。信頼性凡例: 🔵 資料依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## 1. リファクタリングの主眼 — REQ-103 字義の充足

Green フェーズでは restraint 幅超過警告 (REQ-103) を **rwp 閾値ベース**
(`_CORRELATION_RWP_THRESHOLD`) のみで実装していた。これは「μt が restraint 中心へ拘束された結果、
強度残差 (rwp) が系統的に残る」潜在的乖離のシグナルであり、**μt が実際に中心から大きく動いた
顕在的逸脱**を字義どおりに判定してはいなかった。

REQ-103 の字義は「**μt 精密化値が restraint 幅を超えて逸脱した場合に警告**」である。そこで:

- 🔵 **一次シグナル (字義)**: `|μt − μt_calc|` が許容幅 `restraint_width` を超えたら警告する
  `_deviation_warning` を新設。
- 🔵 **補完シグナル (残置)**: rwp 閾値ベース判定を `_residual_correlation_warning` として明示分離し、
  一次シグナルが μt=中心近傍で沈黙するケース (μt–scale 相関で μt が中心に張り付く) を補う。

両シグナルは排他でなく、相関リスク (§14) を取りこぼさない**多重シグナル**として共存する。

### 逸脱を独立に検証できることの根拠 (合成ケース)

| ケース | scale | w_r | 中心 | fitted μt | dev | rwp | 発火シグナル |
|---|---|---|---|---|---|---|---|
| T-E04 (既存) | 解放 | 1.0 | 0.2 | 0.209 | 0.009 | 1.83% | rwp のみ (μt が中心へ張り付く) |
| T-E06 (追加) | 固定 | 0.001 | 0.2 | 1.000 | 0.800 | 0.003% | **字義 (幅逸脱) のみ** |

T-E06 は scale を解放しないため μt–scale 相関が起きず、μt はデータ選好 (≈1.0) へ収束し rwp は
極小のまま中心から `restraint_width=0.3` を超えて逸脱する。**rwp 補完シグナルが不発でも字義判定が
単独で発火する**ことを示し、Green の rwp-only 実装では取りこぼしていた逸脱を検出する。

---

## 2. 変更点

### 2.1 `src/tsumugin/absorption/model.py` (🔵 非破壊の末尾フィールド追加)

`AbsorptionConfig` に許容逸脱幅フィールドを追加:

```python
restraint_width: float = 0.3   # |μt − μt_calc| がこれを超えたら相関疑い警告 (REQ-103 字義)
```

- 末尾追加・既定値付きのため全既存生成 (キーワード引数) は無改変で成立 (REQ-404 非破壊)。
- 既定 0.3 は透過セルの実効 μt が概ね O(0.1〜2) の域で「明確に逸脱」とみなせる絶対幅 🟡 設計裁量。
- `from_cell_config` / `empirical` は既定 (0.3) を採用 (明示指定なし)。

### 2.2 `src/tsumugin/backends/simulated.py` (🔵 警告構成の責務分割 + 字義判定追加)

`_build_warnings` を単一責任のヘルパへ分割し、字義判定を一次シグナルとして追加:

- `_deviation_warning(mu_t, center, width) -> str | None`: `|μt − μt_calc| > width` で警告文を返す
  (顕在的逸脱・REQ-103 字義)。
- `_residual_correlation_warning(mu_t, center, rwp) -> str | None`: `rwp > 閾値` で警告文を返す
  (潜在的乖離・補完シグナル。従来ロジックを移設)。
- `_build_warnings`: 経験推定 → 字義逸脱 → rwp 乖離 の決定論的順序で組み立てる。

機能的挙動の変更は「字義逸脱の**追加検出**」のみ。既存の経験推定警告・rwp 警告・無警告条件は不変。

### 2.3 `tests/test_absorption.py` (🔵 逸脱強制ケースの追加)

- `test_fitted_mu_t_beyond_restraint_width_emits_literal_warning` (T-E06): 上表の逸脱強制合成ケース。
  `|fitted μt − 中心| > 0.3` かつ `rwp < 0.5` (補完シグナル不発) かつ warnings に「幅逸脱/逸脱」を含む。
- `test_absorption_config_restraint_width_default_and_explicit` (T-B09): `restraint_width` 既定 0.3 と
  明示上書きの保持を検証。

---

## 3. セキュリティレビュー

- 🔵 **入力信頼境界**: 追加コードは数値 (float) の内部演算のみ。外部入力の解釈・逆シリアライズ・
  I/O・eval・サブプロセスを一切行わない。インジェクション面はゼロ。
- 🔵 **数値安全性**: `restraint_width` は比較にのみ使用。負値でも `abs(...) > width` は破綻せず
  (常に真寄り) fail-loud にはならないが、値オブジェクトは frozen で不変・決定論。
- **結論**: 重大な脆弱性なし。

## 4. パフォーマンスレビュー

- 🔵 **計算量**: 追加処理は精密化 1 回あたり O(1) のスカラ比較 2 回 (abs 差分と rwp 比較) のみ。
  LM ループ本体 (O(cycles·n_obs·n_params)) に対し無視できる。ヘルパ分割による関数呼び出し増も
  精密化完了後 1 回の警告構成時のみで、ホットパス (残差評価/Jacobian) には一切入らない。
- 🔵 **テスト実行時間**: 追加 2 ケースは各 < 0.1s。test_absorption.py 全 28 ケースで高速
  (2 秒超の遅いテストなし。既存の 2.17s は @gsas contract test で本タスク非関連)。
- **結論**: 重大な性能課題なし。

## 5. テスト実行結果

- `uv run pytest tests/test_absorption.py`: **28 passed** (26 定義 + 2 追加)。
- `uv run pytest` (全体回帰): **502 passed, 3 skipped** (505 collected)。
  内訳 = 474 (pre-0026) + 26 (Green) + 2 (Refactor 追加)。既存テストファイル無改変・無退行。
- `uvx ruff check src tests`: **All checks passed!** (line-length 100 / py312)。

## 6. 品質判定

```
✅ 高品質:
- テスト結果: 全 502 passed + 3 skipped で継続成功 (無退行)
- セキュリティ: 重大な脆弱性なし (数値内部演算のみ)
- パフォーマンス: 重大な性能課題なし (O(1) 追加・ホットパス外)
- リファクタ品質: REQ-103 字義を充足 (顕在的逸脱の一次シグナル追加 + rwp 補完の責務分離)
- コード品質: 単一責任ヘルパ化・日本語コメント強化・型注釈完備・ruff clean
- ファイルサイズ: simulated.py 431 行 / model.py 91 行 (いずれも 500 行未満)
```

**次のお勧めステップ**: `/tsumiki:tdd-verify-complete m3-operando TASK-0026` で完全性検証を実行。
