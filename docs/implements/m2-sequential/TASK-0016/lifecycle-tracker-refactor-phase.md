# TASK-0016 Refactor フェーズ記録: LifecycleTracker

**機能名**: LifecycleTracker (ヒステリシス付き birth/death 追跡)
**要件名**: m2-sequential / **タスクID**: TASK-0016 / **タイプ**: TDD
**実施日時**: 2026-07-03 / **対象**: `src/tsumugin/sequential/lifecycle.py`

> すべてのファイルパスはプロジェクトルートからの相対パス。
> 信頼性: 🔵 資料準拠 / 🟡 妥当な推測 / 🔴 資料外推測。

---

## 1. リファクタリング方針と判定

**判定: 変更不要 (no code change)** 🔵

Green フェーズ実装 `src/tsumugin/sequential/lifecycle.py` (170 行) を可読性・状態機械設計・
YAGNI・セキュリティ・パフォーマンスの観点でレビューした結果、リファクタリングの原則
(機能変更なし・小さな改善) に照らして **積極的なコード変更を行うべき箇所は見当たらず、変更不要と判断**した。
本タスク指示 (「YAGNI、変更不要判断可」) に沿った結論。

---

## 2. レビュー観点と評価

### 2.1 可読性 / 状態機械設計 🔵
- 相ごとの可変状態を `_PhaseState` (frozen でない dataclass) に集約し、present/absent の
  逐次遷移を `_mark_present` / `_mark_absent` の 2 メソッドに分離。状態機械の遷移が
  「入力 (present/absent) × メソッド」で 1:1 に読める構造で、可読性は既に高い。
- `observe()` は「初出登録 → 全登録相を present/absent に振り分け」の 2 段で、責務が明快。
- birth=連続 present ランの先頭 frame、death=不在ランの先頭 frame という
  off-by-one を招きやすい境界セマンティクスが、`present_run_start` / `absent_run_start` の
  ラン先頭保持で明示されており、コメントにも意図が記録済み。改善の余地は小さい。

### 2.2 YAGNI / スコープ 🔵
- `presence_wt_frac` は本タスクで判定に未使用だが、これは **契約 (interfaces.py L118-121) で固定された
  設定フィールド**であり、存在判定は上位 (後続 TASK-0019 SequentialEngine) が担う疎結合設計。
  仕様どおりの「保持・文書化」であり、デッドコード/過剰実装ではない。削除は契約違反になるため不可。
- 余分な抽象化・将来用フック・未使用ヘルパーは無し。標準ライブラリのみで最小構成。

### 2.3 コード品質 / 規約 🔵
- `uvx ruff check src/tsumugin/sequential/lifecycle.py tests/test_lifecycle.py` → **All checks passed**。
- 型注釈完備 (`any` 不使用)。日本語 docstring は既存 `changepoint.py` の
  【機能概要】【実装方針】【テスト対応】+ 🔵/🟡 様式に準拠。
- `from typing import Mapping, Sequence` は **同一パッケージ `changepoint.py` と同一の import 様式**。
  `collections.abc` へ変更すると兄弟モジュールとの一貫性を崩すため、あえて現状維持 (一貫性 > 個別最適)。
- ファイルサイズ 170 行 (< 500 行制限)。分割不要。

### 2.4 セキュリティレビュー 🔵
- 外部入力は `frame_index: int` / `present_refs: Sequence[str]` のみ。I/O・eval・
  subprocess・外部リソースアクセス・シリアライズなし。インジェクション面なし。
- 乱数不使用・グローバル状態不使用でトラッカー単位に状態が隔離。重大な脆弱性なし。

### 2.5 パフォーマンスレビュー 🔵
- 計算量 O(総フレーム数 × 相数)。各 `observe` は登録相を 1 回走査、各相の更新は O(1)。
- `present_set = set(present_refs)` により present 判定を O(1) 化済。合成 100 フレーム規模で軽量。
- 全 13 テスト 0.73s / 全 317 テスト 11.14s。2 秒以上の遅いテストなし。最適化課題なし。

### 2.6 決定論 (REQ-402 / NFR-202) 🔵
- 相状態は初出順を保つ `dict` で保持し、`finalize()` は初出順で縮約。乱数・時刻依存なし。
  同一入力・同一 Config で出力ビット同一。

---

## 3. リファクタリング実施内容

**コード変更: なし** (上記レビューにより変更不要と判断)。

適用を検討したが **見送った** 候補と理由:
- `typing.Mapping/Sequence` → `collections.abc` 移行: 兄弟 `changepoint.py` と不整合になるため見送り。
- `presence_wt_frac` 削除: 契約フィールドのため不可。
- ヘルパー追加/状態機械の別クラス抽出: 現状で既に読みやすく、過剰設計 (YAGNI 違反) になるため見送り。

---

## 4. テスト実行結果 (リファクタ判定後)

- 単体: `uv run pytest tests/test_lifecycle.py` → **13 passed in 0.73s**。
- 全体回帰: `uv run pytest` → **317 passed, 3 skipped in 11.14s** (skip 3 は `gsas` マーカー未導入分・想定内)。
- Lint: `uvx ruff check` → All checks passed。
- 開発時一時ファイル (debug-*/temp-*/*.bak 等)・`skip`/`xfail` マーカー: **なし**。

---

## 5. 品質判定

✅ **高品質**
- テスト結果: 全 green を維持 (単体 13 / 全体 317 passed)。
- セキュリティ: 重大な脆弱性なし。
- パフォーマンス: 重大な性能課題なし・遅いテストなし。
- リファクタ品質: 状態機械の可読性は既に目標水準、変更不要判断は妥当。
- コード品質: ruff クリーン・型注釈完備・500 行制限内・日本語コメント充実。
- ドキュメント: 本ファイルおよびメモに記録済。

**次のお勧めステップ**: `/tsumiki:tdd-verify-complete` で完全性検証を実行。
