# プロファイル物理性ガード タスク概要

**作成日**: 2026-07-09
**総タスク数**: 5 (全 TDD)

## 関連文書
- **要件定義**: [requirements.md](../../spec/profile-physicality-guard/requirements.md)
- **設計**: [architecture.md](../../design/profile-physicality-guard/architecture.md) /
  [interfaces.py](../../design/profile-physicality-guard/interfaces.py)

## フェーズ構成

| フェーズ | 内容 | タスク |
|---|---|---|
| Phase 1 | 純関数コア (numpy, GSAS 非依存) | TASK-0001, TASK-0002 |
| Phase 2 | engine アダプタ + 配線 + エクスポート | TASK-0003, TASK-0004, TASK-0005 |

## タスク一覧

- [ ] [TASK-0001: check_profile_physicality — CW 判定 + hard/soft 切り分け](TASK-0001.md) (TDD) 🔵
- [ ] [TASK-0002: check_profile_physicality — TOF 判定 + skip 縮退](TASK-0002.md) (TDD) 🔵
- [ ] [TASK-0003: _extract_profile + hist_profile 充填](TASK-0003.md) (TDD) 🔵
- [ ] [TASK-0004: _profile_ranges + _profiles_physical + engine ガード配線](TASK-0004.md) (TDD) 🔵
- [ ] [TASK-0005: __all__ エクスポート + diagnose 連携回帰](TASK-0005.md) (TDD) 🔵

## 依存関係

```
TASK-0001 → TASK-0002 → TASK-0003 → TASK-0004 → TASK-0005
```

## 全体進捗
- [ ] Phase 1: 純関数コア
- [ ] Phase 2: engine アダプタ + 配線

## 信頼性レベルサマリー
- 🔵 青信号: 5件 (100%)

**品質評価**: 高品質
