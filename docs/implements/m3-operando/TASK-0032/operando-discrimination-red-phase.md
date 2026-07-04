# TASK-0032 Redフェーズ記録: operando/discrimination — 固溶体 vs 二相判別 (FR-313)

**要件名**: m3-operando / **タスクID**: TASK-0032 / **機能名**: operando-discrimination
**作成日時**: 2026-07-04 / **フェーズ**: Red (失敗テスト作成)
**テストファイル**: `tests/test_discrimination.py` (新規・17 件)
**対象実装 (未実装)**: `src/tsumugin/operando/discrimination.py`
(`DiscriminationConfig` / `DiscriminationResult` / `discriminate_interval`)

> 本書のすべてのファイルパスはプロジェクトルートからの相対パス。

---

## 1. 作成したテストケース一覧 (17 件 / testcases.md に 1:1 対応)

### 正常系 (8 件)
| テスト関数 | 対応 | 信頼性 | 概要 |
|---|---|---|---|
| `test_solid_solution_series_yields_solid_solution_verdict` | TC-N01 / TC-204-01 | 🔵 | 固溶体系列 → `"solid_solution"`・ΔBIC≤−閾値 |
| `test_two_phase_series_yields_two_phase_verdict` | TC-N02 / TC-204-02 | 🔵 | 二相系列 → `"two_phase"`・ΔBIC≥+閾値 |
| `test_multistart_is_mandatory_at_interval_endpoints` | TC-N03 / TC-204-03 | 🔵 | 端点×仮説×n_starts 本のマルチスタート必須 (spy) |
| `test_both_hypotheses_carry_metrics_multistart` | TC-N04 / TC-204-03 | 🔵 | 両仮説 `metrics.multistart={"n","n_basins","n_diverged"}` |
| `test_two_phase_hypothesis_keeps_lattice_fixed` | TC-N05 / D4 | 🟡 | 仮説 B refine の free_params に lattice 無し |
| `test_fixed_phase_preserved_and_does_not_disturb_verdict` | TC-N06 / FR-312 | 🔵 | 固定相 Al 格子ビット不変・判別を乱さない |
| `test_ledger_records_and_verifies` | TC-N07 / NFR-105 | 🔵 | `discrimination.*`/`multistart.*` 追記・verify()==True |
| `test_discrimination_is_deterministic_bitwise_identical` | TC-N08 / TC-204-06 | 🔵 | 2 回実行でビット同一 |

### 異常系 (4 件)
| テスト関数 | 対応 | 信頼性 | 概要 |
|---|---|---|---|
| `test_close_competitor_yields_undecided_and_queue_notice_without_blocking` | TC-E01 / TC-204-04 | 🔵 | 僅差 → `"undecided"`+Queue `close_competitor`・非例外 |
| `test_both_high_r_escalates_without_verdict` | TC-E02 / TC-204-05 / EDGE-005 | 🔵 | 両仮説高 R → `"undecided"`+escalations+`all_high_r` |
| `test_all_multistart_diverged_degrades_with_warning` | TC-E03 / REQ-102 / EDGE-002 | 🟡 | 全滅 → 空 basins+warnings・判別継続 |
| `test_invalid_frame_range_raises_value_error` | TC-E04 / 器の契約 | 🟡 | `(5,2)`/`(0,99)`/`(-1,3)` → `ValueError`・refine 未開始 |

### 境界値 (5 件)
| テスト関数 | 対応 | 信頼性 | 概要 |
|---|---|---|---|
| `test_delta_bic_exactly_threshold_is_decided_closed_boundary` | TC-BV01 | 🟡 | ΔBIC 10.0/9.99/10.01 の閉境界 (`>=` 確定側) |
| `test_none_queue_and_ledger_do_not_change_verdict` | TC-BV02 | 🔵 | queue/ledger=None でも同一 verdict/delta/escalations |
| `test_single_frame_interval_degenerate_is_deterministic` | TC-BV03 | 🟡 | `frame_range=(3,3)` 縮退・非例外・決定論 |
| `test_config_and_result_are_frozen_with_contract_defaults` | TC-BV04 | 🔵 | frozen + 既定値 (10.0/30.0/10/MultistartConfig()) |
| `test_single_interval_discrimination_under_thirty_seconds` | TC-BV05 / TC-209-03 | 🟡 | 判別 1 区間 (N=8) < 30 秒 smoke |

---

## 2. テストダブル (テストファイル内定義)

- **`RecordingSpyBackend`**: `SimulatedBackend` へ委譲しつつ refine の
  `(free_params, max_cycles, n_phases, phase_refs)` を記録。マルチスタートは `max_cycles==15`
  (ms_max_cycles)、逐次は `==10` (seq_max_cycles)、仮説 A=単相 / B=2 相で識別 (TC-N03/N05/E04)。
