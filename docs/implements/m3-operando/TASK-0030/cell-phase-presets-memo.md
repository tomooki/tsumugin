# TDD開発メモ: cell-phase-presets

## 概要

- 機能名: operando/cell_phases — セル固定相プリセット (FR-312)
- 開発開始: 2026-07-04
- 現在のフェーズ: 完了 (verify-complete 合格)

## 🎯 最終結果 (2026-07-04)
- **実装率**: 100% (12/12 テストケース: TC-N01〜N07 / TC-A01〜A02 / TC-BV01〜BV03)
- **成功率**: 100% (単体 12 passed / 全体 565 passed, 3 skipped, 0 failed, 0 errors)
- **要件網羅率**: 100% (TC-203-01→TC-N01/N05, TC-203-02→TC-N03/BV03, TC-203-03→TC-N06, 完了条件3→TC-N02/BV01/BV02)
- **品質判定**: 合格 (高品質・完全達成)
- **TODO更新**: ✅ 完了マーク追加 (docs/tasks/m3-operando/TASK-0030.md タイトル + 完了条件 3 項目 checkbox)

## 💡 重要な技術学習
### 実装パターン
- frozen dataclass 値オブジェクト (`FixedPhaseSpec` = phase/label) + `MappingProxyType` の読み取り専用プリセット表
  + 純粋関数ヘルパ (`fixed_free_suffixes -> ("scale",)`) の 3 点セット。M0〜M2 の値オブジェクト規約と同型で後続 (TASK-0032/0033) が依存。
- 六方晶の直方近似は orthohexagonal `b = a·√3` (SimulatedBackend の直方 `_d_spacing` に整合させ b 方向反射の a=b 縮退を回避)。
### テスト設計
- 合成データ精密化検証は `SimulatedBackend(peak_fwhm=0.2)` + `two_theta=arange(15,80,0.02)` + `RefinementModel(free_params=param_name(i,"scale"))`
  が有効 (固定相 scale のみ解放で活物質相 scale 収束・固定相 lattice 不変を同時検証)。
- 「scale のみ解放」の backend 担保は free_params に lattice を入れないことで `_recognized` が認識せず不変 → TC-BV03 で境界確認。
### 品質保証
- 定数プリセットはユーザ入力・I/O なしで攻撃面ゼロ、`MappingProxyType`+`frozen` で定数汚染不可。過剰な防御を足さない判断が有効。
- YAGNI: 3 プリセット固定の投機的テーブル駆動化は見送り、可読性を優先。

## 関連ファイル

- 元タスクファイル: `docs/tasks/m3-operando/TASK-0030.md`
- 要件定義: `docs/implements/m3-operando/TASK-0030/cell-phase-presets-requirements.md`
- テストケース定義: `docs/implements/m3-operando/TASK-0030/cell-phase-presets-testcases.md`
- 実装ファイル: `src/tsumugin/operando/cell_phases.py` (Green で新規作成)
- テストファイル: `tests/test_cell_phases.py` (新規, 12 ケース)

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-04

### テストケース

正常系 7 (TC-N01〜N07) / 異常系 2 (TC-A01〜A02) / 境界値 3 (TC-BV01〜BV03) の計 12 件。
プリセット取得・格子値照合・scale のみ解放・frozen 不変性・決定論・固定相込み合成精密化・直方近似 (b=a·√3) を網羅。

### 期待される失敗

`from tsumugin.operando.cell_phases import ...` が `ModuleNotFoundError` を送出し、
`tests/test_cell_phases.py` が collection error で全ケール失敗 (対象モジュール未実装)。確認済み。

### 次のフェーズへの要求事項

- `src/tsumugin/operando/cell_phases.py` に `FixedPhaseSpec` / `CELL_PHASE_PRESETS` / `fixed_free_suffixes` を実装。
- 格子は直方近似 (六方晶は b=a·√3)、docstring に近似の注意を明記。
- `operando/__init__.py` に re-export 追加。

## Greenフェーズ（最小実装）

### 実装日時

2026-07-04

### 実装方針

`FixedPhaseSpec` (frozen dataclass) / `CELL_PHASE_PRESETS` (MappingProxyType の Be/Al/graphite 3 プリセット,
直方近似格子) / `fixed_free_suffixes` (常に `("scale",)`) を `src/tsumugin/operando/cell_phases.py` に実装。
六方晶は `b = a·√3` の orthohexagonal 近似、立方晶 Al は `a=b=c`。docstring に直方近似・文献出典・実回折との
ずれの注意を明記。`operando/__init__.py` に re-export 追加。

### テスト結果

- `uv run pytest tests/test_cell_phases.py` → 12 passed。
- `uv run pytest` → 565 passed, 3 skipped。
- `uvx ruff@latest check src tests` → All checks passed!。

### 課題・改善点

- 格子定数が docstring と実装本体に重複。Refactor で名前付き定数化・出典コメント集約の余地。
- プリセット追加時の一貫性向上のためテーブル駆動化の余地 (機能影響なし)。

## Refactorフェーズ（品質改善）

### リファクタ日時

2026-07-04

### 改善内容

**構造・機能の変更なし (YAGNI に基づく変更不要判断)**。Green 実装は品質判定基準を既に充足しており、
Green フェーズの改善候補 2 件 (格子定数の名前付き定数化 / テーブル駆動化) はいずれも YAGNI 該当のため見送った:
- 格子値はプリセット表の 1 箇所のみに出現し隣接コメントで出典明示済 → 定数化は間接化を増やすだけで実重複を除去しない。
- プリセットは Be/Al/graphite の 3 種で確定 → テーブル駆動化は将来追加を仮定した投機的抽象化 (器のみ提供が本タスクスコープ)。

### セキュリティレビュー結果

重大な脆弱性なし。ユーザ入力・外部 I/O・eval/network なし (攻撃面なし)。`MappingProxyType` + `frozen=True` で
定数汚染不可。未定義キーは `KeyError` で明示失敗。過剰な防御コードの追加は不要と判断。

### パフォーマンスレビュー結果

重大な性能課題なし。プリセット構築はロード時 O(1) の 1 回のみ。`fixed_free_suffixes` はリテラルタプル返却 O(1)。
`math.sqrt(3.0)` は `_SQRT3` に 1 度だけ確定。追加最適化 (キャッシュ等) 不要。

### テスト結果

- `uv run pytest tests/test_cell_phases.py` → 12 passed 継続。
- `uvx ruff@latest check src tests` → All checks passed!。
- 全体回帰 (565 passed / 3 skipped) は verify-complete フェーズで確認。

### 品質評価

✅ 高品質 — テスト継続成功 / 脆弱性なし / 性能課題なし / 型注釈・命名・日本語コメント・ファイルサイズ (149行) 全て適切 /
決定論・非破壊・コア依存 (stdlib のみ) を維持。詳細は `cell-phase-presets-refactor-phase.md` 参照。
