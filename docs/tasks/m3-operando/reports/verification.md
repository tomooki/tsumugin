# M3 operando — TASK-0035 検証レポート

**要件名**: m3-operando / **タスクID**: TASK-0035 (公開 API 統合 + E2E + ドキュメント)
**検証日時**: 2026-07-04 / **フェーズ**: tdd-verify-complete / **判定**: ✅ 合格

## 1. 検証コマンドと結果

| 検証項目 | コマンド | 結果 |
|---|---|---|
| 全テスト green | `uv run pytest` | **644 passed, 3 skipped** (26.93s) 無退行 |
| カバレッジ 90%+ | `uv run pytest --cov=tsumugin` | **TOTAL 98%** (2983 stmts / 71 miss) |
| Lint clean | `uvx ruff@latest check src tests` | **All checks passed!** |
| @gsas smoke | (gsas 導入済につき本体に含む) | TC-035-11 (N=4 smoke) green |

- GSAS-II 導入済み環境のため `@pytest.mark.gsas` は skip されず実行 (TC-035-11 / TC-209-02)。
- 3 skipped は既存ベースライン (本タスクによる新規 skip なし = 無退行)。
- 起動時の `Error reading {cfgfile}` は GSAS-II の既知無害警告 (cp932 config、動作影響なし)。

## 2. 対象テスト (tests/test_operando_e2e.py — 18 件 / TC-035-01〜18)

- 正常系 (11): 公開シンボル re-export / `__all__` 昇順・後方互換 / is 同一実体 / operando 一気通貫完走 /
  echem frame 同期 / 固定相込み区間分割 / 区間判別 + マルチスタート / 結合出力 CSV 読み戻し /
  共有 Ledger verify / README M3 例の写経実行 / (@gsas) GSASIIBackend N=4 smoke。
- 異常系 (3): echem 必須列欠損 ValueError / undecided エスカレーション (非例外化) / 単一セグメント完走。
- 境界値 (4): 決定論ビット同一 (2 回実行) / `__all__` 全名称の実属性解決 / 判別 1 区間 30 秒以内 / 空系列縮退。

## 3. 完了条件照合 (docs/tasks/m3-operando/TASK-0035.md)

| # | 完了条件 | 状態 |
|---|---|---|
| ① | `from tsumugin import MultistartEngine, ...` で M3 API 利用可能 | ✅ TC-035-01/02/03 green (85 シンボル・昇順・is 同一実体) |
| ② | TC-209-01 一気通貫 E2E green | ✅ TC-035-04〜09 green |
| ③ | (@gsas) TC-209-02 マルチスタート smoke | ✅ TC-035-11 green (実 GSAS-II で N=4 完走) |
| ④ | 全テスト green・カバレッジ 90%+・ruff clean | ✅ 644 passed / 3 skipped・cov 98%・ruff clean |
| ⑤ | README M3 例 + context.md 更新 + 検証レポート | ✅ README「使い方 (M3)」節 + docs/dev/context.md M3 反映 + 本レポート |

## 4. 変更ファイル (本タスク Green→Refactor→Verify 累計)

- `src/tsumugin/__init__.py` — M3 公開シンボル re-export (85 件・昇順) + グルーピングコメント。
- `tests/test_operando_e2e.py` — E2E 18 件 (新規)。
- `README.md` — 「使い方 (M3): operando 解析」節 + 状態/アーキテクチャ表を M3 反映。
- `docs/dev/context.md` — Overview/構造/公開 API/Additional Notes を M3 反映。

## 5. 判定

✅ **合格 (完全実装)**。完了条件 5/5 達成・スコープ内テスト全 green・カバレッジ 98%・ruff clean・無退行。
非破壊性 (P2/REQ-404: 既存 M0/M1/M2 公開面と `__all__` 昇順は不変) を維持。
