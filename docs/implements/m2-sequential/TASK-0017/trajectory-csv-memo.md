# TDD開発メモ: trajectory-csv (TASK-0017)

## 概要

- 機能名: trajectory-csv (Trajectory + FrameRecord + to_csv / 時系列トラジェクトリ出力 + CSV 書き出し)
- 開発開始: 2026-07-03
- 現在のフェーズ: 完了 (Refactor 済 / 品質判定 ✅ 高品質)

## 関連ファイル

- 元タスクファイル: `docs/tasks/m2-sequential/TASK-0017.md`
- 要件定義: `docs/implements/m2-sequential/TASK-0017/trajectory-csv-requirements.md`
- テストケース定義: `docs/implements/m2-sequential/TASK-0017/trajectory-csv-testcases.md`
- Red フェーズ記録: `docs/implements/m2-sequential/TASK-0017/trajectory-csv-red-phase.md`
- 実装ファイル: `src/tsumugin/sequential/trajectory.py` (未実装 — Green で新設)
- テストファイル: `tests/test_trajectory.py` (新規作成済)

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-03

### テストケース

`tests/test_trajectory.py` に 17 件 (正常系 6 / 異常系 4 / 境界値 7) を実装。
受け入れ基準対応: TC-104-01 → T-N01 / TC-104-02 → T-N02 / TC-104-03 → T-E01 / REQ-402(完了条件④) → T-B05。
信頼性内訳: 🔵 10 / 🟡 7 / 🔴 0。CSV レイアウト (共通 8 列 + 相ごと 8 列 / bool は "True"/"False" /
reasons は "|" 連結 / 非有限・None は空欄) をテスト定数で凍結した。

### テストコード

全文は `tests/test_trajectory.py` を参照 (共通ヘルパ `_phase` / `_record` / `_read_rows` / `_read_dicts`、
凍結定数 `FRAME_COMMON_COLUMNS` / `PHASE_FIELD_SUFFIXES` / `REASONS_DELIMITER` を含む)。

### 期待される失敗

`uv run pytest tests/test_trajectory.py -q` →
`ImportError: cannot import name 'FrameRecord' from 'tsumugin.sequential'` により collection で 1 error、
17 テスト全てがエラー (=失敗)。`uvx ruff check tests/test_trajectory.py` は All checks passed。

### 次のフェーズへの要求事項 (Green)

1. `src/tsumugin/sequential/trajectory.py` を新設し `FrameRecord` / `Trajectory` (両 frozen) + `to_csv` を実装。
2. 相 ref は `sorted(phase_ref ∪ lifecycles.keys())` で列順決定論化。列は明示リスト構築。
3. 数値セルはローカル純化ヘルパ (`_finite_or_none` と同思想) を通し None/非有限 → `""`、有限 → `str(v)`。
   bool → `str(bool)`、reasons → `"|".join(...)`。`open(newline="", encoding="utf-8")` + `csv.writer`。
4. `to_csv` は書き出した `path` を返す。`sequential/__init__.py` の `__all__` に昇順で 2 シンボル追加。
5. `PhaseInstance`/`PhaseLifecycle`/`LatticeParams` は `tsumugin.model` から再利用 (新設しない)。ruff クリーン維持。

## Greenフェーズ（最小実装）

`src/tsumugin/sequential/trajectory.py` に `FrameRecord` / `Trajectory` (両 frozen) + `to_csv` を実装済。
相 ref は `sorted(phases ∪ lifecycles.keys())` で列順決定論化。数値セルはローカル `_num_cell` で
None/非有限 → `""`、bool → `str(bool)`、reasons → `"|".join`。`sequential/__init__.py` に 2 シンボル昇順追加。
テスト 17 件全 green。

## Refactorフェーズ（品質改善）

### リファクタ日時

2026-07-03

### 改善内容

- 相ごと列接尾辞を `_PHASE_FRAME_SUFFIXES` (a/b/c/scale/wt_frac) と `_PHASE_LIFECYCLE_SUFFIXES`
  (birth/death/confidence) に分割し、`_PHASE_FIELD_SUFFIXES` を両者の連結で合成 (単一情報源化)。
  相なし行の空欄プレースホルダをマジック個数 (`["", "", "", "", ""]` / `["", "", ""]`) から
  `[""] * len(...)` へ変更し、列定義変更時の個数 desync を排除。出力バイト列は完全不変。
- YAGNI により見送り: `typing.Mapping` (コードベース慣習に一致)、`_num_cell` の共通化
  (レイヤ独立性を優先した意図的複製)。

### セキュリティレビュー結果

重大な脆弱性なし。非有限は `_num_cell` で空欄化しファイルに漏らさない。stdlib csv のみで注入面なし。

### パフォーマンスレビュー結果

重大な性能課題なし。O(フレーム数 × 相数)、逐次 writerow で全行バッファリングなし。

### 品質評価

✅ 高品質 — テスト 17 件継続 green / ruff クリーン / 197 行 (500 行制限内)。
詳細は `trajectory-csv-refactor-phase.md` を参照。

## 検証フェーズ（完全性確認）

### 🎯 最終結果 (2026-07-03)

- **実装率**: 100% (17/17 テストケース — 正常系 6 / 異常系 4 / 境界値 7)
- **テストケース網羅**: testcases.md の T-N01〜T-N06 / T-E01〜T-E04 / T-B01〜T-B07 が
  `tests/test_trajectory.py` の 17 関数へ 1:1 対応 (欠落・未実装なし)
- **完了条件網羅**: ①必須列→T-N01 / ②行数=フレーム数→T-N02 / ③失敗フレーム空欄・非有限漏れなし→T-E01 /
  ④決定論バイト同一→T-B05 の 4 項目すべて対応テスト green
- **テスト成功率**: 100% (スコープ内 17/17)
- **全体テスト**: 334 passed, 3 skipped (skip は GSAS-II gated の contract test = スコープ外・失敗ではない)
- **品質判定**: ✅ 合格 (高品質・完全達成)
- **TODO更新**: ✅ 完了マーク追加 (`docs/tasks/m2-sequential/TASK-0017.md` 完了条件 4 項目チェック + タイトル完了マーク)

### 💡 重要な技術学習

- **実装パターン**: 列レイアウトを「フレーム由来 / lifecycle 由来」の 2 サブリストに分割し連結合成することで、
  空欄プレースホルダ数を `len()` から導出 → 列定義の単一情報源化 (今後の CSV 出力層で再利用可)。
- **テスト設計**: バイト同一 (`open(rb).read()` 比較) で決定論 (REQ-402) を凍結、CSV レイアウトをテスト定数
  (`FRAME_COMMON_COLUMNS` / `PHASE_FIELD_SUFFIXES` / `REASONS_DELIMITER`) で固定する契約凍結が有効。
- **品質保証**: 非有限 (inf/nan) はセル空欄化に加えファイル全文へ文字列が漏れないことまで検証 (M1 教訓)。

### ⚠️ 注意点

- スコープ内・スコープ外ともに失敗テストなし。後工程での修正対象は **なし**。
