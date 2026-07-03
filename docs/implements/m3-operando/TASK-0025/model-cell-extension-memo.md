# TDD開発メモ: model 拡張 (CellConfig / CellLayer / BeamConfig / channel kind / metrics.multistart / MuCalculator)

## 概要

- 機能名: model 拡張 (CellConfig / CellLayer / BeamConfig / channel kind 拡張 / metrics.multistart / MuCalculator)
- 開発開始: 2026-07-04
- 現在のフェーズ: Verify-Complete (完全性検証 完了) ✅

## 🎯 最終結果 (2026-07-04)
- **実装率**: 100% (21/21 テストケース)
- **スコープ内テスト**: 21 passed (tests/test_model_m3.py)
- **全体テスト**: 474 passed / 3 skipped (既存 453 + 新規 21、無退行)
- **ruff**: clean (src tests, line-length 100)
- **要件網羅率**: 100% (完了条件 4/4)
- **品質判定**: ✅ 合格 (高品質)
- **TODO更新**: ✅ TASK-0025.md 完了マーク + checkbox 4 件を更新

## 関連ファイル

- 元タスクファイル: `docs/tasks/m3-operando/TASK-0025.md`
- 要件定義: `docs/implements/m3-operando/TASK-0025/model-cell-extension-requirements.md`
- テストケース定義: `docs/implements/m3-operando/TASK-0025/model-cell-extension-testcases.md`
- タスクノート: `docs/implements/m3-operando/TASK-0025/note.md`
- 実装ファイル: `src/tsumugin/model/{cell,channel,hypothesis,__init__}.py` (cell.py 新設・他は非破壊拡張)
- テストファイル: `tests/test_model_m3.py`

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-04

### テストケース

テストケース定義の 21 件 (正常系 10 / 異常系 4 / 境界値 7) に 1:1 対応。
一覧・信頼性分布・Green 実装指示の詳細は
`docs/implements/m3-operando/TASK-0025/model-cell-extension-red-phase.md` を参照。

- CellLayer/BeamConfig/CellConfig: 生成・等価比較・frozen・既定値縮退・`dataclasses.asdict`
  シリアライズ (N-01〜N-06 / E-01〜E-03 / B-01〜B-03 / B-06)
- ChannelKind 拡張: voltage 生成 + value_for、4 新 kind 網羅、temperature 後方互換 smoke
  (N-07 / B-07 / B-04)
- RefinementMetrics.multistart: 明示付与生成、最小生成で既定 None (N-08 / B-05)
- MuCalculator Protocol / XraylibMuCalculator: 構造的適合、mu_t が NotImplementedError
  (N-09 / E-04)
- re-export: model パッケージからの 5 シンボル解決 + `__all__` 収載 (N-10)

### テストコード

`tests/test_model_m3.py` (全文はテストファイル参照。書式は `tests/test_model_m2.py` に準拠、
ruff line-length 100 clean)

### 期待される失敗

`uv run pytest tests/test_model_m3.py` → collection 時 ImportError で全 21 テストがエラー:

```
E   ImportError: cannot import name 'BeamConfig' from 'tsumugin.model'
```

回帰確認: `uv run pytest --ignore=tests/test_model_m3.py` → 453 passed, 3 skipped (既存テスト無退行)。

### 次のフェーズへの要求事項

1. `src/tsumugin/model/cell.py` 新設 — CellLayer / BeamConfig / CellConfig (frozen dataclass 3 種) +
   MuCalculator Protocol + XraylibMuCalculator (mu_t → NotImplementedError)。
2. `ChannelKind` Literal 末尾に voltage/current/capacity/composition を追加 (本体無改変)。
3. `RefinementMetrics` 末尾 (evidence の後ろ) に `multistart: Mapping[str, int] | None = None` を追加。
4. `model/__init__.py` に新 5 シンボルを import + `__all__` 追加。
5. 回帰ゲート: 既存 453 passed / 3 skipped を無改変で維持 (REQ-404 非破壊)。

## Greenフェーズ（最小実装）

（未実施）

## Greenフェーズ（最小実装）

### 実施内容

21 テストを green にする最小実装を完了 (cell.py 新設 / channel.py・hypothesis.py・__init__.py 非破壊拡張)。
詳細は `src/tsumugin/model/{cell,channel,hypothesis,__init__}.py` を参照。

### 課題 (Refactor へ持ち越し)

`CellConfig.layers` に `_LayerTuple` (tuple==list を成立させる equality ハック) を導入していた。
原因は N-06 / B-06 のテスト定義の矛盾 (asdict が layers を list にすると誤って期待していた)。

## Refactorフェーズ（品質改善）

### 実施日時

2026-07-04

### 改善内容

- **`_LayerTuple` equality ハックを完全除去** — `dataclasses.asdict` は Python 仕様上 tuple 型を保持する
  (list へ変換しない) ため、「asdict で layers が list になる」を期待する N-06 / B-06 が誤りだった。
  該当テストの期待値を Python 仕様 (tuple) に理由コメント付きで修正し、`CellConfig.layers` を素の tuple に復帰。
  `__post_init__` も削除し、`tuple == list` は常に False という == の対称性を回復。
- 詳細は `model-cell-extension-refactor-phase.md` を参照。

### テスト・品質

- `uv run pytest tests/test_model_m3.py` → 21 passed。`uvx ruff check` clean。
- 品質判定: ✅ 高品質 (ハック除去・対称性回復・cell.py 129→98 行)。
