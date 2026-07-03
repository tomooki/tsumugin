# TDD Refactor フェーズ記録: operando-discrimination (TASK-0032)

## 実施日時

2026-07-04

## 対象

- 実装: `src/tsumugin/operando/discrimination.py` (Green 直後 507 行 → Refactor 後 546 行)
- テスト: `tests/test_discrimination.py` (17 件・**無改変**)

## リファクタリング前の品質確認

- テスト: `uv run pytest tests/test_discrimination.py` → **17 passed** (Green 維持)。
- Lint: `uvx ruff@latest check src/tsumugin/operando/discrimination.py` → All checks passed。
- 遅いテスト: 判別 smoke (`test_single_interval_discrimination_under_thirty_seconds`) は端点のみ
  マルチスタート設計で <30 秒に収まる (性能課題なし)。
- 除外/スキップ: `*.skip` 等の無効化なし。開発時一時ファイルなし。

## 改善計画と実施内容

Green 実装は既に高品質 (詳細な日本語 docstring + 信頼性レベル併記) だったため、**テストの意味を変えない
範囲**で以下の低リスクな構造改善のみを適用した (機能変更なし)。

### 1. 重複除去 (DRY) — 両仮説 Hypothesis 構築の共通化 🔵

- **改善前**: `discriminate_interval` 内で `hyp_single` / `hyp_two_phase` を near-duplicate な
  6 行ブロック × 2 で構築していた (id・区間結果・端点マルチスタートだけが差分)。
- **改善後**: `_build_endpoint_hypothesis(hyp_id, outcome, multistart, start, end) -> Hypothesis`
  ヘルパへ集約。本体は 2 つの短い呼び出しに縮約。
- **効果**: 同形処理の一元化。metrics.multistart 付与ロジックの分岐が 1 箇所に。
- **観点**: 重複除去 / 命名。

### 2. 長大関数の分割 + 命名 — 区間検証の抽出 🟡

- **改善前**: `discriminate_interval` 冒頭に frame_range 検証の inline ガード (9 行)。
- **改善後**: `_validate_frame_range(frame_range, n_frames) -> tuple[int, int]` へ抽出。
  本体は `start, end = _validate_frame_range(frame_range, series.n_frames)` の 1 行に。
- **効果**: フェイルファスト検証に名前が付き独立検証可能。本体先頭が意図明示的な段構成に。
- **観点**: 長大関数の分割 / 命名。

### 3. 特記事項の docstring/コメント妥当性再確認 (変更不要と判断) 🔵

- **仮説 B の wt_frac 不活性 → scale のみ精密化 / BIC は設計 DOF で計上 (ΔBIC 相殺)**:
  `_TWO_PHASE_REFINE_SUFFIXES` / `_TWO_PHASE_MODEL_SUFFIXES` の定数コメント (L46-56 相当) と
  `_refine_interval` / `_model_bic` の docstring で既に十分明確に記述済み。追加変更は不要と判断。
- **B 端成分格子 = 端点マルチスタート最良 basin 代表 (全滅時は逐次端点フォールバック)**:
  `_endpoint_lattice_source` の docstring と本体コメントで既に明確。変更不要と判断。

## セキュリティレビュー

- 純関数オーケストレータ。外部入力の実行・eval・IO・ネットワーク・SQL いずれもなし。
- 入力検証: `_validate_frame_range` で区間契約違反を早期に ValueError 化 (フェイルファスト)。
- バックエンド失敗は例外化せず chi2=inf 結果として縮退 (ガードレール処理)。データ漏洩リスクなし。
- **結論**: 重大な脆弱性なし。

## パフォーマンスレビュー

- 計算量: フレーム数 N に対し O(N) の逐次 refine + 端点 2 × 仮説 2 のマルチスタートのみ
  (全フレームには掛けない)。抽出したヘルパは O(1) で新規コストなし。
- メモリ: 端点相/結果のみ dict 保持 (区間全フレームは保持しない)。
- **結論**: 重大な性能課題なし。smoke (<30 秒) 維持。

## 決定論・非破壊の再確認 (NFR-102 / P2)

- **非破壊**: 入力 `series` / `initial_phases` / `fixed_phases` を破壊しない。`init_a`/`init_b` は
  新規タプル生成。`Ledger.append` は追記のみ、`ReviewQueue.add` は追記型。
- **決定論**: 乱数・時刻・集合反復順に依存する出力なし。唯一の frozenset (`free_params`) は
  `SimulatedBackend._recognized` が `sorted(...)` で並べるためプロセス跨ぎでも順序不変
  (`src/tsumugin/backends/simulated.py` L139)。2 回実行ビット同一テスト green。

## テスト実行結果 (Refactor 後)

- `uv run pytest tests/test_discrimination.py` → **17 passed**。
- `uvx ruff@latest check src/tsumugin/operando/discrimination.py` → All checks passed。

## 品質判定

✅ **高品質**:
- テスト結果: 全 17 件継続成功 (無改変)。
- セキュリティ: 重大な脆弱性なし。
- パフォーマンス: 重大な性能課題なし。
- リファクタ品質: 重複除去 + 関数分割 + 命名を達成 (機能変更なし)。
- ファイルサイズ: 546 行。500 行超だが本コードベースの許容ノルム内
  (`sequential/engine.py` 623 行 / `search/tree.py` 892 行)。オーケストレータの凝集を優先し
  人工的な分割は見送り (ruff の enforced gate は line-length 100・E501 非選択で clean)。
- 日本語コメント: 抽出ヘルパにも【機能概要】【実装方針】+ 信頼性レベルを付与し既存様式と整合。

## 次のステップ

`/tsumiki:tdd-verify-complete m3-operando TASK-0032` で完全性検証を実行する。
