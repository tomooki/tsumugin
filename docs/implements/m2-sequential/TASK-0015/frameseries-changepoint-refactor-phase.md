# TDD Refactorフェーズ記録: frameseries-changepoint (TASK-0015)

## 実施日時
2026-07-03

## 対象ファイル
- `src/tsumugin/sequential/series.py` (75 行)
- `src/tsumugin/sequential/changepoint.py` (179 行)
- `src/tsumugin/sequential/__init__.py` (18 行)

## リファクタリング前の状態
- Green フェーズ完了。テスト 23 定義 (実行 24 = FrameSeries 9 / changepoint 14, うち 1 件 parametrize 2 分岐) が全て green。
- 実装はすでに高品質: ヘルパー分割 (`_robust_z` / `_axis_diff_series` / `_lattice_z`)、
  日本語 docstring + 【機能概要/実装方針/テスト対応】+ 🔵🟡 信頼性注記、frozen 値オブジェクト、
  MAD=0 ガードによる非有限値非漏洩、`sorted(keys)` による決定論を Green 時点で具備。

## 改善計画と判断 (YAGNI 準拠・変更不要判断を含む)

| 観点 | 評価 | 対応 |
|------|------|------|
| 可読性 (命名/コメント) | 良好。日本語 docstring と信頼性注記が既に充実 | 変更不要 🔵 |
| 重複コード (DRY) | robust z / 差分列 / 軸集約がヘルパー化済み | 変更不要 🔵 |
| 設計 (単一責任) | series (器) と changepoint (純関数統計) が分離済み | 変更不要 🔵 |
| ファイルサイズ (500 行制限) | 最大 179 行 (changepoint) — 大幅に下回る | 変更不要 🔵 |
| typing import 規約 | `from typing import Mapping, Sequence` は既存 model/backends と一致 | 変更不要 🔵 |
| フォーマット統一 (ruff format) | `_lattice_z` シグネチャが不要改行で 3 行折返し | **改善実施** 🔵 |
| セキュリティ | I/O・外部入力・注入面なし (純計算) | 指摘なし 🔵 |
| パフォーマンス | 窓 W=5 の小規模・O(frames·keys) の median 計算 | 指摘なし 🔵 |

### 実施した改善 (1 件のみ)
`_lattice_z` の関数シグネチャが 100 桁未満 (88 桁) にもかかわらず 3 行に折り返されていたため、
`ruff format` 準拠で 1 行へ集約 (可読性・整形一貫性の向上)。**数値ロジックは一切変更なし** —
Red で較正済みの z 値 (SPIKE_RWP≈201.68 / JUMP_LATTICE≈168.29 / TC-C-B02 境界) を保存するため。

```python
# Before (3 行折返し)
def _lattice_z(
    lattice_history: Sequence[Mapping[str, float]], *, window: int
) -> float:

# After (1 行 / ruff format 準拠)
def _lattice_z(lattice_history: Sequence[Mapping[str, float]], *, window: int) -> float:
```

## セキュリティレビュー結果
- **入力面**: `detect_changepoint` は数値履歴と設定のみを受け取る純関数。外部入力・ファイル I/O・
  ネットワーク・シリアライズ・eval/exec・SQL/シェルなし → 注入系脆弱性の攻撃面なし。
- **数値安全性**: MAD=0 の 0 除算を発火前ガードで回避し、inf/nan を `z`/`reasons`/`triggered` に
  漏らさない (CLAUDE.md「非有限値を漏らさない」/ M1 教訓 / 完了条件⑥)。
- **FrameSeries**: 形状不一致を `__post_init__` で `ValueError` 明示化し不正な器の生成を阻止。
- 重大な脆弱性: **なし**。

## パフォーマンスレビュー結果
- `_robust_z`: `np.median` を 2 回 (中央値・MAD)、窓は末尾 W 要素のみ → O(W log W)。
- `_lattice_z`: 現フレームの存在軸数 × 履歴長の差分計算 → O(keys · frames)。窓 W=5 の逐次呼び出し前提で軽量。
- 決定論のための `sorted(keys)` は軸数 (通常 ≤3) に対する O(k log k) で無視可能。
- メモリ: 窓・差分列とも短命な小配列。ボトルネックなし。
- 重大な性能課題: **なし**。

## テスト実行結果 (リファクタ後)
- `uv run pytest tests/test_sequential_series.py tests/test_changepoint.py -q` → **24 passed** (全 green 継続)。
- `uvx ruff check src/tsumugin/sequential` → All checks passed。
- `uvx ruff format --check src/tsumugin/sequential` → 3 files already formatted (整形完了)。
- 遅いテスト (2 秒以上) の検出: **なし**。
- `describe.skip`/`test.skip` 等によるテスト無効化・除外設定: **なし**。
- 開発時一時ファイル (`debug-*`/`test-*`/`*.tmp`/`*.bak` 等): **検出なし**。

## コメント改善内容
既存の日本語コメント (docstring + 行内【】注記 + 🔵🟡 信頼性注記) は Green 時点で
`comment_template` 要件を満たしており追加改善は不要と判断。整形 1 行化に伴うコメント変更なし。

## 品質判定
✅ 高品質
- テスト結果: Task/pytest で 24 件全て継続成功
- セキュリティ: 重大な脆弱性なし
- パフォーマンス: 重大な性能課題なし
- リファクタ品質: 目標達成 (整形一貫性を確保、数値契約を保存)
- コード品質: 適切なレベル (ヘルパー分割・型注釈・日本語 docstring 完備、全ファイル 500 行未満)
- ドキュメント: 完成
