# TASK-0030 Refactor フェーズ記録: operando/cell_phases — セル固定相プリセット (FR-312)

**機能名**: cell-phase-presets / **タスクID**: TASK-0030 / **要件名**: m3-operando
**実装ファイル**: `src/tsumugin/operando/cell_phases.py` (149 行) + `src/tsumugin/operando/__init__.py` (re-export)
**リファクタ日時**: 2026-07-04

---

## 0. 総括 — 構造変更なし (YAGNI に基づく変更不要判断)

Green フェーズ実装は既に品質判定基準の各項目を満たしており、**機能・構造の変更は行わなかった**
(タスク指示「YAGNI、変更不要判断可」に基づく)。Green フェーズで挙げた 2 件の改善候補はいずれも
YAGNI 該当のため見送った (下記「改善候補の評価」参照)。テストの継続 green と静的解析 clean を確認済み。

---

## 1. テスト実行結果 (リファクタ前 = 現状の確認)

- 単体: `uv run pytest tests/test_cell_phases.py` → **12 passed** (TC-N01〜N07 / TC-A01〜A02 / TC-BV01〜BV03)。
- Lint: `uvx ruff@latest check src tests` → **All checks passed!**。
- 実行時間: 単体スイートは高速 (2 秒以上の遅いテストなし)。全体回帰は verify-complete フェーズで実施。
- テスト無効化なし: `describe.skip` / `it.skip` / `test.skip` 等の無効化・`testPathIgnorePatterns` 相当の除外なし。
- 開発時一時ファイルなし: `debug-*` / `test-*.tmp` / `*.bak` / `*.orig` 等の残置ファイルなし。

## 2. セキュリティレビュー

- **入力経路なし**: ユーザ入力・外部 I/O・ファイル読込・ネットワーク・`eval`/`exec`・SQL・シェル呼出を一切持たない。
  モジュールレベル定数と純粋関数のみ。攻撃面 (attack surface) が存在しない。🔵
- **定数汚染耐性**: `CELL_PHASE_PRESETS` は `MappingProxyType` で読み取り専用化し、要素の `FixedPhaseSpec` は
  `frozen=True` でフィールド再代入不可。共有される定数が実行時に破壊されない (TC-A01 で検証)。🔵
- **未定義キーの明示失敗**: 未定義プリセット参照は標準 Mapping の `KeyError` で沈黙せず停止 (TC-A02)。🔵
- 結論: **重大な脆弱性なし**。追加の入力検証を要する経路が無いため、防御コードの追加も不要 (過剰防御を避ける)。

## 3. パフォーマンスレビュー

- **構築コスト**: プリセット 3 種をモジュールロード時に 1 度だけ構築 (O(1))。以降は定数参照のみで再計算なし。🔵
- **`fixed_free_suffixes`**: リテラルタプル `("scale",)` を返す O(1)。spec 非依存で分岐・ループなし。🔵
- **`_orthohexagonal` / `_cubic`**: import 時に計 3 回呼ばれるだけ。`math.sqrt(3.0)` は `_SQRT3` に 1 度だけ確定。🔵
- 結論: **重大な性能課題なし**。計算量・メモリともに最適。キャッシュ等の追加最適化は不要。

## 4. 改善候補の評価 (Green フェーズ課題への対応)

| # | Green フェーズ候補 | 判断 | 理由 (YAGNI) |
|---|---|---|---|
| 1 | 格子定数のマジックナンバーを名前付き定数化 | **見送り** 🟡 | 各格子値はコード上 **プリセット表の 1 箇所のみ**に出現し、隣接インラインコメントで出典・意味を明示済。docstring 出現はドキュメントであり実コードの重複ではない。名前付き定数への抽出は使用箇所から値を 1 段引き離し間接化を増やすだけで、実重複を除去しない。可読性はむしろ現状が上。 |
| 2 | 近似方針のテーブル駆動化 (材料→結晶系→格子) | **見送り** 🔴 | プリセットは Be/Al/graphite の 3 種で確定 (器のみ提供、追加 API は本タスク非スコープ)。将来のプリセット追加を仮定した投機的抽象化であり YAGNI に反する。現状の `_orthohexagonal` / `_cubic` 2 ヘルパで結晶系の場合分けは十分明快。 |

## 5. 品質判定基準への適合確認 (構造変更なしで既達)

- ✅ **テスト**: 12 passed 継続。回帰は verify-complete で確認予定。
- ✅ **セキュリティ**: 重大な脆弱性なし (§2)。
- ✅ **パフォーマンス**: 重大な性能課題なし (§3)。
- ✅ **コード品質**: 型注釈完備 (`Mapping[str, FixedPhaseSpec]` / `tuple[str, ...]`)、`from __future__ import annotations`、
  ruff clean (line-length 100 / py312)。命名規約 (PascalCase 型 / UPPER_SNAKE 定数 / snake_case 関数) 準拠。
- ✅ **ファイルサイズ**: 149 行 (< 500 行制限)。分割不要。
- ✅ **日本語コメント**: 全公開 API・内部ヘルパ・定数に【機能概要】【実装方針】【テスト対応】と信頼性レベル 🔵🟡🔴 を付与済。
- ✅ **決定論 (NFR-102)**: 乱数・時刻・環境依存なし。モジュール定数で同一入力→ビット同一。
- ✅ **依存 (REQ-403)**: 実装本体は stdlib (`dataclasses` / `math` / `types` / `typing`) のみ。pymatgen 等未使用。
- ✅ **非破壊 (既存 API)**: `PhaseInstance` / `LatticeParams` / `param_name` を利用のみ。model / backends 未変更。

## 6. 改善されたコード

構造・機能の変更を行っていないため、対象コードは Green フェーズ記録
(`cell-phase-presets-green-phase.md`) および `src/tsumugin/operando/cell_phases.py` (149 行) の
現行内容と同一。追記・削除・改名なし。

---

## 品質判定

```
✅ 高品質:
- テスト結果: 12 passed 継続成功 (単体) / ruff clean
- セキュリティ: 重大な脆弱性なし (攻撃面なし・MappingProxyType/frozen で不変)
- パフォーマンス: 重大な性能課題なし (ロード時 O(1) 構築・ヘルパ O(1))
- リファクタ品質: YAGNI に基づき変更不要と判断 (投機的抽象化を回避)
- コード品質: 型注釈・命名・日本語コメント・ファイルサイズ (149行) 全て適切
- ドキュメント: 完成
```

**次のお勧めステップ**: `/tsumiki:tdd-verify-complete m3-operando TASK-0030` で完全性検証を実行します。
</content>
</invoke>
