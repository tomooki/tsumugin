# thermal (熱膨張ベースライン + 転移温度推定) TDD開発完了記録

## 確認すべきドキュメント

- `docs/tasks/m2-sequential/TASK-0018.md`
- `docs/implements/m2-sequential/TASK-0018/thermal-requirements.md`
- `docs/implements/m2-sequential/TASK-0018/thermal-testcases.md`
- `docs/implements/m2-sequential/TASK-0018/thermal-refactor-phase.md`

## 🎯 最終結果 (2026-07-03)
- **実装率**: 100% (18/18 テストケース: 正常系 7 / 異常系 6 / 境界値 5)
- **テスト成功率**: 100% (スコープ内 18/18 green)
- **全体テスト**: 352 passed / 3 skipped (skip は gsas マーカー、スコープ外・想定内)
- **品質判定**: 合格 (高品質・完全達成)
- **TODO更新**: ✅ 完了マーク追加 (TASK-0018.md 完了条件 5 項目すべて [x])
- **Lint**: `uvx ruff check` All checks passed

## 完了条件 (5 項目) とテスト対応
1. 線形膨張+ジャンプで係数真値近傍・逸脱分離 🔵 TC-105-03 → TB-N01 ✅
2. シグモイド遷移 midpoint±1間隔・onset<midpoint・σ>0 🔵 TC-105-04 → TE-N01 ✅
3. 遷移なし (定数分率) で None 🔵 → TE-E01 ✅
4. appearing/disappearing 方向判定 🟡 → TE-N01/TE-N02 ✅
5. 決定論 (2 回ビット同一) 🔵 TC-105-05 → TB-B02/TE-B03 ✅

## 💡 重要な技術学習
### 実装パターン
- `numpy.polyfit` は高次→低次で係数を返すため `[::-1]` 反転して「低次から」契約に整合。
- 逸脱フレーム分離は残差の中央値/MAD 修正 z (`0.6745*(x-median)/MAD`) 超過で判定。
  MAD=0 (完全フィット) は 0 除算回避で空タプルへ縮退 (changepoint.py `_robust_z` を踏襲)。
- 転移温度は分率の 50%/10% 交差を隣接フレーム線形補間 (`_interpolate_crossing`)。
  平坦対 (f_i==f_{i+1}) は分母 0 回避のため除外し最初の交差を採用 → 決定論。

### テスト設計
- 純関数のため合成データをモジュールレベルで一度だけ構築 (状態レス)。
- 決定論は `==` 厳密比較 (pytest.approx 禁止)、係数/温度は `pytest.approx`、
  非有限漏洩は `math.isfinite`、frozen は `pytest.raises(FrozenInstanceError)`。

### 品質保証
- 縮退 (空入力・点数不足・交差なし・MAD=0) を例外化せず None / 空タプル / 定数フィットへ一元化し、
  inf/nan を下流に漏らさない (M1 教訓 / CLAUDE.md)。

## ⚠️ 注意点 (後続タスク向けメモ、本タスクの完了条件外)
- 減少シグモイド (disappearing) では onset(10% 交差) が midpoint より高温側になり得る。
  完了条件・テストは disappearing での onset<midpoint を要求しておらず、note.md でも
  「10% を『変化 10% 進行』と一貫」の設計判断として既知。必要なら仕様確定の上で後続対応。
- `_MODIFIED_Z_CONST` は changepoint.py と重複するが、windowed 単点 z と全点ベクトル z で
  セマンティクスが異なるため意図的に非共通化。

---
*Red → Green → Refactor (変更不要判断) → Verify-complete まで完了。スコープ内の修正対象なし。*
