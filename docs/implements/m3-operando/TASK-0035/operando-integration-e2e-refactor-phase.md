# TASK-0035 Refactor フェーズ記録 (operando 公開 API 統合 + E2E)

**要件名**: m3-operando / **タスクID**: TASK-0035 / **フェーズ**: Refactor
**実施日時**: 2026-07-04 / **信頼性**: 🔵 (統合タスク・配線/E2E/ドキュメント)

## 1. リファクタリング方針

本タスクは新規解析ロジックを持たない **統合タスク** (公開 API の re-export 配線 + 公開 API 経由の
E2E 結線検証 + ドキュメント)。Green フェーズで `src/tsumugin/__init__.py` の M3 シンボル re-export と
`tests/test_operando_e2e.py` (18 件) は既に高品質・全 green に到達済み。Refactor では **機能を変えず**
以下 3 観点に絞って品質を仕上げた:

1. `src/tsumugin/__init__.py` の整理 (グルーピング・コメント)
2. `tests/test_operando_e2e.py` の可読性
3. ドキュメント更新 (README M3 節 + `docs/dev/context.md` の M3 反映)

**不変条件の遵守**: テストの意味を変える変更は一切行わない (`__all__` 昇順維持・M0/M1/M2 公開面の
非破壊 REQ-404・re-export は is 同一実体・P2 非破壊性)。git commit はしない。

## 2. 実施した改善

### 2.1 `src/tsumugin/__init__.py` (🔵)
- **改善内容**: import 群の先頭に、各サブパッケージ実体からの re-export であること・サブパッケージ名の
  アルファベット昇順で配置していること・別実装でなく `is` 同一実体であること (REQ-404) を明示する
  グルーピングコメントを 2 行追加。
- **非改変**: import 文・`__all__` の要素/順序は不変 (既存の昇順ソート・85 シンボルを維持)。
- **効果**: 追記時に「どの順序で・なぜ re-export か」が自己文書化され、順序崩れ/二重実装の混入を抑止。

### 2.2 `tests/test_operando_e2e.py` (🔵)
- **判断**: 既に【テスト目的】【テスト内容】【期待される動作】+ 信頼性レベル注記が全 18 件へ付与され、
  module スコープ fixture (`operando_run`) による一気通貫共有・索引規約ヘルパ (`_intervals_from_boundaries`)
  など可読性・実行時間の設計が完了している。テストの意味を変えない範囲で追加すべき改善は無しと判断し、
  **無改変** とした (過剰なコメント追加はノイズになるため回避)。

### 2.3 ドキュメント (🟡 文面は妥当な推測 / 完了条件⑤)
- **README.md**:
  - 状態ブロックへ M3 (operando 解析) を追記。
  - 「使い方 (M3): operando 解析」節を新設 (M2 節と同型)。使用例コードは E2E
    `test_readme_m3_example_executes` (TC-035-10) と同等の公開 API のみで構成し、回帰保護下に置く。
  - アーキテクチャ表へ `tsumugin.multistart` / `tsumugin.operando` / `tsumugin.absorption` を追加、
    見出しを「M0 + M1 + M2 + M3 実装済み範囲」へ更新。
- **docs/dev/context.md**:
  - Overview スコープ・Project Structure (multistart/operando/absorption)・公開 API 段落 (85 件へ更新)・
    Additional Notes の「M3 実装済み」行を追記。スコープ外行を M3+ → M4+ (joint/MCP/MEM/nested/OED/RDB) へ更新。
  - Last updated を 2026-07-04 へ更新。

## 3. セキュリティレビュー

- 統合タスクにつき新規の入力処理・外部 I/O ロジックは追加していない。E2E が通す `read_echem_csv` は
  欠損列を `ValueError` で fail-loud (TC-035-12 で回帰保護)、非有限値は空欄化され CSV へ文字列漏洩しない
  (TC-035-08 で検証)。re-export は名前束縛のみで実行時副作用なし。**新規脆弱性なし**。

## 4. パフォーマンスレビュー

- re-export は import 時の名前束縛のみで実行時オーバーヘッドを増やさない。E2E は module スコープ fixture で
  一気通貫を 1 回だけ実行し、判別は `n_starts=2` の高速 config を用いる設計。TC-035-17 が 1 区間 (N=8) 30 秒
  以内を回帰保護。**重大な性能課題なし**。

## 5. テスト実行結果 (Refactor 後)

- `uvx ruff@latest check src tests` → **All checks passed!**
- `uv run pytest tests/test_operando_e2e.py tests/test_m1_e2e.py tests/test_m2_e2e.py -q` → **50 passed**
  (@gsas 含む。`Error reading {cfgfile}` は GSAS-II の既知無害警告)。
- 全体無退行の最終確認は tdd-verify-complete で `uv run pytest` 実行 (期待 644 passed / 3 skipped)。

## 6. 品質判定

✅ 高品質:
- テスト: 関連テスト全 green・ruff clean。
- セキュリティ / パフォーマンス: 重大課題なし。
- リファクタ品質: 3 観点とも目標達成 (機能不変・テスト意味不変)。
- ドキュメント: README M3 節 + context.md 反映で完了条件⑤へ前進 (検証レポートは verify-complete で作成)。
