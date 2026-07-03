# TDD開発メモ: LifecycleTracker

## 🎯 最終結果 (2026-07-03 完全性検証)

- **実装率**: 100% (13/13 テストケース: 正常系 6 / 異常系 3 / 境界値 4)
- **成功率**: 100% (スコープ内 13 passed / 全体 317 passed, 3 skipped=gsas マーカー)
- **要件網羅率**: 100% (完了条件 5 項目・TC-103-01〜04・EDGE-001/101 を全網羅)
- **品質判定**: 合格 (高品質)
- **TODO更新**: ✅ 完了マーク追加 (`docs/tasks/m2-sequential/TASK-0016.md` 完了条件 5 項目チェック済)

### テストケース ↔ 完了条件 対応 (13 件全通過)

| テスト | 対応 | 完了条件 |
|---|---|---|
| N-01 test_birth_confirmed_after_hysteresis | TC-103-01 | ① birth_frame=10 |
| N-02 test_death_confirmed_after_absent_hysteresis | TC-103-02 | ② death_frame=15 |
| N-03 test_death_cancelled_on_reappear_within_window | TC-103-04/REQ-201 | ④ death 取り消し |
| N-04 test_all_frames_present_confidence_one | 完了条件⑤ | ⑤ confidence=1.0 |
| N-05 test_multiple_phases_tracked_independently | 契約 Mapping | (複数相独立) |
| N-06 test_lifecycle_config_defaults_frozen_and_reexport | interfaces.py L118-121 | (Config/公開) |
| E-01 test_single_frame_flicker_not_birth | TC-103-03 | ③ 点滅非認定 |
| E-02 test_empty_observation_returns_empty_mapping | EDGE-001 | (空→空) |
| E-03 test_absent_run_reaching_window_confirms_death | TC-103-02 境界 | ② death 確定 |
| B-01 test_birth_boundary_exactly_n_frames | TC-103-01/03 境界 | ①③ N/N-1 境界 |
| B-02 test_death_cancelled_at_window_minus_one | REQ-201 境界 | ④ 窓 N-1 境界 |
| B-03 test_single_frame_observation_no_birth | EDGE-101 | (単一フレーム縮退) |
| B-04 test_confidence_is_presence_fraction | 完了条件⑤裏 | ⑤ confidence=0.7 |

### 💡 重要な技術学習

- **状態機械の可読性**: 相ごとの可変状態を `_PhaseState` に集約し present/absent 遷移を
  `_mark_present`/`_mark_absent` に分離すると、ヒステリシス境界 (birth=連続先頭 frame /
  death=不在先頭 frame) の off-by-one が「ラン先頭 (`*_run_start`) 保持」で明示でき堅牢。
- **death 取り消し (REQ-201)**: death を暫定扱いにせず「不在ランが窓に達した時点で確定・以後不変、
  窓未満の再出現は absent ランリセット」で表現すると、E-03 (窓充足=確定) と N-03/B-02 (窓内=取り消し) が
  対称に落ちる。
- **契約フィールドの未使用**: `presence_wt_frac` は疎結合設計で上位が存在判定を担うため本層で未使用。
  契約 (interfaces.py) 固定のため削除せず保持・文書化するのが正 (YAGNI 違反ではない)。
- **一貫性優先**: `typing.Mapping/Sequence` import は兄弟 `changepoint.py` と揃える (個別最適より一貫性)。

### ⚠️ 注意点

- スコープ外テスト失敗: なし。修正が必要な項目: なし。
- skip 3 件は `gsas` マーカー (GSAS-II 未導入時の想定 skip) であり本タスク非関連。

---

## 概要

- 機能名: LifecycleTracker (ヒステリシス付き birth/death 追跡)
- 要件名 / タスクID: m2-sequential / TASK-0016
- 開発開始: 2026-07-03
- 現在のフェーズ: 完了 (Refactor 済み・変更不要判断)

## 関連ファイル

- 元タスクファイル: `docs/tasks/m2-sequential/TASK-0016.md`
- 要件定義: `docs/implements/m2-sequential/TASK-0016/lifecycle-tracker-requirements.md`
- テストケース定義: `docs/implements/m2-sequential/TASK-0016/lifecycle-tracker-testcases.md`
- 開発コンテキスト: `docs/implements/m2-sequential/TASK-0016/note.md`
- 実装ファイル (未実装): `src/tsumugin/sequential/lifecycle.py`
- テストファイル: `tests/test_lifecycle.py`
- 再利用する既存型: `src/tsumugin/model/phase.py` (`PhaseLifecycle`)

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-03

