# M9 高温 in situ 逐次 Rietveld 自動解析 アーキテクチャ設計

作成: 2026-07-06
前提: M7 で単一フレーム実構造自動 Rietveld (`tsumugin.autorietveld`) が完成、M8 で agentic 閉ループの
3 層分離 (決定論コア + 薄い MCP + Claude Code plugin, `tsumugin.refine_loop`) が完成した。
M6 で相同定エンジン (`tsumugin.reference` + `tsumugin.mp`) が完成した。しかし **実構造を温度/時間
系列で逐次精密化する層は未実装** — 既存の `tsumugin.sequential` / `tsumugin.operando` は抽象
`RefinementBackend` Protocol + `SimulatedBackend` (合成強度) の上でのみ動作し、GSAS 実構造には未配線。

## 0. スコープと達成目標

**高温 in situ (Parametric sequential fitting)** の全自動解析を M7/M8 と同様に実装する:

- **実証データ 1 (T-seq)**: GSAS-II 公式チュートリアル "Parametric sequential fitting"
  (CuCr₂O₄ + CuO, 17 フレーム 7–300K, 11-BM 放射光 `.fxye`)。目標 wRp 13–17%。相転移は
  2 次 (b→c 収束) で新相出現なし。
- **実証データ 2 (T-cyc)**: Jana2020 Cookbook Example 02.6 "CaTeO3 cyclic"
  (14 フレーム, 実験室 X線 Cu Kα, XRDML)。**alpha CaTeO3·H₂O (P2₁cn) → delta CaTeO3 無水
  (P2₁ca) の相転移で delta が系列途中で出現** (フレーム 150–300 で共存, 目標 wRp ~9%)。
  **初期相 (alpha) のみ与え、出現する delta は自動相同定する** = 本 M9 の中心課題。

**3 層構造 (M8 継承)**: ① 決定論コア (numpy + GSAS 遅延) / ② 薄い MCP (計器+アクチュエータ) /
③ Claude Code plugin (agentic 判断)。閉ループでチュートリアル同等以上の解析を自動完了する。

## 1. 設計原則 (M7/M8 継承)

- **提案 ≠ 適用**: 相同定・変化点は候補を返すのみ。相追加はループが ledger 記録の上で可逆に行う。
- **警戒すべき自動化**: 新相追加 (ModelAction) は残差だけから一意に決まらない。相同定 (化学的文脈)
  を根拠にするが、③/人間の承認点を明示する。規則が自律で回すのは safe 部分集合のみ。
- **受理基準は Rwp 改善 ∧ 物理妥当性維持** (過剰適合ガード)。相追加は「未指数ピークの説明 ∧
  相分率が有意 ∧ 全体 Rwp 改善」で受理。
- **不変条件継承**: P2 非破壊 (ledger 追記 + snapshot)・NFR-102 再現性 (種固定・安定ソート)・
  NFR-105 ハッシュチェーン・**コア import は numpy のみ** (GSAS/MP/pymatgen は遅延 import)。

## 2. モジュール構成 — `tsumugin.insitu` (M9 新規)

```
tsumugin/insitu/
├── model.py        # frozen dataclass: FrameRietveldResult / SequentialRietveldResult /
│                   #   ParametricAnalysis / PhaseAppearance (numpy-only)
├── phaseid.py      # 相同定→PhaseSpec 物質化ブリッジ (要素3): identify_and_materialize_phase
│                   #   (numpy コア + MP/GSAS/pymatgen 遅延)。M6 reference の未配線ギャップを埋める
├── parametric.py   # 系列のパラメトリック解析: 格子 vs T・転移 onset/midpoint (sequential.thermal 再利用)
├── engine.py       # run_sequential_rietveld (実構造 GSAS 逐次, ウォームスタート + 変化点で自動相追加)
│                   #   GSAS 遅延 import。単一フレームは autorietveld.run_auto_rietveld へ委譲
└── __init__.py

tsumugin/autorietveld/engine.py   # + initial_cells 引数 (逐次ウォームスタート, 追加のみ)
tsumugin/reference/io.py          # + parse_xrdml/load_xrdml (Panalytical XRDML ローダー)
tsumugin/mcp/tools.py             # + sequential_rietveld / identify_and_add_phase / parametric_fit
plugins/tsumugin/                 # ③: skills/insitu + commands/insitu-analyze
```

コア (model/parametric/phaseid の numpy 部) は numpy のみ。GSAS 駆動は engine 内、MP/pymatgen は
phaseid の遅延 import 境界内。

## 3. 要素1 — 逐次実構造エンジン (engine.py)

M7 `run_auto_rietveld` の**時間系列アナロジー**。GSAS-II チュートリアルの sequential refine
("copy results to next histogram" = 直前フレームの精密化結果を次フレームの初期値に引き継ぐ) を
フレーム毎の `run_auto_rietveld` 呼び出しで実現する (単一 gpx 巨大プロジェクトでなく per-frame
オーケストレーションを採る: 実装単純・テスト容易・M7 の確立したガードレールを再利用)。

