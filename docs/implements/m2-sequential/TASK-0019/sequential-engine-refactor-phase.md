# TASK-0019 Refactor フェーズ記録 — SequentialEngine

**要件名**: m2-sequential / **タスクID**: TASK-0019 / **機能名 (英)**: sequential-engine
**対象実装**: `src/tsumugin/sequential/engine.py` / **テスト**: `tests/test_sequential_engine.py` (18 件)
**実施日**: 2026-07-03

---

## 1. リファクタリング方針

Green フェーズ完了時点で engine.py は既に日本語 docstring・信頼性マーカー (🔵🟡🔴)・
【…】タグ付きインラインコメントを備えた高品質状態であった。YAGNI に基づき、機能変更を伴わない
以下 2 点の**可読性・DRY 改善**のみを実施 (それ以外は「変更不要」と判断)。

## 2. 実施した改善

### 改善 1: 量子化ヘルパの一元化と docstring 根拠の集約 (DRY / 🟡 NFR-102)
- **課題**: 6 桁量子化 (`round(x, 6)`) が `run()` 内 rwp 履歴と `_lattice_map` の 2 箇所に重複し、
  同一の rationale (robust z の尺度不変性ゆえノイズフロアジッタが偽 changepoint を生む → 履歴のみ量子化)
  が二重記述されていた。
- **改善**: モジュール定数 `_HISTORY_QUANTIZE_DIGITS = 6` に rationale を集約し、静的ヘルパ
  `_quantize_history(value)` を新設。`run()` の rwp 量子化と `_lattice_map` の a/b/c 量子化を
  同ヘルパへ委譲。`_lattice_map` は `@classmethod` 化し `{axis: cls._quantize_history(...)}` で簡潔化。
- **効果**: 量子化桁と根拠が 1 箇所に集約。記録用 (record.rwp / record.phases) の full precision 保持は不変。

### 改善 2: `run()` のフェーズ分解 — frame 精密化 (D2 2 段構え) の抽出 (可読性 / 🔵 D2)
- **課題**: `run()` が約 180 行。frame0 staged / 後続 warm start direct の分岐 (18 行) が
  ループ本体に埋め込まれ、first_frame_report 設定・evidence 比較源選択と混在していた。
- **改善**: 非公開 frozen dataclass `_FrameRefinement` (精密化結果の正規化束) と
  メソッド `_refine_frame(...)` を新設し、2 段構えの精密化ロジックを抽出。`run()` 側は
  `fr = self._refine_frame(...)` の 1 呼び出し + フィールド展開に簡素化。staged 経路のみ
  `staged_report` を、後続経路のみ `direct_result` を持たせ、`run()` の分岐意図を明示化。
- **効果**: `run()` ループが短縮され「精密化 → 失敗継続 → changepoint → 探索採択 → 記録」の
  フェーズ構造が読み取りやすくなった。両経路の出力が同一形に正規化され下流分岐が単純化。

## 3. セキュリティレビュー
- 入力は数値配列 (2θ / 強度) と dataclass のみ。外部入力の eval/exec・パス操作・ネットワーク・
  SQL・シリアライズなし。`orchestration="native"` は副作用前に早期 `NotImplementedError`。
- 非有限 (inf/NaN) は `_num_or_none` / 失敗フレーム分岐で下流へ漏らさない (M1 教訓)。
- **結論**: 新規脆弱性なし。攻撃面の増加なし。

## 4. パフォーマンスレビュー
- 抽出はメソッド呼び出し 1 段の追加のみで計算量 (フレーム数 × direct refine) 不変。
- `_lattice_map` の dict 内包表記化は 3 要素固定で無視できるコスト。
- SE-B04 (100 フレーム < 60 秒 smoke) は継続 green。
- **結論**: 性能退行なし。

## 5. テスト実行結果
- `uv run pytest tests/test_sequential_engine.py -q` → **18 passed** (リファクタ前後で同一)。
- 決定論テスト SE-B02 (2 回実行ビット同一) green ゆえ、抽出が挙動を保存していることを保証。
- `uvx ruff check src/tsumugin/sequential/engine.py` → All checks passed (line-length 100)。

## 6. 品質評価
- ファイルサイズ: 552 行 (sibling `search/tree.py` 886 行に対し十分小さく、密な日本語 docstring
  前提の当プロジェクト規範内)。
- **総合: ✅ 高品質** — テスト全 green・脆弱性なし・性能退行なし・DRY / 可読性向上・機能変更なし。
