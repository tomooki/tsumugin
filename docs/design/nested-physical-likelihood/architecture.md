# nested 物理尤度配線 (Issue #76 / FR-313×FR-125×FR-122) — 設計

## 1. 問題 (v1 の数学的欠陥)

v1 の `_build_evidence_problem` (operando/discrimination.py) は区間 Σbic を**定数尤度**
(`logL(θ) = -Σbic/2`, θ 非依存) で包むサロゲート。帰結:

- 実 dynesty: 一様事前分布 × 定数尤度 → `-logZ = Σbic/2` (bic 一次の半分)
- Laplace フォールバック: map_point/hessian 無し → `score(metrics)` = Σbic (bic 一次と厳密一致)
- 発動条件が |ΔBIC_bic| < close_threshold のため、どちらの経路でも
  |Δ_nested| ≤ |ΔBIC_bic| < 閾値 → **構造的に僅差を解消できない**

## 2. 中核設計: 区間 joint EvidenceProblem

### 2.1 数学

区間 [start, end] の各フレーム i は条件付き独立 (仮説 A の warm-start は初期値の継承であって
パラメータ共有ではない; B は毎フレーム独立精密化)。よって区間 evidence は厳密に分解する:

```
logZ_interval = Σ_i logZ_i,   logZ_i = ∫ L_i(θ_i) π(θ_i) dθ_i
```

