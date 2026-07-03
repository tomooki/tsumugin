# TASK-0012 store/serialization Greenフェーズ記録

**日時**: 2026-07-03 / **要件名**: m2-sequential / **機能名**: serialization

## 実装ファイル

- `src/tsumugin/store/serialization.py` (新規, 148行): `phase_to_dict` / `phase_from_dict` +
  内部ヘルパ `_finite_or_none` / `_finite_map` / `_value_or_default`
- `src/tsumugin/store/__init__.py`: `phase_from_dict` / `phase_to_dict` を re-export

## 実装方針と判断理由

- 🔵 **固定 dict スキーマ**: 要件定義 §2.1 のキー名・ネスト構造 (lattice / lifecycle をネスト dict、
  既定角 90.0 も明示出力、空 Mapping は {}) をそのまま実装。TASK-0014 が依存するため固定。
- 🔵 **非有限 → None (M1 教訓)**: 全 float フィールド (lattice a〜gamma / sigma 値 / scale /
  wt_frac / occupancies 値 / confidence) をローカル `_finite_or_none` で純化。
  `search/tree.py` は import しない (レイヤ逆依存回避)。
- 🟡 **前方/後方互換**: `phase_from_dict` は `data.get()` による明示キー取り出しで未知キーを無視、
  欠損 optional は既定 (scale=1.0 / wt_frac=None / occupancies={} / lifecycle=None / sigma={} /
  角=90.0) で補完。`_value_or_default` は `is None` 判定で 0.0 等の falsy 有限値を潰さない (B-06)。
- 🔵 **純関数・決定論**: 入力無変更、乱数不使用。`_canonical_json` 互換 (N-06 で検証済み)。

## テスト実行結果

- `uv run pytest tests/test_serialization.py -v` → **15 passed** (N-01〜N-06 / E-01〜E-03 / B-01〜B-06 全 green)
- `uv run pytest` (全体) → **253 passed, 3 skipped** (無退行)
- `uvx ruff@latest check src tests` → **All checks passed!**

## 品質判定

✅ **高品質**: 全テスト成功 / 実装シンプル (148行 ≪ 800行) / モック・スタブなし /
コンパイル・lint エラーなし / 機能的問題なし。

## 課題・改善点 (Refactorフェーズ候補)

- `_value_or_default` が関数定義より後方 (`phase_from_dict` の下) にある — 定義順の整理。
- lattice の必須キー a/b/c が None の場合の扱い (現状は素通し) — 契約明文化の検討。
- docstring とインラインコメントの粒度統一。
