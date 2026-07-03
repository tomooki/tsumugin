# TDD開発メモ: store/serialization

## 🎯 最終結果 (2026-07-03 検証完了)

- **実装率**: 100% (15/15 テストケース: N-01〜N-06 / E-01〜E-03 / B-01〜B-06)
- **スコープ内テスト**: 15 passed (0.71s、遅いテストなし)
- **全体回帰**: 253 passed, 3 skipped (10.95s、スコープ外失敗なし)
- **完了条件**: 4/4 達成 (①N-01 ②B-01 ③N-03/E-01/E-02/E-03 ④B-03)
- **品質判定**: 合格 (高品質) / **TODO更新**: ✅完了マーク追加 (docs/tasks/m2-sequential/TASK-0012.md)

### 💡 技術学習 (再利用ポイント)
- **非有限 → None 契約 (M1 教訓)**: 全 float フィールドをローカル `_finite_or_none` で純化し
  `json.dumps(allow_nan=False)` を通す。上位 `search/tree.py` を import せずレイヤ逆依存を回避。
- **前方/後方互換 from_dict**: `data.get()` の明示キー取り出しで未知キー無視、欠損 optional は
  `_value_or_default` (`is None` 判定で 0.0 等 falsy 有限値を潰さない) で既定補完。
- **リファクタ**: private ヘルパ 3 関数を冒頭に集約し「ヘルパ群 → 公開 API」構成へ統一 (機能無変更)。

## 概要

- 機能名: store/serialization — `phase_to_dict` / `phase_from_dict`
- 要件名: m2-sequential / タスクID: TASK-0012
- 開発開始: 2026-07-03
- 現在のフェーズ: 完了 (Refactor 完了)

## 関連ファイル

- 要件定義: `docs/implements/m2-sequential/TASK-0012/serialization-requirements.md`
- テストケース定義: `docs/implements/m2-sequential/TASK-0012/serialization-testcases.md`
- Redフェーズ記録: `docs/implements/m2-sequential/TASK-0012/serialization-red-phase.md`
- 実装ファイル (未作成): `src/tsumugin/store/serialization.py`
- テストファイル: `tests/test_serialization.py`

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-03

### テストケース

テストケース定義 15 件 (正常系 6 N-01〜N-06 / 異常系 3 E-01〜E-03 / 境界値 6 B-01〜B-06) に
1:1 対応する pytest 関数を `tests/test_serialization.py` に作成。書式は `tests/test_model_m2.py` を範とし、
【テスト目的】【テスト内容】【期待される動作】と 🔵/🟡 信頼性レベルの日本語コメントを付す。
roundtrip は `==` で厳密比較、JSON 安全性は `json.dumps(d, allow_nan=False)` が例外を出さないことで検証。
決定論確認 (N-06) は `tsumugin.store.ledger._canonical_json` を私的 import。

### 期待される失敗

`tsumugin.store.serialization` 未実装のため collection 時に
`ModuleNotFoundError: No module named 'tsumugin.store.serialization'` が発生し全 15 テストがエラー。
ruff (line-length 100) は passed。

### 次のフェーズへの要求事項

`src/tsumugin/store/serialization.py` を標準ライブラリのみで新規作成:
- `phase_to_dict`: 固定 dict スキーマ + 非有限 float の None 化 (ローカル `_finite_or_none`) + Mapping の素 dict コピー。
- `phase_from_dict`: 明示キー取り出しで未知キー無視 + 欠損 optional の既定補完 + lattice/lifecycle 再構築。
- レイヤ制約 (`search/tree.py` を import しない)・非破壊・決定論を遵守。

## Greenフェーズ（最小実装）

### 実装日時

2026-07-03

### 実装方針

- `src/tsumugin/store/serialization.py` を標準ライブラリのみで新規作成 (148行)。
- `phase_to_dict`: 要件定義 §2.1 の固定スキーマ + ローカル `_finite_or_none` / `_finite_map` で
  非有限 float を None 化 (M1 教訓) + Mapping を素 dict へコピー。純関数・決定論。
- `phase_from_dict`: `data.get()` の明示キー取り出しで未知キー無視 (前方互換) +
  欠損 optional の既定補完 (後方互換、`_value_or_default` は `is None` 判定) +
  lattice/lifecycle を `LatticeParams` / `PhaseLifecycle` として型復元。
- `store/__init__.py` に `phase_from_dict` / `phase_to_dict` を re-export。
- レイヤ制約遵守 (`search/tree.py` を import しない)。既存 API 無改変 (非破壊)。

### テスト結果

- `uv run pytest tests/test_serialization.py -v` → 15 passed (全 15 ケース green)
- `uv run pytest` (全体) → 253 passed, 3 skipped (無退行)
- `uvx ruff@latest check src tests` → All checks passed!

### 課題・改善点

- `_value_or_default` の定義位置 (使用箇所より後方) の整理。
- lattice 必須キー a/b/c が None の場合の契約明文化 (現状は素通し)。
- 詳細は `serialization-green-phase.md` 参照。Refactorフェーズで対応。

## Refactorフェーズ（品質改善）

### 実施日時

2026-07-03

### 改善内容

- YAGNI に従い機能変更を伴わない可読性改善 1 件のみ適用:
  `_value_or_default` を末尾 (`phase_from_dict` の後) から他ヘルパ (`_finite_or_none` / `_finite_map`) と
  同じモジュール冒頭へ移動し、「private ヘルパ群 → 公開 API」のトップダウン構成へ統一。ロジック無変更。
- 見送り (変更不要判断): lattice 必須キー a/b/c None の契約明文化 (新規挙動追加のため YAGNI) /
  docstring 粒度統一 (既に高品質)。

### セキュリティレビュー結果

外部 I/O・eval・SQL なし。`data.get()` 明示キー取り出しで未知キー無視 (属性汚染なし)。
非有限は None 化し `json.dumps(allow_nan=False)` 純データのみ出力。重大な脆弱性なし。

### パフォーマンスレビュー結果

O(n) 単一走査 (dict 内包表記)、`dict()` コピー 1 回のみ、純関数・決定論。重大な性能課題なし。
テスト 0.73s (2 秒超の遅いテストなし)。

### 最終コード

`src/tsumugin/store/serialization.py` (141 行)。ヘルパ 3 関数を冒頭に集約後、`phase_to_dict` / `phase_from_dict`。

### テスト結果

- `uv run pytest tests/test_serialization.py -q` → 15 passed
- `uvx ruff@latest check src/tsumugin/store/serialization.py` → All checks passed!

### 品質評価

✅ 高品質: 全 15 テスト継続成功 / ruff クリーン / 141 行 / モック・スタブなし /
重大なセキュリティ・性能課題なし / 純関数・決定論。詳細は `serialization-refactor-phase.md` 参照。