これを **1 個の joint EvidenceProblem** で表現する (arbitrate/run_with_fallback の
単一 problem 契約・PR #75 三重ガードを不変に保つため):

- θ = 各フレームの解放パラメータの連結。次元名は `frame{i:04d}.{param}` で
  lexicographic 昇順 = フレーム major の決定論順 (EvidenceProblem.priors 昇順契約)
- `logL(θ) = Σ_i -χ²_i(θ_i)/2` — χ²_i は backend の**公開 API** で評価:
  `backend.refine(RefinementModel(phases=θ適用済み, free_params=∅), max_cycles=…)` は
  LM ループに入らず初期状態の chi2 を返す (純評価・全 backend 共通契約)
- `map_point` = 各フレーム精密化済み値の連結
- `hessian` = 各フレーム JᵀJ のブロック対角 (ブロック対角の ln|H| = Σ ln|H_i| なので
  joint Laplace = Σ per-frame Laplace が自動で成立)
- `metrics` = v1 と同一の Σbic 合成 metrics (**BIC フォールバック値を bic 一次と厳密一致に保つ**
  — PR #75 のガード/メッセージング前提を壊さない)

### 2.2 曲率の公開 (Issue #76 項目 3)

`RefinementResult` に additive optional フィールド `curvature: Curvature | None = None` を追加:

```python
@dataclass(frozen=True)
class Curvature:
    param_names: tuple[str, ...]  # J の列順 (SimulatedBackend: names 順 + 末尾 mu_t)
    point: np.ndarray             # 最終受理パラメータベクトル p
    hessian: np.ndarray           # JᵀJ (weighted, restraint 行含む) = -logL の Hessian (logL=-χ²/2)
```

- SimulatedBackend: `_apply_lattice_sigma` が最終 p で再計算している jac を refine() 側へ持ち上げ、
  σ 導出と Curvature 充填で共有する (二重計算しない)。解放パラメータゼロの早期リターンは None
- GSASIIBackend: **v2 スコープ外** (None のまま)。GSAS の covMatrix 配線はコスト予算の検討と一体で
  M-later (Issue #76 本文どおり)
- 恒等 0 列 (非識別パラメータ) を含む JᵀJ は非正定値 → LaplaceBackend の既存ガードが BIC へ縮退する
  (これが正しい縮退: 非識別次元があるモデルの Laplace は定義できない)

### 2.3 事前分布 (FR-125)

既存 `build_prior_from_restraints` へ渡す `RestraintSpec` を**精密化状態から自動構成**する
(`restraints_from_state`)。判別仮説は明示 restraint を持たないため、「格子シフト上限」の発想で
精密化済み値を中心とする有界区間を組む:

- lattice.{a,b,c}: uniform [v(1−m_lat), v(1+m_lat)], m_lat 既定 0.02 (Rietveld 収束半径オーダー)
- scale: uniform [0, v·f_scale], f_scale 既定 4.0 (v≤0 の縮退は [0, 既定上限])
- その他 suffix: prior.py の種別既定へ委譲

margins は `PhysicalProblemConfig` (frozen) で上書き可。**MAP が事前分布の台に必ず入る**
(v 中心の区間なので構成的に保証。台の外の MAP は nested/Laplace 双方を壊すため、これは不変条件)。

### 2.4 Laplace の事前密度項 (真の logZ 近似化)

現行 LaplaceBackend は log π(θ_map) を省いた相対 evidence。省略項 Σ ln(prior 幅) は
**次元数・事前幅が異なる仮説間で相殺しない** (A: 4/frame vs B: 2/frame) ため、v2 で
`PriorSpec.log_pdf(x)` を追加し、map_point/hessian/priors が揃い次元一致のときのみ

```
logZ_laplace = logL_map + Σ_j log π_j(θ_map,j) + (k/2)ln(2π) − (1/2)ln|H|
```

を返す (真の logZ の Laplace 近似 → nested と同一スケールで比較可能)。priors 欠如/次元不一致は
従来式のまま。BIC フォールバック経路は不変。

### 2.5 経路検出の細分化 (v1 の潜在欠陥修正)

三重ガード① (経路一致) は `adjudicated_by` 比較だが、「実 Laplace (-logZ スケール)」と
「Laplace の BIC フォールバック (Σbic スケール)」がどちらも `"laplace"` になり、スケールの違う値を
同一経路と誤認しうる。v2 は per-hypothesis の実効経路を 3 値で検出する:

```
effective_route = "nested" | "laplace" (実曲率) | "bic_fallback" (value == laplace.score(metrics).value)
```

- route_consistent は実効経路の厳密一致を要求
- `"bic_fallback"` 同士は v1 と同じく解消不能 (Δ=ΔΣbic<閾値) → 正直に undecided (従来挙動保存)
- BIC フォールバック検出は LaplaceBackend が文書化済みの契約
  「フォールバック時 value が score(metrics).value に一致」を用いる

### 2.6 スケール整合 (ΔBIC ≈ 2Δ(-logZ))

BIC = -2 logL_max + k ln n ≈ -2 logZ + O(1)。evidence value = -logZ なので、物理経路
(nested / 実 Laplace) の Δvalue は **×2 で BIC 等価スケール**に直してから close_threshold と
比較する (`delta_bic_equiv = 2Δvalue`)。bic_fallback 経路は既に BIC スケールなので ×1。
`DiscriminationResult.nested_delta_evidence` には BIC 等価スケールの値を格納する
(既存フィールドの意味「ΔBIC 相当」に合わせる)。

## 3. 配線 (FR-313 discrimination への適用)

- `DiscriminationConfig.physical_problem: PhysicalProblemConfig | None = PhysicalProblemConfig()`
  — nested_arbitration 発動時に物理 problem を構築する (既定 ON)。None で v1 サロゲートへ
  明示的に退避 (escape hatch・既存サロゲートテストの互換維持)
- `_IntervalOutcome` に per-frame `results: dict[int, RefinementResult]` を追加
  (現状 endpoint のみ保持 → 物理 problem は全 comparable フレームの精密化状態が要る)
- 物理 problem 構築が失敗 (フレーム欠損等) したら v1 サロゲートへ縮退し warning で明示
  (例外化しない — 判別を止めない既存契約)
- FR-316 区間分割・M10 anchor crossover への一般化は動作実証後 (Issue #76 項目 4 どおりスコープ外)

## 4. モジュール配置

| モジュール | 内容 |
|---|---|
| `backends/base.py` | `Curvature` dataclass + `RefinementResult.curvature` (additive) |
| `backends/simulated.py` | 最終 p の jac 共有 + Curvature 充填 |
| `nested/base.py` | `PriorSpec.log_pdf` |
| `nested/laplace.py` | 事前密度項 (priors+MAP+H 揃い時) |
| `nested/physical.py` | **新設**: `restraints_from_state` / `FrameState` / `build_physical_problem` (joint 構築)。numpy-only、backend は Protocol 経由 |
| `operando/discrimination.py` | 物理 problem 配線 + 実効経路検出 + BIC 等価スケール |

## 5. ②③ 露出 (★不変条件)

**非露出を宣言する** (黙って未露出にしない):

- nested (FR-500) の露出障壁だった「EvidenceProblem.log_likelihood が callable で JSON 化不可」は、
  本設計の**内部構築化** (JSON 化可能な精密化状態から ① 内で problem を組む) により原理的には解消
- しかし呼び手となる discrimination (FR-313) 自体が ② に無く、FrameSeries/PhaseInstance の
  JSON spec 設計 + 実データ backend (GSAS) 接続が前提になる。これは本 Issue のスコープ
  (裁定力の獲得) と独立した露出設計なので、**LAYER1_FEATURES の非露出理由を更新**し、
  ② 露出 (discriminate ツール + nested オプトイン引数) を**新 Issue に切る**

## 6. 受け入れ基準 (Issue #76)

1. 合成データで「bic 僅差 (|ΔΣbic|<閾値) だが実曲率 Laplace は判別可能 (|2Δvalue|≥閾値)」を構成し、
   verdict が確定する (決定論・dynesty 非依存)
2. dynesty 導入環境では nested 経路も同符号で確定する (seed 固定・logZ±err 併記, skip ガード)
3. PR #75 三重ガード + メッセージングが不変に通る (bic_fallback 経路の従来挙動保存を含む)
4. ガード系テストは変異させて fail することを実証してから受け入れる
