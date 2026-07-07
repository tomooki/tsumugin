# M11 逐次減算同定 タスク分割 (kairo-tasks)

仕様 FR-118 / 要件 `docs/spec/m11-iterative-identification/requirements.md` / 設計
`docs/design/m11-iterative-identification/architecture.md`。ブランチ: `milestone/m11-iterative-identification`。
全タスク TDD (Red→Green→Refactor)、モデル Opus、タスク 1 件 = 1 コミット。**PR #26 (層1 rerank 既定 on)
マージ後**に実装着手 (本ループは rerank 既定を前提とする)。

## 依存グラフ

```
T1 significance 昇格 ─┐
T2 scale.py ──────────┼─ T3 iterative 骨格 ── T4 受理/棄却 ── T5 chem+多形 ── T6 operando シム ── T7 実データ ── T8 review/PR
```

## タスク

### T1 — `reference/significance.py` 昇格 (NFR-M11-3)
- **成果**: `insitu/residual.py` の `residual_significance`/`ResidualSignificance` を `reference/significance.py`
  へ移設。`insitu.residual` は `from ..reference.significance import *` で re-export (後方互換)。import 方向
  (reference ⇏ insitu) を回復。
- **テスト**: 既存 `test_residual.py` を `tests/reference/test_significance.py` へ移設 + `insitu.residual`
  経由 import が通る後方互換テスト。
- **AC**: reference が insitu を import しない。全既存テスト green。

### T2 — `reference/scale.py` (非負スケール joint フィット, FR-118-2)
- **成果**: `render_model(tt, ref, scale, fwhm)` (プロファイル合成) + `fit_nonneg_scales(tt, observed, refs, fwhm)
  -> (scales, residual, unexplained_ss)` (閉形式 + 非負クリップ アクティブセット, numpy)。
- **テスト**: 既知スケールの2相合成を回復、非負制約 (負スケール候補は 0)、unexplained_ss = 正残差二乗和、決定論。
- **AC**: scipy 非依存、numpy 決定論 green。

### T3 — `reference/iterative.py` 骨格 (FR-118-1/3)
- **成果**: `IdentifyConfig`/`AcceptedPhase`/`IterativeIdentification` dataclass + `identify_pattern` の前処理 +
  停止 (residual_significance < snr_stop) + 単相縮退。
- **テスト** (stub 供給元): 単相パターン → k=1 停止・受理1相、ノイズのみ → 受理0、決定論。
- **AC**: 単相縮退が `identify_phases` 首位と整合。

### T4 — 反復受理/棄却 (FR-118-2/4)
- **成果**: 提案 (`identify_phases` on residual) → try_k を joint 再フィット → gain>eps_gain ∧ scale>scale_min
  で受理 → 原パターンから残差再計算 → ledger 追記。`known_phases` 起点。
- **テスト** (stub): 2相受理、**decoy (既説明ピークのみ) が s≈0 で棄却**、known_phases 起点で残差先引き、
  全棄却で停止、ledger verify。
- **AC**: decoy 棄却が hard 除外なしに成立 (AC-1 の核)。

### T5 — chem 降格 prior + 多形委譲旗 (FR-118-4/5)
- **成果**: `chem.ChemPlausibility` を提案スコアに減点合成 (除外しない) + `group_by_composition` で多形集約 +
  僅差同組成の `escalate_to_rietveld` 旗。
- **テスト**: 部分集合単純相が prior で下がるが残差要求時は受理され得る、多形2つで escalate 旗が立つ。
- **AC**: Dara 教訓遵守 (候補除外なし)。

### T6 — operando シム一本化 (FR-118-6)
- **成果**: `insitu.phaseid.identify_new_phases` を `identify_pattern(known_phases=現行相集合)` 委譲へ
  (物質化→PhaseSpec は温存)。後方互換シグネチャ。
- **テスト**: 既存 insitu phaseid テスト非回帰 + known_phases 起点の逐次同定が動く。
- **AC**: M9/M10 の insitu テスト green。

### T7 — 実データ検証 (`@pytest.mark.mp`, AC-1/2/3)
- **成果**: CandAt × MP 全候補で calcite+aragonite 受理・graphite 棄却、PbSO4 で k=1 停止、minority_probe で
  検出限界低下を測るスクリプト + gated テスト。snr_stop を PbSO4 で校正。
- **テスト**: gated (受理相集合・graphite 不在・単相 k=1・検出限界)。
- **AC**: AC-1/2/3 達成。`scratchpad/bench_mp_full.py` の graphite 混入が解消。

### T8 — `/code-review` ループ → PR
- **成果**: 差分 code-review、MEDIUM/LOW 修正、CLAUDE.md (アーキ表 + M11 現状) 更新、PR 作成。
- **AC**: レビュー収束、`__all__` 昇順、テスト green。マージはユーザー判断。

## リスクと緩和

| リスク | 緩和 |
|---|---|
| import 昇格で循環参照 | T1 で reference→insitu 方向を断つ (re-export のみ insitu 側) |
| 非負 LSQ の数値不安定 | 閉形式 + クリップ反復 (~30行)、条件数が悪ければ Tikhonov 微小正則化 |
| snr_stop がデータ依存 | PbSO4 純単相で校正 (M9 の S/N 校正と同手法)。エージェント/人間 override 可 (層3) |
| プロファイル FWHM 固定の粗さ | 同定 (相の有無) には十分。形状精密化は Rietveld へ委譲 (スコープ外明記) |
| 貪欲順序依存 | 毎回原パターンから joint 再フィット (誤差蓄積を断つ) |

## 検証コマンド

```
uv run pytest tests/reference/test_iterative.py tests/reference/test_scale.py -q   # 決定論コア
uv run pytest -m mp tests/reference/test_iterative_realdata.py                     # 実データ (MP)
uvx ruff check src/tsumugin/reference/iterative.py src/tsumugin/reference/scale.py
```
