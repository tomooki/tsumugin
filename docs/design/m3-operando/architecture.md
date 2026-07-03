# m3-operando アーキテクチャ設計

**作成日**: 2026-07-03
**関連要件定義**: [requirements.md](../../spec/m3-operando/requirements.md)
**ヒアリング記録**: [design-interview.md](design-interview.md)

**【信頼性レベル凡例】**: 🔵 要件・仕様・M0〜M2 実装に依拠 / 🟡 妥当な推測で確定 / 🔴 根拠なし推測

---

## システム概要 🔵

M2 の時系列レイヤの上に **operando 判別レイヤ**を載せる。electrochem チャネルを同期した
フレーム列を IC ペナルティ付きで区間分割 (FR-316) し、各区間で固溶体 vs 二相の両仮説を
**マルチスタート付き** (FR-230) で精密化して evidence 判別 (FR-313) する。実効 μt 吸収補正
(FR-317) は前方モデルの乗算因子 + restraint ペナルティとして組み込む。

## アーキテクチャパターン 🔵

- **パターン**: M0〜M2 と同一 (不変データ + Protocol 境界 + 追記専用ストア + 純関数コア)
- **選択理由**: マルチスタートの N 本独立精密化は純関数構成 (FR-234 並列化余地) が必須。
  判別・分割はいずれも「仮説列挙 + evidence 比較」で P1 の直系 🔵

## コンポーネント構成

### 新規モジュール

