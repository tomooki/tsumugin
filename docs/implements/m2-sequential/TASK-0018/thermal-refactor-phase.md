# TASK-0018 thermal — Refactor フェーズ記録

**要件名**: m2-sequential / **タスクID**: TASK-0018 / **フェーズ**: TDD Refactor
**対象**: `src/tsumugin/sequential/thermal.py` / **テスト**: `tests/test_thermal.py`
**実施日**: 2026-07-03

---

## 1. リファクタ前状態の確認

- **テスト**: `uv run pytest tests/test_thermal.py -q` → 18 passed (正常系 7 / 異常系 6 / 境界値 5)。
- **Lint**: `uvx ruff check src/tsumugin/sequential/thermal.py tests/test_thermal.py` → All checks passed。
- **ファイルサイズ**: 218 行 (500 行制限に対し十分に余裕、分割不要)。
- **re-export**: `src/tsumugin/sequential/__init__.py` に `ThermalBaseline` /
  `TransitionEstimate` / `fit_thermal_baseline` / `estimate_transition` 追加済み・`__all__` 整合。
- **遅いテスト**: 全体 0.2s 未満。2 秒超のテストなし。
- **除外/skip**: `*.skip` / `testPathIgnorePatterns` 相当なし。開発時一時ファイル(debug-*/temp-* 等)なし。

## 2. 品質レビュー結果

### セキュリティレビュー 🔵
- 純関数 2 本 (乱数・I/O・外部状態・可変グローバルなし)。SQL/XSS/CSRF/認証の攻撃面は存在しない。
- 入力縮退が例外化されず安全側 (`None` / 空タプル / 定数フィット) に一元化され、
  `inf`/`nan` を下流へ漏らさない (M1 教訓 / CLAUDE.md 非有限漏洩禁止に適合)。
- MAD=0 / 点数不足 / 平坦分率対の 0 除算はガード済み。脆弱性なし。

### パフォーマンスレビュー 🔵
- `fit_thermal_baseline`: `np.polyfit` O(n·degree) + `np.median` O(n log n)。フレーム列規模で十分高速。
- `_outlier_frames`: ベクトル化した中央値/MAD + O(n) 走査。
- `estimate_transition` / `_interpolate_crossing`: 先頭からの O(n) 単一走査。過剰計算・重複走査なし。
- 重大な計算量・メモリ課題なし。

### コード品質レビュー 🔵
- 可読性: モジュール docstring に仕様参照 (FR-322/323 / interfaces.py L169-203) と決定論保証を明記。
  各関数・dataclass フィールドに信頼性レベル (🔵🟡) 付き日本語コメントが行き届いている。
- DRY: 交差補間は `_interpolate_crossing` に、逸脱判定は `_outlier_frames` に共通化済み。
  閾値・レベルは名前付き定数 (`_OUTLIER_Z_THRESHOLD` / `_ONSET_LEVEL` / `_MIDPOINT_LEVEL`) に抽出済み。
- 単一責任: フィット / 逸脱分離 / 交差補間 / 転移推定が各関数に分離されている。
- 命名・型: snake_case / PascalCase・型注釈完備・`Any` 不使用。import 様式は changepoint.py と一致。

## 3. リファクタリング判断: 変更不要 (YAGNI)

Green フェーズ実装が既に Refactor 目標水準に到達しているため、機能・構造の変更は行わない。

- **`_MODIFIED_Z_CONST` の changepoint.py との重複**: 意図的に非共通化のまま維持。
  changepoint の `_robust_z` は「窓の末尾点 1 点」の z を返すのに対し、thermal の `_outlier_frames`
  は「全点をベクトル化」して z 集合を返す別セマンティクスであり、共有ヘルパー化は自然な統合にならず
  かつクロスモジュール変更のリスクを負う。定数は「changepoint.py と同一」とコメント済み。YAGNI に従い据え置き。
- **係数順反転・縮退分岐・交差補間**: いずれも仕様契約に直結し、簡素化余地は乏しい。
- **注記 (行動変更せず)**: 減少シグモイド (disappearing) では onset(10% 交差) が midpoint より
  高温側になり得る。ただし完了条件・テストは disappearing での onset<midpoint を要求しておらず、
  note.md でも「10% を『変化 10% 進行』と一貫」の設計判断として既知。挙動変更は Refactor スコープ外の
  ため触れない (必要なら後続タスクで仕様確定の上対応)。

## 4. リファクタ後の再確認

- テスト: 18 passed (変更なしのため差分ゼロ、決定論テスト == 一致)。
- Lint: All checks passed。
- 最終コード: `src/tsumugin/sequential/thermal.py` (218 行、変更なし)。

## 5. 品質判定

✅ 高品質
- テスト結果: 全 18 件継続成功
- セキュリティ: 重大な脆弱性なし
- パフォーマンス: 重大な性能課題なし
- リファクタ品質: 目標到達済み (変更不要と判断)
- コード品質: 適切なレベル
- ドキュメント: 完成

次のお勧めステップ: `/tsumiki:tdd-verify-complete` で完全性検証を実行。
