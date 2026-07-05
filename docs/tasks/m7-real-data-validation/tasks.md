# M7 実装タスク分割

各タスクは TDD (Red→Green→Refactor)。GSAS-II 依存は `@pytest.mark.gsas`。
タスク毎に 1 コミット (テスト green)。

**進捗 (2026-07-05)**: Phase A–C 完了 (T1/T2/T3 いずれもチュートリアル同等以上を自動達成)。
Phase D はインフラ (FXYE ローダー・多相相分率制約・TOF プロファイルキー・格子崩壊ガード) 完了、
T4 の TOF Rwp 収束は M-later。Phase E (洗練・AGENT_PLAYBOOK・完了記録) 完了。

## Phase A — 実構造 Rietveld コア + T1 検証

- **TASK-0701** `autorietveld.model`: 入力/出力 frozen dataclass 群 + Radiation/Geometry Enum。
  純データのユニットテスト (不変性・with_updates)。依存: なし
- **TASK-0702** `autorietveld.recipe.build_recipe`: 普遍段階列 + 幾何アダプタ (BB→shift,
  DS→zero/XY)。宣言的 flags の検証テスト。依存: 0701
- **TASK-0703** `autorietveld.validity.check_validity`: 物理妥当性ゲート (格子/Uiso/占有率/
  制約/収束)。純 numpy テスト。依存: 0701
- **TASK-0704** `autorietveld.engine.run_auto_rietveld`: GSAS-II 駆動。単相ラボ X 線経路。
  revert-on-worsen ガード + inf 変換 + ledger 追記。`@pytest.mark.gsas`。依存: 0701–0703
- **TASK-0705** T1 ベンチ: `tests/autorietveld/test_t1_labdata.py` — FAP を自動解析し
  Rwp ≤ 12%, GOF ≤ 4.5, 妥当性 pass を検証 (`@pytest.mark.gsas` + データ未取得時 skip)。依存: 0704

## Phase B — CW 中性子 + 制約 + T2 検証

- **TASK-0706** 中性子放射源対応 (エンジンの放射源分岐 + 背景/プロファイル既定)。依存: 0704
- **TASK-0707** 制約 API: 占有率等価制約・占有率和制約の自動生成 (recipe + engine)。依存: 0702,0704
- **TASK-0708** T2 ベンチ: garnet を自動解析し Rwp ≤ 6.5%, 占有率制約充足を検証。依存: 0706,0707

## Phase C — ネイティブ joint + T3 検証

- **TASK-0709** 複数ヒストグラム対応 (1 プロジェクト N histogram, 共有/個別パラメータ)。依存: 0704
- **TASK-0710** 温度差吸収: per-histogram 静水圧歪み Dij。依存: 0709
- **TASK-0711** T3 ベンチ: PbSO4 X 線+中性子 joint で合計 wR ≤ 8% を検証。依存: 0709,0710

## Phase D — TOF + 多相 + T4 検証

- **TASK-0712** ローダー: `reference.io.load_fxye` + TOF `.gsa`/`.instprm` エンジン対応。依存: 0709
- **TASK-0713** 多相 + 相分率和=1 制約。依存: 0707,0709
- **TASK-0714** T4 ベンチ: NAC+CaF2 3 ヒストグラムで Rw ≤ 8.5%, 相分率制約充足を検証。依存: 0712,0713

## Phase E — 洗練 + 指示書 + 統合

- **TASK-0715** アルゴリズム洗練: 4 例横断で背景動的増項・段階追加ヒューリスティクスを一般化。依存: 0705,0708,0711,0714
- **TASK-0716** `AGENT_PLAYBOOK.md` 作成 (成果物2)。依存: 0715
- **TASK-0717** 公開 API 配線 (`autorietveld.__init__` + トップレベル `__all__`) + MCP ツール
  `auto_rietveld` 検討。依存: 0715
- **TASK-0718** CLAUDE.md 更新 (M7 完了記録) + ベンチ回帰化 + 最終チェック。依存: 0716,0717

## 検証コマンド

```bash
uv run pytest                                   # 全テスト green
PYTHONIOENCODING=utf-8 uv run pytest -m gsas    # GSAS-II 実データ検証 (T1-T4)
uvx ruff check src tests                        # lint
```