### テストケース

`tests/test_lifecycle.py` に 13 件 (正常系 6 / 異常系 3 / 境界値 4) を実装。
N-01 birth 確定 / N-02 death 確定 / N-03 death 取り消し (REQ-201) / N-04 confidence=1.0 /
N-05 複数相独立追跡 / N-06 Config 既定値・frozen・re-export / E-01 点滅非認定 (TC-103-03) /
E-02 空観測→空 Mapping / E-03 不在=N で death 確定 / B-01 birth N 境界 / B-02 death 窓 N-1 境界 /
B-03 単一フレーム / B-04 confidence=存在フレーム率 (0.7)。

### Red で固定した意味論 (要件定義の 🟡 判断点)

1. `confidence` = present フレーム数 / **総観測フレーム数** (N-04→1.0, B-04→0.7)。
2. 不在ランが hysteresis を満たしたら death 確定し以後取り消さない。取り消しは不在ラン < N の再出現のみ。
3. birth 未確定の相は `finalize()` のキーに含めない。

### 期待される失敗

`ModuleNotFoundError: No module named 'tsumugin.sequential.lifecycle'` により collection 時に
全 13 テストが失敗 (Red 想定どおり)。`uvx ruff check tests/test_lifecycle.py` は通過。

### 次のフェーズへの要求事項 (Green)

`src/tsumugin/sequential/lifecycle.py` に `LifecycleConfig` (frozen dataclass) と
`LifecycleTracker` (observe/finalize によるヒステリシス追跡) を実装し、
`sequential/__init__.py` の `__all__` に 2 シンボルを昇順追加して re-export する。
`PhaseLifecycle` は既存型を再利用。決定論 (安定走査順・乱数不使用) を守る。

## Greenフェーズ（最小実装）

### 実施日時

2026-07-03

### 実装内容

`src/tsumugin/sequential/lifecycle.py` (170 行) に以下を実装済:
- `LifecycleConfig` (frozen dataclass, hysteresis=3 / presence_wt_frac=1e-3)。
- `_PhaseState` (相ごとの内部可変状態: present/absent ラン・確定 birth/death・存在フレーム数)。
- `LifecycleTracker` (`observe()` で present/absent ランを逐次更新 → `finalize()` で
  `Mapping[str, PhaseLifecycle]` を初出順に縮約)。birth=連続 present ランの先頭 frame、
  death=不在ランの先頭 frame、confidence=存在フレーム数/総観測フレーム数、
  birth 未確定相はキーに含めない。
- `sequential/__init__.py` の `__all__` に `LifecycleConfig` / `LifecycleTracker` を昇順追加・re-export。
- `PhaseLifecycle` は既存 `src/tsumugin/model/phase.py` (TASK-0011) を再利用。

### テスト結果

`uv run pytest tests/test_lifecycle.py` → 13 passed (正常系 6 / 異常系 3 / 境界値 4)。

## Refactorフェーズ（品質改善）

### 実施日時

2026-07-03

### 判定: 変更不要 (no code change)

可読性 (状態機械) / YAGNI / セキュリティ / パフォーマンス / 決定論 / 規約の各観点でレビューし、
積極的なコード変更を行うべき箇所なし = 変更不要と判断 (本タスク指示「変更不要判断可」に合致)。
詳細は `docs/implements/m2-sequential/TASK-0016/lifecycle-tracker-refactor-phase.md` を参照。

### レビュー要点

- 状態機械は `_PhaseState` + `_mark_present`/`_mark_absent` で遷移が 1:1 に読める構造・既に高可読性。
- `presence_wt_frac` は契約 (interfaces.py L118-121) 固定の設定フィールドで未使用は仕様どおり (削除不可)。
- `typing.Mapping/Sequence` の import は兄弟 `changepoint.py` と同一様式のため現状維持 (一貫性優先)。
- ファイル 170 行 (< 500)、型注釈完備、日本語 docstring 充実、`uvx ruff check` クリーン。
- 重大なセキュリティ脆弱性・性能課題・遅いテストなし。

### テスト結果

- 単体: `uv run pytest tests/test_lifecycle.py` → 13 passed in 0.73s。
- 全体回帰: `uv run pytest` → 317 passed, 3 skipped in 11.14s (skip 3 は gsas マーカー・想定内)。
- Lint: `uvx ruff check src/tsumugin/sequential/lifecycle.py tests/test_lifecycle.py` → All checks passed。

### 品質評価

✅ 高品質 (全 green 維持・脆弱性なし・性能課題なし・規約準拠・ドキュメント完成)。