```python
def run_sequential_rietveld(
    frames: Sequence[FrameSpec],          # 各フレーム: data_path + axis_value(温度/時間) + 共通 instprm/geometry/radiation
    initial_phases: Sequence[PhaseSpec],  # フレーム 0 の既知相 (CaTeO3 は alpha のみ)
    *,
    phase_id: PhaseIdConfig | None = None,   # 新相自動同定の設定 (None なら相追加しない)
    ledger: Ledger | None = None,
    warm_start: bool = True,
    two_theta_limits: tuple[float, float] | None = None,
    max_frames: int | None = None,
    seed: int = 0,
) -> SequentialRietveldResult
```

各フレームの処理:
1. **フレーム 0**: `run_auto_rietveld` を M7 フル段階解放で実行 (初期相の確立)。
2. **フレーム i>0 (ウォームスタート)**: 直前フレームの `refined_cells` を `initial_cells` に渡し、
   現在の相集合で `run_auto_rietveld` を実行 (格子が温度で滑らかにドリフトするため大域最適近傍から
   開始でき収束が速く安定)。
3. **変化点判定**: `sequential.changepoint.detect_changepoint` に Rwp 履歴・格子履歴・新規未指数
   ピークを渡す。未指数ピークは M7 結果 + `reference.background`/`search.peaks` で抽出。
4. **新相の自動同定 (変化点 ∧ phase_id 有効)**: `insitu.phaseid.identify_and_materialize_phase`
   を残差パターン + 元素ヒントで呼び、MP から候補相を得て **PhaseSpec を物質化** (CIF を取得/生成)。
   相集合に追加して当該フレームを再精密化し、**受理基準 (未指数説明 ∧ Rwp 改善 ∧ 妥当性維持)** を
   満たせば採用。以降のフレームは拡張相集合を引き継ぐ。棄却時は据え置き (可逆・ledger 記録)。
5. **相の消失**: `sequential.lifecycle.LifecycleTracker` で相分率ヒステリシスを追跡し、
   一定フレーム連続で寄与ゼロなら相を落とす候補にする (提案のみ、除去は ③/受理基準)。

全フレーム遷移を ledger に追記。非有限 (精密化失敗) は M7 同様 Rwp=inf に変換し当該フレームを
`refine_failed=True` で伝播 (直前成功フレームから warm start 継続)。

**受理基準 (相追加, §1 過剰適合ガード)**: `(1) 新相の相分率 > frac_min` かつ
`(2) 全体 Rwp が eps 超改善` かつ `(3) validity.passed 維持`。3 条件全てで採用。

## 4. 要素2 — 相同定→PhaseSpec ブリッジ (phaseid.py) 【M6 ギャップの解消】

M6 の `reference.identify_phases`/`identify_phase_mixtures` は候補をランキングするが、
**autorietveld が精密化できる `PhaseSpec` (CIF パス) への物質化が未配線** (M6 探索で確認)。
本ブリッジがそれを埋める:

```python
def identify_and_materialize_phase(
    two_theta, intensity,                # 残差 (既知相を引いた後) or 生パターン
    *, elements: Sequence[str],          # 化学的文脈 (既知 + 想定元素)
    provider: ReferenceProvider,         # 既定 MPReferenceProvider (遅延 import)
    workdir: str,                        # CIF 書き出し先
    exclude_phases: Sequence[str] = (),  # 既知相 (重複同定回避)
    subtract_bg: bool = True, kalpha2=..., refine_lattice: bool = True,
    top_k: int = 1,
) -> tuple[PhaseSpec, ...]               # 物質化した相 (CIF パス付き, ランキング順)
```

フロー: `identify_phases` (MP provider, Dara スコア, 格子精密化) → 上位候補の
`ReferencePhase.structure` (pymatgen) を **CIF に書き出し** (`CifWriter`) → その CIF パスで
`PhaseSpec` を組む。MP provider は `ReferencePhase` に実構造を保持 (mp.xrd 経由) するため CIF 化可能。
CaTeO3 の delta は MP に anhydrous CaTeO3 が存在するため同定・物質化できる。

**相同定の実装改善 (本 M9 スコープ)**:
- **残差ベース同定**: 既知相のピークを引いた残差から新相を同定する経路 (`exclude_phases` +
  背景減算) — 系列途中の新相出現に必須。既知相の calc ピークを `search.matcher` で除いて残差ピークを得る。
- **物質化 (materialization)**: pymatgen `Structure`→CIF 書き出し + `PhaseSpec` 生成。M6 で欠けていた配線。
- **多相 NNLS の厳密化** (余力): mixture の非負スケールをクリップ近似から真の NNLS へ (相分率の
  過小評価解消)。系列で相分率閾値判定に効く。

MP キー未設定/pymatgen 無しなら明示エラー (呼び出し側で skip 可、`@pytest.mark.gsas` と同様に gate)。

## 5. 要素3 — パラメトリック解析 (parametric.py)

系列の精密化結果から物理量を抽出 (`sequential.thermal` を再利用, numpy-only):
- **格子 vs 軸 (温度)**: 各相の a/b/c を軸に対して `fit_thermal_baseline` (多項式) で回帰、
  熱膨張係数と逸脱フレーム (転移候補) を得る。
