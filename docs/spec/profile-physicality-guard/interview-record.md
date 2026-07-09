# プロファイル物理性ガード ヒアリング記録

**作成日**: 2026-07-09
**ヒアリング実施**: 要件確定前のスコープ・プロセス確認 (AskUserQuestion)

## ヒアリング目的

XND joint 解析で判明した「プロファイルパラメータが収束前に非物理値へ走る」問題に対し、
数学的妥当性チェック＆revert の実装スコープと開発プロセスを確定する。

## 質問と回答

### Q1: プロファイル妥当性チェック＆revert の実装スコープをどこまでにするか

**質問日時**: 2026-07-09
**カテゴリ**: 追加要件 / スコープ調整
**背景**: 最小 (engine ガードのみ) と フル (抽出+純関数+ガード+警告+診断連携) で作業量・波及が大きく異なるため。

**回答**: **フル（推奨）** — プロファイル値抽出→`hist_profile` 充填 + `check_profile_physicality` (純関数) +
engine revert ガード配線 + ValidityReport 警告 + `diagnose_residual` 連携。内省フィールドの死蔵も解消。

**信頼性への影響**:
- REQ-001〜REQ-006・REQ-101〜REQ-103 の全機能要件が確定 (🔵)。
- 内省フィールド `hist_profile` の充填 (REQ-001) がスコープ内に入り、診断連携が確定。

### Q2: 実装プロセス (Kairo+TDD 必須の前提で)

**質問日時**: 2026-07-09
**カテゴリ**: 既存設計確認 / プロセス
**背景**: CLAUDE.md がマイルストーン実装に Kairo+TDD を必須化している。

**回答**: **Kairo フルループ（推奨）** — requirements→design→tasks→implement を自律実行。

**信頼性への影響**:
- 本要件定義書の作成方針が確定。以降 design/tasks/implement を順に実行。

## 事前調査で確定した技術事実 (コード精読)

- `check_validity` (`validity.py:20`) は純関数で checks/warnings を返す既存パターン。同流儀で
  `check_profile_physicality` を追加できる 🔵
- `_cells_physical` (`engine.py:79`) は bool を返し、段階ループで
  `if not _cells_physical(...): rwp=gof=inf` として revert 経路に落とす (`engine.py:622`)。
  同格ガードを 1 行追加すればよい 🔵
- `AutoRietveldResult(...)` 構築 (`engine.py:699-711`) は `hist_profile` を渡していない
  → 内省フィールドは現状 default 空 (死蔵)。抽出配線が必要 🔵
- GSAS 格納形は `hist.data['Instrument Parameters'][0][key] = [default, value, refine_flag]` 🔵
- CW X 線既定 instprm: `U:2.0, V:-2.0, W:5.0, SH/L:0.002` (`interop/instrument.py:53`)。
  **V が負なのは正常** → 単独符号でなく幅関数正値性で判定すべき、が裏付けられた 🔵
- TOF 既定: `sig-0/1/2, beta-0:0.02, beta-1:0.0, alpha` (`interop/instrument.py`)。
  alpha/beta は `1/alpha`,`1/beta` で発散するため strict > 0 が必要 🔵

## ヒアリング結果サマリー

### 確認できた事項
- スコープ = フル。プロセス = Kairo フルループ。
- 判定は材料非依存の物理法則 (幅関数正値性) に限定 (過度な一般化の禁止)。
- accept/revert エンジンは不変、`_cells_physical` 同格ガードの追加のみ。

### 追加/変更要件
- `hist_profile` 内省フィールドの充填を明示的にスコープへ (REQ-001)。

### 残課題
- soft 上限の具体値 (SH/L 上限等) は設計フェーズで既定を決定 (revert には無関係なので安全側)。

### 信頼性レベル分布

**ヒアリング後**:
- 🔵 青信号: 18
- 🟡 黄信号: 3
- 🔴 赤信号: 0

## 関連文書

- **要件定義書**: [requirements.md](requirements.md)
- **ユーザストーリー**: [user-stories.md](user-stories.md)
- **受け入れ基準**: [acceptance-criteria.md](acceptance-criteria.md)