- **`ControlledFakeBackend`**: 相数で chi2/rwp を固定返す決定論スタブ。
  `close`(A/B 同一 chi2→ΔBIC≈0) / `high_r`(rwp=50 全返し) /
  `diverge_multistart`(max_cycles==15 のみ chi2=inf) / `threshold`(chi2 差で ΔBIC 厳密制御)。
  `n_params=0` を返し BIC ペナルティを 0 に固定 (ΔBIC=chi2 差へ帰着 / TC-E01/E02/E03/BV01/BV02)。

## 3. 合成データ (SimulatedBackend・乱数なし → ビット同一)

- `_solid_solution_series(a0=5.0, a1=5.10)`: 単相の格子 a=b=c をフレームで線形変化 (格子連続変化)。
  → 仮説 A 完全適合・仮説 B 中間不適合 → ΔBIC≈−84 (検証済み)。
- `_two_phase_series(a_alpha=5.0, a_beta=5.06)`: 端成分 2 相 (純端点) の scale を α:1→0/β:0→1 漸移。
  → 仮説 B 適合・仮説 A 不適合 → ΔBIC≈+37 (検証済み・a_beta は LM 追従域内で選定)。
- `_solid_solution_with_al_series`: 上記固溶体に Al 固定相ピークを重畳 (TC-N06)。
- `_fake_series`: ControlledFakeBackend 用ダミー (n_obs 用の形状のみ)。
- グリッド `GRID = np.arange(15.0, 60.0, 0.05)` (小グリッド・<30 秒 smoke)。

---

## 4. 期待される失敗 (Red 確認済み)

```
$ uv run pytest tests/test_discrimination.py
ERROR collecting tests/test_discrimination.py
E   ModuleNotFoundError: No module named 'tsumugin.operando.discrimination'
1 error in 0.79s
```

- `src/tsumugin/operando/discrimination.py` 未実装のため collection 時に import が失敗し全 17 件がエラー(=失敗)。
- 他の import (SimulatedBackend / MultistartConfig / FrameSeries / CELL_PHASE_PRESETS / ReviewQueue /
  Ledger / Hypothesis) はすべて解決済み (=モジュール本体はコンパイル成功・構文エラーなし)。
- `uvx ruff check tests/test_discrimination.py --line-length 100` → All checks passed。

---

## 5. Green フェーズで実装すべき内容 (次フェーズ要求事項)

`src/tsumugin/operando/discrimination.py` に以下を最小実装する:

1. **`DiscriminationConfig`** (frozen): `close_threshold=10.0` / `multistart=MultistartConfig()` /
   `high_r_threshold=30.0` / `seq_max_cycles=10`。
2. **`DiscriminationResult`** (frozen): `verdict` / `delta_evidence`(=Σbic_A−Σbic_B) /
   `hypothesis_single` / `hypothesis_two_phase` / `multistart_single` / `multistart_two_phase` /
   `escalations` / `warnings=()`。
3. **`discriminate_interval(backend, series, frame_range, initial_phases, *, config, fixed_phases, ledger, queue)`**:
   - frame_range 検証 (範囲外/start>end → `ValueError`、refine 開始前)。
   - 仮説 A: 区間フレームを単相 warm-start 逐次 direct refine (free: scale+lattice.a/b/c、
     max_cycles=seq_max_cycles) → Σbic_A。
   - 仮説 B: 区間端点の A 格子で端成分 2 相を初期化・**格子固定**、scale/wt のみ解放で逐次 refine → Σbic_B。
   - 両仮説の区間端点 (start/end) で `MultistartEngine(backend, config=config.multistart,
     ledger=ledger).run(...)` を適用 (B は `free_suffixes=("scale","wt_frac")`)。両仮説 metrics に
     `multistart={"n","n_basins","n_diverged"}` を付与。
   - verdict: ΔBIC≤−閾値→`"solid_solution"` / ≥+閾値→`"two_phase"` / |ΔBIC|<閾値→`"undecided"`+
     `queue.add("close_competitor")` (queue 提供時)。
   - 両仮説とも代表 rwp>high_r_threshold → `"undecided"`+escalations+`queue.add("all_high_r")` (判別しない)。
   - マルチスタート全滅 → 警告を result.warnings へ伝播・逐次 Σbic から判別継続 (非例外)。
   - 固定相: `initial_phases`+`fixed_phases` を連結・固定相 index は `fixed_free_suffixes`=`("scale",)` のみ解放。
   - 全操作 `ledger.append("discrimination.*", ...)` (ledger 提供時、verify() 恒真)。
   - 乱数/集合反復順/時刻に非依存 (2 回実行ビット同一)。
4. `operando/__init__.py` の `__all__` へ非破壊追記。

**次のお勧めステップ**: `/tsumiki:tdd-green m3-operando TASK-0032` で Green フェーズ (最小実装) を開始。