- **相転移**: `estimate_transition` で相分率シグモイドから onset/midpoint±σ を推定
  (appearing=delta 出現・disappearing=alpha 消失)。
- **擬変数 (pseudo-variable)**: b/c 比等の派生量を系列で追跡 (CuCr₂O₄ の b→c 収束 = 2 次転移)。

## 6. 要素4 — 薄い MCP (計器+アクチュエータ, M8 パターン)

MCP_TOOLS に 3 ツール追加 (ループ丸ごとは出さない = ③ が回す):

| ツール | 入力 | 出力 |
|---|---|---|
| `sequential_rietveld` | frames spec (JSON) + initial_phases + 任意 phase_id | フレーム別 Rwp/格子/相分率・変化点・出現相・ledger |
| `identify_and_add_phase` | 残差パターン + elements + workdir | 物質化 PhaseSpec[] (CIF パス) + 同定根拠 (Dara スコア/未指数) |
| `parametric_fit` | 系列結果ハンドル + parameter + axis | 多項式係数・熱膨張・転移 onset/midpoint±σ |

既存 MCP パターン踏襲 (SDK 非依存の実処理層 + 遅延 import アダプタ, `to_dict`/`from_dict`)。

## 7. 要素5 — Claude Code plugin (③, agentic 判断層)

```
plugins/tsumugin/
├── skills/insitu/SKILL.md    # in situ 逐次解析の手順化: フレーム収集・sequential_rietveld 駆動・
│                             #   変化点で identify_and_add_phase → 新相を確認して追加 (ユーザー承認)・
│                             #   parametric_fit で転移特性・収束判定
└── commands/insitu-analyze.md # /tsumugin-insitu <frames...> --initial <cif>
```

③ が担う判断: **新相追加の採否** (相同定候補が化学的に妥当か・未指数を説明するか)・**構造改訂**・
リミット設定。SafeAction (背景/パラメータ解放/ウォームスタート) は決定論コアが自律。

## 8. データフロー

```
frames (XRDML/fxye) + initial CIF
        │
        ▼  ① run_sequential_rietveld  ── frame0 full staged (M7) ──▶ refined_cells
        │        │ warm-start (initial_cells) 각 frame                     │
        │        ▼                                                          ▼
        │   changepoint? ──yes──▶ ② identify_and_materialize_phase (MP) ──▶ PhaseSpec(delta.cif)
        │        │                     (③ が採否判断: 未指数説明∧化学妥当)      │
        │        ▼◀────────── 拡張相集合で再精密化・受理基準 ◀────────────────┘
        ▼
   SequentialRietveldResult ──▶ ⑤ parametric_fit (格子 vs T・転移 onset/midpoint)
        │
   ③ Claude Code plugin: MCP 3 ツールを反復駆動・新相はユーザー承認・収束判定
```

## 9. 段階計画

- **Phase A — データ/ローダー**: XRDML ローダー (`reference.io`) + M9 ベンチデータ整備 +
  alpha 初期相 CIF (Jana→CIF)。純テスト。
- **Phase B — コアモデル + パラメトリック**: `insitu.model` + `insitu.parametric`
  (thermal 再利用)。純 numpy テスト。
- **Phase C — 相同定ブリッジ**: `insitu.phaseid.identify_and_materialize_phase` +
  autorietveld `initial_cells`。純テスト (provider スタブ) + MP-gated 実同定。
- **Phase D — 逐次エンジン**: `run_sequential_rietveld` (ウォームスタート・変化点・自動相追加)。
  スタブ runner で純テスト + `@pytest.mark.gsas` 実データ。
- **Phase E — MCP 3 ツール + plugin + AGENT_PLAYBOOK**。
- **Phase F — 実データ検証**: T-seq (CuCr₂O₄ 逐次, wRp 13–17%) + T-cyc (CaTeO3 delta 自動同定,
  wRp ~9%, MP-gated)。/code-review ループ。

## 10. テスト戦略

- モデル/パラメトリック/ブリッジ (provider スタブ): 純テスト (GSAS/MP 不要, 決定論)。
- 逐次エンジン: スタブ runner (固定 result 列) で warm-start/変化点/相追加の論理を純テスト。
- 実データ: `@pytest.mark.gsas` (+ CaTeO3 は MP キー gate)。frame0 収束 → warm-start 2 フレーム →
  全系列。CuCr₂O₄ で wRp 帯・CaTeO3 で delta 自動出現を回帰。
- 再現性: 同一種で `SequentialRietveldResult` ビット同一・ledger `verify()` True (NFR-102/105)。

## 11. スコープ外 (M-later)

- 単一 gpx GSAS-II ネイティブ sequential (copy-forward) の最適実装 (per-frame で機能等価)。
- COD/ICSD 供給元 (Issue #10)。座標の系列トラジェクトリ精密化・異方性歪みの系列追跡。
- operando 電気化学チャネル同期 (既存 `operando.echem` は合成のみ; 実 operando は M-later)。