| モジュール | 役割 | 要件 | 信頼性 |
|---|---|---|---|
| `_json.py` | `finite_or_none` 共有 (tree/webui/serialization が委譲) | REQ-022/Issue #5 | 🔵 |
| `model/cell.py` | `CellConfig`/`CellLayer`/`BeamConfig` (§4、透過法のみ) | REQ-016 | 🔵 |
| `model/channel.py` 拡張 | kind に voltage/current/capacity/composition 追加 (後方互換) | REQ-007 | 🟡 D-Q4 |
| `model/hypothesis.py` 拡張 | `RefinementMetrics.multistart` (既定 None、非破壊) | REQ-006 | 🔵 |
| `multistart/perturb.py` | 決定論摂動列 (格子グリッド/scale 対数/占有率 LHS 固定表) | REQ-001 | 🔵 (列生成式 🟡) |
| `multistart/basin.py` | 正規化パラメータ距離 + union-find の basin クラスタ | REQ-002 | 🟡 |
| `multistart/engine.py` | `MultistartEngine.run` → `MultistartResult` (昇格仮説含む) | REQ-003〜006 | 🔵 |
| `operando/echem.py` | `EchemData`/`read_echem_csv`/`EchemLoader` Protocol/.mpr スタブ | REQ-007/008 | 🔵 |
| `operando/cell_phases.py` | セル固定相プリセット (Be/Al/graphite) + `FixedPhaseSpec` | REQ-009 | 🔵 (格子値 🟡) |
| `operando/discrimination.py` | FR-313 判別: 両仮説構築→マルチスタート付き精密化→bic 比較 | REQ-010/101 | 🔵 |
| `operando/segmentation.py` | FR-316: 逐次 k 追加 + BIC ペナルティ + 粗→細スキャン | REQ-013/014 | 🔵 |
| `operando/hysteresis.py` | 充放電枝分離 + 同一 x 差分 | REQ-012/104 | 🟡 |
| `operando/output.py` | 結合出力 (trajectory + echem → CSV、転移点 x/V±σ) | REQ-011 | 🟡 |
| `absorption/model.py` | `AbsorptionConfig`/透過因子 A(θ;μt)/restraint ペナルティ/`MuCalculator` Protocol | REQ-017〜019 | 🔵 |
| `sequential/changepoint.py` 拡張 | 新規ピーク指標に強度閾値+持続 M フレーム (Issue #3) | REQ-015 | 🔵 |
| `sequential/thermal.py` 修正 | disappearing onset=90% 交差 (Issue #4) | REQ-021 | 🔵 |

### 再利用する M0〜M2 資産 🔵

- `SimulatedBackend` — μt 吸収項の前方モデル拡張の宿主 (D8)
- `StagedRefinementEngine`/`backend.refine` — マルチスタート各 start の精密化
- `BICBackend`/`rank` — 判別・分割・basin の evidence
- `SequentialEngine` の warm-start 逐次パターン — 区間内コスト計算 (軽量版)
- `FinalSelectionEngine`/`ReviewQueue`/`detect_escalations` — 僅差エスカレーション (REQ-101)
- `Ledger`/`SnapshotStore` (+Persistent) — 全操作記録

## 主要設計決定

### D1: マルチスタート摂動は決定論列 🔵
乱数不使用。start index i (0..N-1) に対し格子 ±frac の等間隔グリッド・scale の対数一様
グリッド・占有率は固定ラテン超方格テーブルで一意に決まる (NFR-102)。i=0 は無摂動 (基準解)。

### D2: マルチスタートの精密化は direct refine 🟡
各 start は `backend.refine` 直呼び (scale+lattice、`ms_max_cycles` 既定 15)。staged フルは
コスト過大 (FR-234「探索モード精密化と同等に抑える」に整合)。

### D3: basin クラスタリング 🟡
収束解を正規化パラメータベクトル (初期値スケールで無次元化) 化し、相対距離 < tol (既定 1e-2)
を union-find (M1 clustering の実装パターン再利用) で連結。basin 代表は chi2 最小解。
発散 start (chi2=inf) は除外しカウント報告 (REQ-102)。

### D4: FR-313 の仮説構築 🔵/🟡
- 仮説 A (固溶体): 区間フレームを単相 warm-start 逐次 direct refine、区間合計 bic
- 仮説 B (二相): 端成分 2 相 (区間端点の A 仮説格子で初期化・格子固定 🟡)、scale/wt 変化のみ
  解放で逐次精密化、区間合計 bic
- 両仮説の区間端点フレームでマルチスタート必須適用 (REQ-004)、basin 情報を metrics に記録
- verdict: ΔBIC ≥ 閾値で優位側、未満は "undecided" + Review Queue (REQ-101)

### D5: FR-316 の探索順序 🔵
§15-1 確定案: k=1 から**貪欲挿入** — 既存分割に境界 1 本を追加する全候補 (粗グリッド刻み G、
既定 5 フレーム) を評価し、合計コスト = Σ区間 bic + β·(境界数)·ln(n_frames) が最小の挿入を
採用。改善 < 閾値 (既定 10.0) で打ち切り。採用境界は ±G の細密スキャンで再配置。
区間コストは軽量逐次 refine (changepoint/木探索なし) の bic 和 🟡。

### D6: 分割仮説の保存 🔵
各 k の分割を `Hypothesis` (id="seg-k{K}-XXXX", frame_range=全区間, phases=区間代表相) として
保存し、`SegmentationResult.partitions` で代替閲覧可能。ledger に境界・evidence を記録。

### D7: Issue #3 の較正 🔵
`ChangepointConfig` に `new_peak_min_height_frac` (既定 0.05) と `new_peak_persistence`
(既定 2) を追加 (既定値付き非破壊)。SequentialEngine は未マッチピークの**連続出現カウント**を
保持し、持続 M フレーム以上で初めて new_peaks 指標を発火させる。

### D8: 吸収補正の実装位置 🔵/🟡
- パラメータ文法拡張: `parse_param` が `"global.{key}"` → `(-1, key)` を返す (非破壊追加)
- `SimulatedBackend(absorption=AbsorptionConfig(...))`: simulate/refine の前方モデルに
  透過因子 **A(θ; μt) = exp(−μt / cos θ)** を乗算。`"global.mu_t"` ∈ free_params のとき
  μt をフィットベクトルへ追加し、restraint ペナルティ **w_r·(μt − μt_calc)²** を chi2 に加算
- `RefinementResult.globals: Mapping[str, float]` (既定 {}) に fitted μt を記録 (非破壊)
- CellConfig 提供時: μt_calc はユーザー指定値 (MuCalculator は Protocol のみ、REQ-019)。
  未提供時: 弱 restraint (w_r 小) + `warnings` に経験推定モード明示 (REQ-018)
- GSASIIBackend: v1 は吸収を scale に畳み込む近似とし docstring に制限明記 🟡

### D9: 結合出力 🟡
`FrameRecord` は不変のまま、`operando/output.py` の `combined_csv(trajectory, echem, path)` が
echem 列 (V/I/Q/x) を frame_index で外部結合して CSV 化。転移点 x/V は判別境界フレームの
echem 値から線形補間で算出、σ は隣接フレーム間隔。

## ディレクトリ構造 🔵

```
src/tsumugin/
├── _json.py           # 新規 (Issue #5)
├── multistart/        # 新規: perturb / basin / engine
├── operando/          # 新規: echem / cell_phases / discrimination / segmentation /
│                      #        hysteresis / output
├── absorption/        # 新規: model (AbsorptionConfig/MuCalculator)
├── model/             # 拡張: cell.py 新規、channel.py kind 追加、metrics.multistart
├── backends/          # 拡張: base (global param 文法 / RefinementResult.globals)、
│                      #        simulated (吸収項)
└── sequential/        # 拡張: changepoint (Issue #3)、thermal (Issue #4)
tests/  test_multistart*.py / test_echem.py / test_cell_phases.py / test_discrimination.py /
        test_segmentation.py / test_hysteresis_output.py / test_absorption.py / test_m3_e2e.py
```

## 非機能要件の実現方法

- **NFR-001**: 判別は区間端点のみマルチスタート・direct refine (小グリッド合成で <30 秒) 🟡
- **NFR-002**: 粗→細 2 段 (D5)。区間コストはメモ化 (同一区間の再評価回避) 🟡
- **決定論**: 摂動列・クラスタ順・境界候補順すべて index 安定ソート 🔵
- **セキュリティ**: echem CSV は stdlib csv で読み、数値変換失敗は明示エラー (eval 不使用) 🔵

## 技術的制約 🔵

- コア依存 numpy のみ (xraylib/.mpr は Protocol + NotImplementedError)
- 既存 API 後方互換 (REQ-404): parse_param/RefinementResult/ChangepointConfig の拡張は
  既定値付き・既存テスト 433 件無改変 green
- thermal の onset 修正 (Issue #4) は既存テストの期待値変更を伴う — 変更理由をテストに明記

## 関連文書

- [dataflow.md](dataflow.md) / [interfaces.py](interfaces.py) / [要件定義](../../spec/m3-operando/requirements.md)
- DB スキーマ / API 仕様: なし (M3 に新規 HTTP API・永続 DB なし) 🔵

## 信頼性レベルサマリー

- 🔵: 24 件 (62%) / 🟡: 15 件 (38%) / 🔴: 0 — **品質評価**: 高品質
