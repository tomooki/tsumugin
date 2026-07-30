# Tsumugin — 多仮説・全自動 Rietveld 解析プラットフォーム 仕様書

**Version:** 0.3.1 (draft)
**Date:** 2026-07-14
**Backend:** GSAS-II (GSASIIscriptable)
**Status:** 仕様凍結候補
**改版履歴:**
- v0.1→v0.2: 名称確定 (Tsumugin)。evidence多バックエンド化、判別区間のIC自動分割、マルチスタート大域最適確認、operando吸収補正、化学妥当性のインターフェース化、最終選択2モード制、中性子/マルチヒストグラム対応、MEM対応を追加。
- v0.2→v0.3: 層状セルは透過法のみ対応に確定。残余の未解決課題を推奨案で確定 or 実装時確定に振り分け。
- v0.3→v0.3.1: M1〜M5 実装照合に基づく条文明確化 (FR 番号・要件は不変)。FR-115 の R 改善の定義、FR-302/306/311/314/323/324 のスコープ注記、FR-242 の joint 充足経路、FR-603 の MPF 範囲、NFR-103 の打ち切り方式を実装実態に整合。機能ギャップは仕様を変えず Issue 管理 (FR-123/116/306σ/313裁定/317/322/324α/325/231-234/ベンチ公開)。

---

## 1. 目的とスコープ

### 1.1 目的

粉末回折(X線・中性子)の相同定・多相Rietveld精密化・時系列(operando / in situ 高温)解析を、
**AIエージェントと人間の介入点を明示的に設計した上で**全自動化するプラットフォームを構築する。

Dara (Fei & McDermott et al., Chem. Mater. 2026) の中核思想を継承する:

1. **多仮説主義** — XRDは構造情報しか持たず、1つのパターンに複数の相組合せが適合しうる。単一解を断定せず、妥当な全仮説を列挙・ランキングし、曖昧さを明示する。
2. **精密化の前倒し** — Rietveld精密化を「最後の仕上げ」ではなく相同定の検証エンジンとして探索ループ内で使う。
3. **null hypothesis testing** — 固溶体 vs 端成分混合のような競合解釈を明示的に比較する。
4. **解釈可能性** — ピークマッチング・R値・格子シフトなど、人間が検証可能な量でスコアリングする。

その上でDaraが扱わない領域に拡張する:

- **多相「精密」解析** — 占有率・原子座標・サイズ/歪み異方性まで含む段階的精密化の自動運転。マルチスタートによる大域最適性の確認。
- **Operando電池解析** — 電気化学同期、セル構成に基づく吸収補正、固溶体 vs 二相反応の情報量基準に基づく自動判別。
- **高温シーケンシャル解析** — 相出現/消滅検出、転移温度推定、速度論解析への出口。
- **マルチプローブ** — X線+中性子(CW/TOF)の同時(joint)精密化。
- **MEM電子/核密度解析** — 精密化後の構造因子からのMEM密度マップ生成。
- **エージェント介入層** — 非破壊設計を前提に基本 `auto` で運転し、最終選択のみ「エージェントモード / 人間モード」を切替可能とする。

### 1.2 非スコープ (v1)

- 未知構造の ab initio 構造決定。未知相フラグと残差ピークの外部引き渡しインターフェースのみ。
- PDF解析(フックのみ確保)。
- 磁気構造精密化。
- 2D検出器の方位解析(積分は前処理として対応)。
- 反応経路・合成可能性の**予測計算そのもの**(外部モジュール接続、§FR-412)。

---

## 2. 設計原則

| # | 原則 | 帰結 |
|---|---|---|
| P1 | 多仮説を第一級オブジェクトにする | 「解」ではなく「仮説集合+確率/ランク」を常に出力 |
| P2 | **構造的非破壊性** | 破壊的操作(生データ削除・上書き・履歴改変)はシステムに存在しない。全状態は追記+スナップショットで、任意時点へ revert 可能。エージェントに渡す権限セットにも破壊的操作は含まれない |
| P3 | trust-based automation | P2により内部操作は既定 `auto`。最終選択のみモード制(§FR-402) |
| P4 | 精密化は必ずガードレール付き | 段階的解放+発散検知+自動ロールバック |
| P5 | 時系列はトラジェクトリ | warm start、相ライフサイクル、changepoint |
| P6 | 測定へのフィードバック | 不確実性→次測定提案(OED出力、PyBOED連携) |
| P7 | バックエンド交換可能性 | RefinementBackend / EvidenceBackend / MEMBackend / ChemPlausibility の各抽象インターフェース |

---

## 3. 全体アーキテクチャ

```
┌──────────────────────────────────────────────────────────────┐
│  Interfaces:  Web UI / Python API / REST API / MCP Server     │
├──────────────────────────────────────────────────────────────┤
│  Agent Layer (LLM)                                            │
│   - Strategy Agent / Triage Agent                              │
│   - ChemPlausibility (プラグイン: rules | 外部予測 | LLM)       │
│   final-selection mode: agent | human                          │
│   action ledger / snapshot-revert                              │
├──────────────────────────────────────────────────────────────┤
│  Orchestrator                                                  │
│   - Hypothesis Manager (木探索・仮説分岐/併合/枝刈り)            │
│   - Sequential Engine  (warm start / IC-changepoint / 相追跡)   │
│   - Refinement Strategy Engine (段階解放・ガード・マルチスタート) │
│   - Evidence Engine    (backends: BIC | AIC | Laplace | Nested) │
├──────────────────────────────────────────────────────────────┤
│  Workers (Ray / multiprocessing)                               │
│   RefinementBackend = GSASIIscriptable (X線/中性子/TOF, joint)  │
│   PeakMatcher / PatternSimulator / AbsorptionModel              │
│   MEMBackend (Dysnomia 連携)                                    │
├──────────────────────────────────────────────────────────────┤
│  Data Layer                                                    │
│   Phase Library / Project Store (HDF5+SQLite)                   │
│   CellConfig Library / Ledger / Snapshots                       │
└──────────────────────────────────────────────────────────────┘
```

### 3.1 GSAS-II 採用理由と役割分担 (既定バックエンド)

- **ネイティブのシーケンシャル精密化**とパラメトリックフィッティング。operando/昇温の基盤。
- **X線・中性子(CW/TOF)・複数ヒストグラムのjoint精密化**を単一エンジンで扱える。BGMNに対する決定的優位で、本仕様のFR-240系の前提。
- **`GSASIIscriptable`** によるヘッドレス自動化。
- **オープンソース** — 収束ガード・吸収補正の内部検証と拡張が可能。
- 占有率・座標・異方性ADP・剛体を段階戦略の管理下で解放できる。

**既知のリスク**: 無人運転での最小二乗発散。→ §6のガードレール+マルチスタートで吸収。

#### 3.1.1 第 2 バックエンド: Bruker TOPAS (M12)

P7 (バックエンド交換可能性) の実体化として、**同一の `PhaseSpec`/`HistogramSpec`/
`RefinementStage` から TOPAS でも自動 Rietveld を回せる** (`tsumugin.topas`)。② では
`backend="gsasii"|"topas"` で選び、可用性は `list_refinement_backends` で確認する。

- **選ぶ理由**: GSAS で乗り切らない異方線幅/微細構造モデル、TOPAS 固有マクロ、そして
  **バックエンド間の独立確認** — 同じデータと構造から 2 実装が同じ格子・同じ相分率へ落ちれば
  大域最適の強い傍証になる (実装のバグまで含めて独立なので `multistart` の初期値摂動より強い)。
- **同一にしたもの**: 段階解放の入出力契約、`r_wp` のセマンティクス (TOPAS の `r_wp_dash` は
  背景差引きで非互換なので使わない)、失敗の chi2=inf 縮退、物理妥当性ゲート。
- **同一にできないもの**: **解放の順序**。GSAS は装置ファイルの Caglioti U,V,W から始まるが
  TOPAS は汎用初期値から始まるため、格子より先にプロファイルを合わせないと格子が幅の不一致を
  吸収して悪化する。レシピはバックエンドごとに持つ (`topas.recipe.build_topas_recipe`)。
- **非対応**: MEM 経路 (GSAS の `.gpx` ハンドルに依存)、operando 逐次 (`sequential_rietveld` /
  `anchored_sequential` は GSAS 固定)、`stability` 診断ゲート、レシピ探索との併用。
  いずれも**黙って GSAS へ落とさず**明示的に断るか警告として結果に出す。

到達点と未達は `docs/benchmark/m12-topas/README.md`、設計は
`docs/design/m12-topas-backend/architecture.md`。

---

## 4. データモデル (主要エンティティ)

```yaml
Project:
  id, meta(sample, chemistry, instruments), created_at
  final_selection_mode: agent | human          # FR-402
  datasets: [Dataset]

Dataset:
  id, kind: single | sequence
  sequence_axis: none | time | temperature | potential | capacity | custom
  frames: [Frame]
  external_channels: [ExternalChannel]
  cell_config_ref: CellConfig | null           # operando用 (FR-317)

Frame:
  id, index, axis_value(s)
  histograms: [HistogramRef]                   # マルチヒストグラム (FR-241)

HistogramRef:
  probe: xray | neutron_cw | neutron_tof
  data_ref, instprm_ref, bank_id, integration_meta

Hypothesis:
  id, parent_id
  frame_range: [start, end]
  phases: [PhaseInstance]
  refinement_state: gpx_snapshot_ref
  metrics: {Rwp, Rpb, GOF, evidence{backend, value, logZ_err},
            peak_match_score, unmatched_peaks, multistart{n, n_basins}}
  status: candidate | refined | accepted | rejected | superseded
  accepted_by: agent | human | null
  provenance: [LedgerRef]

PhaseInstance:
  phase_ref, lattice{...}±σ, scale, wt_frac±σ,
  microstructure{size, strain, anisotropy}, texture{SH係数},
  occupancies{site: val±σ}, coordinates{...},
  lifecycle: {birth_frame, death_frame, confidence}

CellConfig:                                    # FR-317
  geometry: transmission | capillary           # 層状(積層)セルは透過法のみ対応 (v0.3確定)
  layers: [{role: window|electrode|electrolyte|separator|collector,
            material(組成 or 物質名), thickness_mm, density}]
  beam: {energy_keV or wavelength, size}
  # 層情報から μt を組成計算(xraylib)。未知項は精密化変数に昇格

ExternalChannel:
  kind: echem(V, I, Q, x) | temperature | pressure | custom
  sync_map: frame_index -> value
```

---

## 5. 機能要件 — 相同定・多仮説探索

### FR-100 相ライブラリと前処理 (Dara継承)

- FR-101: COD / ICSD / MP / ユーザーCIF の取り込みと元素系フィルタ。
- FR-102: pymatgen StructureMatcher による重複排除(代表選出規則は設定可)。
- FR-103: MP hull エネルギーフィルタ(既定 100 meV/atom、MP未登録相は保持)。
- FR-104: DFT緩和構造の経験補正付き取り込み。
- FR-105: シミュレーションパターン・ピークリストのキャッシュ。X線/中性子それぞれの散乱長で生成。

### FR-110 単一パターン多仮説木探索 (Dara継承 + GSAS-II化)

- FR-111: ノード=相組合せの探索木。ピークマッチングスコアによる事前枝刈り。
- FR-112: 枝刈り閾値はスコア累積分布の変曲点で動的決定。
- FR-113: 各ノードで保守的設定の制約付き精密化(探索モード)。
- FR-114: 等構造相のJaccardクラスタリング。FoM = 1/((1−fit)+ΔU) で代表選出、他相は代替解として保持。
- FR-115: R改善閾値(既定2%)による枝打ち切り。最大相数既定5。(v0.3.1 明確化: 「R改善2%」は Rwp の**絶対ポイント差**で判定する — 親ノード Rwp − 子ノード Rwp < 2.0 ポイントで打ち切り。)
- FR-116: Jenks natural breaks による良好解クラスタ抽出+組成クラスタリング。
- FR-117: 未マッチ/extraピークの構造化出力(未知相フラグ)。

### FR-118 逐次減算同定 (単相/多相の統一エントリ, M11)

未知パターンは事前に単相か多相か分からないため、単相 (`identify_phases`) と多相 (`identify_phase_mixtures`) の2エントリは根本的に不整合。**残差に対する反復同定 (search-match-subtract)** で単一エントリに統一し、相数を入力に要求しない。FR-110/117 の部品を再利用する。

- FR-118-1: `identify_pattern` は未知パターン + 元素一覧 (+ 任意の既知相) を受け、**受理相集合 + 残差 + 未知相レポート**を返す単一エントリでなければならない。相数の事前指定を要求しない。
- FR-118-2: 反復1周は (a) **提案** — 現残差に `identify_phases` を全装備 (異方 rerank・動的閾値) で実行、(b) **受理** — 上位候補を**全採用相の joint 非負スケール最小二乗**で原パターンに再フィットし未説明強度が相対 ε 超減る候補のみ採る (**高速ピーク空間段**)、(c) **減算** — 残差 = 原パターン − Σ 採用相モデル、で構成せねばならない。
- FR-118-3: 停止は**残差 S/N** (`residual_significance`) がノイズ床閾値未満 (全て説明済) または全候補棄却でなければならない (bic はピーク空間で寛容すぎ; 実測)。単相は k=1 で自然停止し多相は相数だけ反復する。
- FR-118-4: 既説明ピークしか持たない decoy (元素部分集合の単純相等) は joint 再フィットでスケール≈0 になり自然棄却されねばならない (残差支持による棄却; hard ガードに依らない)。**化学的妥当性はコアに含めず第3層 (エージェント/人間) の判断に委ねる** — 必要時のみ opt-in の全元素系 hard ガードとして与える (コアの既定挙動には入れない)。
- FR-118-5: **多形判別は相同定アルゴリズムの責務**とする。ピーク探索の pseudo-R では同組成多形 (calcite vs aragonite) を分離できないため、システムは必要時に**注入された実 Rietveld 精密化 (FR-200) を相同定内で呼び** (深段)、真の Rwp/bic で多形・僅差候補を裁定してよい。Rietveld backend は注入境界 (コアは GSAS 非依存) とし、`group_by_composition` で同組成を集約して Rietveld 裁定の入力にする。深段の適用条件 (僅差時のみ/常時) は設定可能とする。
- FR-118-6: operando の per-frame 新相探索は `known_phases=現行相集合` を渡す形で本ループに一本化する (静的=空集合起点, 逐次=既知集合起点, 同一プリミティブ)。
- FR-118-7: 全反復・受理/棄却・スケール・残差 S/N を ledger に追記し (P2)、乱数を用いず同一入力でビット同一の受理相集合を返さねばならない (NFR-102)。

### FR-120 Evidence Engine (多バックエンド)

- FR-121: EvidenceBackend 抽象インターフェースを定義し、以下を実装。プロジェクト/解析単位で切替可能。
  - `bic`(**既定**)/ `aic` — 精密化残差から即時計算。木探索内のノード評価はこれを使う。
  - `laplace` — Hessian由来のLaplace近似evidence。中コスト。
  - `nested` — ネスト化サンプリング(dynesty / UltraNest)。logZ±誤差を返す。高コストのため用途を限定(FR-122)。
- FR-122: **階層的裁定** — 木探索・枝刈りは `bic`、生き残った上位仮説間でevidence差が閾値未満(既定 ΔBIC < 10)の競合のみ `nested` で再裁定する2段構え。フル`nested`運転も設定で可能。
- FR-123: ノイズ標準偏差の明示推定(EM反復)と尤度への反映。
- FR-124: 仮説確率は softmax + 温度較正で出力。backend間で確率の意味が異なることをレポートに明記(BIC近似 vs logZ)。
- FR-125: `nested` の事前分布は精密化restraint(格子シフト上限・占有率拘束等)から自動構成し、手動上書き可。

---

## 6. 機能要件 — 精密化戦略エンジン

### FR-200 段階的パラメータ解放

- FR-201: 既定テンプレート: scale+bg → lattice+zero → profile(size→strain) → 選択配向(SH段階増) → occupancy(拘束下) → 座標(restraint付) → ADP(iso→aniso)。
- FR-202: 各段で収束判定、悪化時は固定戻し or 仮説分岐。
- FR-203: YAMLテンプレート。系統別プリセット(層状酸化物 / PBA / polyanion / hard carbon共存系)同梱。

### FR-210 ガードレール

- FR-211: 発散検知(χ²発散、負占有率、格子暴走、負定値ADP、相分率ゼロ張り付き)。
- FR-212: 自動ロールバック→原因固定→再試行。3回失敗でTriage Agentへ。
- FR-213: 制約テンプレート(組成拘束、反位欠陥ペア連動、結合長restraintライブラリ)。
- FR-214: ガード発動は理由付きで ledger 記録。

### FR-220 多相精密解析

- FR-221: 相ごとに独立の戦略テンプレート適用。
- FR-222: 重量相分率±σ、微量相の検出限界推定(オプション)。
- FR-223: SH/March-Dollase選択配向、Stephens異方性ブロードニング。

### FR-230 マルチスタート大域最適確認 (v0.2新設)

- FR-231: 最終候補仮説に対し、初期値を系統摂動(格子±設定幅、scale対数一様、プロファイル摂動、占有率のラテン超方格)した N 本(既定 8–16)の独立精密化を実行する。
- FR-232: 収束解をパラメータ空間でクラスタリングし、basin数・各basinのχ²/evidenceを報告。単一basinなら「大域最適の傍証あり」、複数basinなら**それぞれを別仮説に昇格**して evidence 比較に回す(多峰性の隠蔽をしない)。
- FR-233: マルチスタートの適用範囲は設定可(既定: accepted候補の最終精密化時+FR-313判別時は必須)。
- FR-234: 実行はWorkerプールで並列化し、1本あたりのコストは探索モード精密化と同等に抑える。

### FR-240 中性子・マルチヒストグラム対応 (v0.2新設)

- FR-241: 中性子CW / TOF(マルチバンク)ヒストグラムの取り込み。TOFはバンクごとの instprm・DIFC 系パラメータを管理。
- FR-242: **joint精密化** — 同一構造モデルに対し X線+中性子、複数バンク、複数温度点などのヒストグラム群を同時フィット。ヒストグラムごとの scale・背景・プロファイルは独立、構造パラメータは共有(GSAS-IIネイティブ機能を利用)。(v0.3.1 注記: 実データの GSAS-II ネイティブ joint 精密化は `tsumugin.autorietveld.run_auto_rietveld([xray, nd, ...])` 経路で充足する。`tsumugin.joint` は仮説検証オーケストレーション層であり、Simulated バックエンドではヒストグラムごと χ² 合算の近似で動作する。)
- FR-243: ヒストグラムごとの重み(統計・信頼度)を設定可能とし、既定は統計重み。
- FR-244: X線/中性子コントラストを利用した占有率解放の推奨判定 — 散乱コントラストが十分なサイト(例: Ni/Fe/MnのX線類似 vs 中性子相違)を自動検出し、jointデータがある場合のみ当該占有率の解放を戦略に追加する。
- FR-245: 木探索(FR-110)はプライマリヒストグラムで実行し、生存仮説の検証精密化をjointで行う(探索コスト抑制)。

---

## 7. 機能要件 — シーケンシャル解析

### FR-300 共通基盤

- FR-301: warm start(継承対象は戦略で指定)。
- FR-302: GSAS-IIネイティブ sequential モードと独自オーケストレーションの選択制。(v0.3.1 注記: v1 は独自オーケストレーション (`independent`) のみ実装。`native` は選択インターフェースを予約済み (指定時は明示エラー) で、性能要求が生じた時点で実装する。実データの逐次解析は M9 `tsumugin.insitu` が独自オーケストレーションで充足。)
- FR-303: changepoint検出 — 残差時系列・格子微分・新規未マッチピークの複合指標。
- FR-304: changepoint近傍のみ残差ピークに対する局所木探索。
- FR-305: 相ライフサイクル(birth/death+確信度、ヒステリシスで点滅抑制)。
- FR-306: 相トラジェクトリ、格子±σトラジェクトリ、R値時系列の出力。(v0.3.1 明確化: 出力形態は構造化データ (CSV + 仮説系譜) を第一級とし、グラフ描画は Web UI / 外部ツールに委譲する。) (v0.3.2 注記更新: 格子 σ 出力は Issue #66 で実装済み — `sequential/trajectory.py` の `a_sigma`/`b_sigma`/`c_sigma`/`sigma_source`。)

### FR-310 Operando電池モード

- FR-311: 電気化学同期。CSV 汎用マッパを第一級とし、容量→組成x換算則を定義可。Biologic .mpr は専用ローダで対応 (Issue 管理)。(v0.3.1 改定: 北斗・HZ 形式は必要時追加のオプションに降格 — CSV エクスポート経由で代替可能なため。)
- FR-312: セル固定相(Be窓・Al集電体・グラファイト等)のテンプレート管理。
- FR-313: **固溶体 vs 二相反応の判別** — 同一区間に対し (a) 単相・格子連続変化、(b) 二相共存・分率変化 の両仮説をマルチスタート付き(FR-233)で精密化し、Evidence Engineで判別。既定は `bic` 一次判定+競合時 `nested` 裁定(FR-122)。
- FR-314: 電気化学量との結合出力(wt_frac(x)、格子(x)、dQ/dV との結合データ出力、転移点x/V±σ)。(v0.3.1 明確化: 「重ね描き」の描画本体は外部ツール/将来 UI に委譲し、コアは frame 結合済みの構造化データ (CSV) を提供する。)
- FR-315: 充放電往復のヒステリシス解析。
- FR-316: **判別区間の自動分割 (v0.2新設)** — 区間境界を人手で与える代わりに、ICペナルティ付きchangepoint分割(PELT / binary segmentation、ペナルティ=BIC項)で区間数と境界を自動決定する。各分割仮説(区間数 k = 1, 2, …)の合計evidenceを比較し、最良分割を採択。分割自体もHypothesisとして保存され、人間/エージェントが代替分割を閲覧・選択できる。粗い格子スキャン→境界近傍の細密化の2段で計算量を抑える。
- FR-317: **吸収補正 (v0.2新設, v0.3改定)** —
  - **層状(積層)セルは透過法のみ対応**とする。反射配置の層状セルはスコープ外(角度依存吸収の複雑さを排除し、透過の μt モデルに一本化)。キャピラリは円筒吸収モデルで対応。
  - CellConfig(§4)を入力として、各層の組成・厚み・密度から μt をエネルギー依存で計算(xraylib等)し、透過配置の吸収補正項を初期化する。
  - 補正パラメータ(実効μt)は**フィット変数として精密化**する。CellConfig由来の計算値は事前分布/restraintとして機能させ、物理的に説明可能な範囲に拘束する。v1は実効μtの1パラメータ+restraintで確定。
  - CellConfig が未提供の場合は経験的推定モード — 実効吸収パラメータを弱restraintで精密化し、レポートに明示警告する。推定値から逆算した μt を提示し、CellConfig入力を促す。
  - 充放電に伴う電極の μ 変化(例: Na量変化)はフレーム依存の緩慢変化として平滑restraint付きで追跡可能とする。
  - 中性子ヒストグラムに対しては該当する吸収/多重散乱補正モデルを同一インターフェースで切替。
- FR-318: **電気化学制約付き operando Rietveld (v0.3.2 追補 — 実装先行の欠番解消)** —
  定電流充放電の実測積算電気量 Q(t) を可動アルカリ量の独立測定として使う。n_e = Q/m × M/F 変換で
  per-frame の目標総アルカリ量 x_total(t) を組み、モード分岐 (diagnose[既定]/soft/fix/lock_fractions)
  で占有率精密化に接続する。diagnose は制約を課さず x_XRD と x_echem の乖離・実行可能性
  (feasibility = 多相域の不可逆容量検出) を報告のみ。fix は相間線形制約
  Σ Zᵢ(xᵢ−x_total)·Scaleᵢ=0 を課す。複数アルカリ元素サイトは合算、x_XRD は式量 (FW) 除算の
  モル平均。x₀ 校正は提案のみ (提案≠適用; 占有率が esd 付きで精密化されたときのみ x_refined)。
  実装: `operando.coulometry` + `insitu.charge` + autorietveld シーダー群 (PR #111)。
  ② は `alkali_budget` + `sequential_rietveld`/`anchored_sequential` の `charge_constraint` spec。

### FR-320 高温シーケンシャルモード

- FR-321: 温度チャネル同期。
- FR-322: 熱膨張ベースライン分離(多項式 / Debye-Grüneisen近似)。
- FR-323: 相転移検出と転移温度(onset/midpoint)±σ。区間分割はFR-316の枠組みを温度軸で再利用。(v0.3.1 明確化: σ は共分散由来を理想とするが、遷移隣接フレームの温度間隔による保守的代理散布度を許容する。いずれの場合も σ の由来を NFR-107 に従いレポートに明示する。)
- FR-324: 等温セグメントのα(t)抽出(JMAK等は外部委譲、CSV出力)。(v0.3.1 改定: parquet はオプション扱いに降格 — CSV で外部委譲要件を満たし、parquet は依存追加に見合う需要が生じた時点で追加。α(t) 抽出本体は Issue 管理。)
- FR-325: 反応経路グラフの自動構成と外部予測モジュール(FR-412)との照合フック。

### FR-330 アンカー基準双方向逐次解析 (M10)

前方単一パスの warm-start は、初期フレームの良否と転移域のセル汚染 (少数相の異方格子誤差) に脆い。信頼度の高いフレーム (アンカー) を起点に**両隣アンカーへ双方向**で独立解析し、区間ごとに最良経路を選ぶことで、転移を頑健に追跡する。FR-303/305/316/323 の枠組みを継承する。

- FR-331: **アンカー抽出** — 相同定の信頼度 (Dara スコア・スコアマージン・strain・未知相フラグ) が閾値以上のフレームを候補とし、実構造 Rietveld で **Rwp 低 + 物理妥当性 pass** を満たすフレームのみアンカーとして確定する (2 段ゲート: 同定信頼度→精密化確認)。理想は単相域だが、多相でも高信頼なら受理。
- FR-332: **アンカー精密化** — 各アンカーを実構造 Rietveld で精密化し、区間解析のウォームスタート種 (相集合 + 格子 + プロファイル) とする。端点フレームはマルチスタート (FR-233) で大域性を確認してよい。
- FR-333: **双方向区間解析** — 隣接アンカー対 `[L, R]` の内側フレームを、L の相集合で前方 (L→R)・R の相集合で後方 (R→L) に独立に warm-start 逐次精密化する。全フレームが 2 回解析される。区間は相互独立で並列化可。
- FR-334: **モデル選択による経路選定** — 相集合が異なる前方/後方フィットの比較は Rwp 生値でなく **IC (bic) で行う** (相数増加による Rwp 単調減少の偏りを排除)。区間の**総 bic を最小化する crossover 点**を選び (L..k は前方採用・k+1..R は後方採用)、相分率が物理的に単調な転移経路を得る。同一相集合の区間は Rwp/gof で足りる。
- FR-335: **物理妥当性ゲート** — 経路選定は bic に加え、格子妥当範囲・Uiso・占有率 (既存 `check_validity`) と、**結合距離・配位数の妥当性** (新規, pymatgen 遅延 import) で採否する。誤構造の偶然フィットを距離/配位で棄却。
- FR-336: **転移 onset の自動確定** — crossover 点が相集合変化 (新相 birth) の onset。FR-323 の onset/midpoint±σ 推定と整合させる。相の birth/death はヒステリシス (FR-305) で点滅抑制。
- FR-337: **非破壊・提案≠適用** — 前方/後方の両トライアルと選定理由 (bic 差・妥当性) を ledger に追記し、採用経路を記録する。棄却経路も保持し代替閲覧可 (P2)。
- FR-338: **決定論** — 双方向パスと crossover 選定は乱数を用いず、同一入力でビット同一の経路を返す (NFR-102)。アンカー端点マルチスタートの摂動種は固定。

---

## 8. 機能要件 — エージェント/人間介入

### FR-400 非破壊前提の自動運転 (v0.2改定)

- FR-401: **破壊的操作の構造的排除** — 生データの削除・上書き、ledger・スナップショットの改変・削除は、エージェント権限に限らずシステムのAPIとして存在しない(P2)。したがって内部解析操作(パラメータ解放、再精密化、枝刈り、仮説生成/降格、区間再分割)はすべて既定 `auto` で実行してよい。全操作はスナップショット後に実行され、revert可能。
- FR-402: **最終選択の2モード** — プロジェクト設定 `final_selection_mode`:
  - `agent` — 上位仮説のevidence・化学妥当性・マルチスタート結果を根拠に、AIエージェントが仮説を `accepted` 化する。裁定根拠は自然言語+定量指標で ledger に記録され、人間はいつでも閲覧・差し戻し(revert)できる。evidence差が閾値未満の僅差競合では自動的にエスカレーション(下記)。
  - `human` — エージェントは推奨順位と根拠を提示するのみで、`accepted` 化は人間の操作でのみ行われる。
  - モードは実行中いつでも切替可能。切替は ledger に記録。
- FR-403: エスカレーション条件(両モード共通) — 全仮説高R値、未知相フラグ、僅差競合(ΔlogZ < 閾値)、ガード3連続発動、吸収補正の経験推定モード発動。`agent` モードでもこれらは人間の Review Queue に通知される(処理のブロックはしない: 暫定裁定+要確認フラグ)。
- FR-404: エージェントのコスト追跡(tokens/dollars/wall-time、日次/月次予算照合)。

### FR-410 エージェントの職務

- FR-411: **Strategy Agent** — 戦略テンプレートの修正案生成・適用(auto)。根拠を ledger に記録。
- FR-412: **ChemPlausibility インターフェース (v0.2改定)** — 化学的妥当性評価は**プラグイン境界として定義するに留める**。
  ```python
  class ChemPlausibility(Protocol):
      def score(self, phase: PhaseRef, context: SynthesisContext) -> PlausibilityResult
      # PlausibilityResult: {score: float[0,1], rationale: str, source: str}
  ```
  - SynthesisContext: 元素系、前駆体、雰囲気、温度履歴、電気化学窓など。
  - v1同梱は最小ルールモジュールのみ(例: 大気下での単体アルカリ金属の降格)。
  - 外部計算予測モジュール(reaction network、熱力学計算、合成可能性予測、LLM判断)は本インターフェースに準拠して接続する想定。複数モジュールのスコア合成規則(重み付き幾何平均、既定)を定義。
  - **スコアは降格のみに使い、候補の除外は行わない**(Dara教訓)。
- FR-413: **Triage Agent** — 異常分類→自動リトライ or エスカレーション文書生成。
- FR-414: (削除: FR-404へ統合)

### FR-420 人間介入インターフェース

- FR-421: Review Queue(エスカレーション・要確認フラグ・`human`モードの裁定待ち)。モバイル要約カード。
- FR-422: 仮説diff表示(フィット・残差・相リスト・格子・evidence・basin構造)。
- FR-423: 人間の裁定・差し戻しの ledger 記録と、以後のランキングへの軽量反映。
- FR-424: あらゆる結果から ledger 根拠への遡及リンク。

### FR-430 OED / 測定フィードバック

- FR-431: 僅差競合時の判別測定提案(高統計再測定・追加温度点・joint用中性子測定・組成分析)を情報利得順で提案するJSONスキーマ。
- FR-432: PyBOED獲得関数への接続。v1は提案生成のみ。

---

## 9. 機能要件 — MEM解析 (v0.2新設)

### FR-600 MEMBackend

- FR-601: 精密化済み仮説から観測構造因子(F_obs、位相はモデル由来)を抽出し、MEM入力を自動生成する。X線→電子密度、中性子→核密度。
- FR-602: **MEMBackend 抽象インターフェース**。v1実装は Dysnomia 連携(外部バイナリのラッパ、入出力ファイル自動生成・実行・回収)。将来の内製ソルバ/他ソルバも同一インターフェースで交換可能。
- FR-603: MEM-Rietveld反復(MPF型) — MEM密度→F_calc更新→再精密化のサイクルをオプション提供(既定オフ、最大反復数・収束判定を設定)。各サイクルは仮説の子スナップショットとして保存。(v0.3.1 注記: 厳密な Sakata-Takata 型 MPF の「重なり反射強度の MEM 再配分」は GSAS-II scriptable が当該機能を露出しないため範囲外とし、各反復はモデル由来 F からの密度再構成で構成する。制約が解消された場合に再検討。)
- FR-604: 出力 — 密度マップ(VESTA互換 .grd 等)、指定サイト/結合経路に沿った1D/2D断面、ボンド経路の最小密度値(伝導経路解析を想定: Na/K伝導パスの可視化)。
- FR-605: 適用ガード — マルチヒストグラムjoint精密化済みかつ単相 or 主相支配的な場合を推奨条件とし、多相・低統計データへの適用時は信頼性警告を表示。
- FR-606: MEMはシーケンシャル解析の指定フレーム(例: 充電端・放電端・転移前後)に対するスポット解析として実行できる。

---

## 10. インターフェース仕様

### FR-500 入出力

- FR-501: 回折データ — xy/xye, xrdml, ras/rasx, GSAS raw(X線/中性子/TOF), NeXus/HDF5, 2D画像(pyFAI積分内蔵)。
- FR-502: 装置パラメータ — .instprm 第一級管理、標準試料からの生成ウィザード、NIST FPAインポート、TOFマルチバンク対応。
- FR-503: 電気化学 — Biologic .mpr、CSV汎用マッパ。
- FR-504: 出力 — 仮説付きレポート(HTML/PDF)、トラジェクトリ(CSV; parquet はオプション)、CIF、MEM密度マップ。
- FR-505: **.gpx 引き渡し保証** — 任意時点の状態をGSAS-II GUIで開ける .gpx として書き出し。
- FR-506: CellConfig のYAML定義とライブラリ化(自作セル・市販セルのプリセット共有)。

### FR-510 API

- FR-511: Python API (`tsumugin.Project`)。
- FR-512: REST API。
- FR-513: MCP Server(`submit_analysis`, `list_hypotheses`, `compare_hypotheses`, `accept_hypothesis`, `revert`, `get_trajectory`, `export_gpx`, `run_mem`)。final_selection_mode はMCP経由でも同一に適用。

---

## 11. 非機能要件

- NFR-101: 破壊的操作のAPI非実装(P2の実装保証)。全出力追記型。
- NFR-102: 再現性 — 乱数種固定でビット同一。`nested` はサンプラー種固定+logZ誤差併記。環境lockfile+コンテナ。
- NFR-103: 性能 — 単一パターン(候補300相)中央値 ≤ 3分(32コア、bic評価時)。シーケンシャル非探索区間 ≤ 10秒/フレーム。`nested` 裁定は1仮説 ≤ 30分を目標とし超過時は打ち切り+Laplace代替と警告。(v0.3.1 明確化: 時間上限の監視は協調的方式 — 実行単位の完了後に経過時間を評価して打ち切る — を許容する。単一実行の途中強制中断は要求しない。)
- NFR-104: Ray並列、PBS Proバッチテンプレート同梱。
- NFR-105: ledger 追記専用+ハッシュチェーン。
- NFR-106: GSAS-IIバージョン固定+contract test。Dysnomia も同様にバージョン固定。
- NFR-107: σの由来(共分散/逐次相関/マルチスタート分散)をレポートに明示。

---

## 12. ベンチマーク計画

1. Rietveld解析ベンチ (GSAS-IIの全関連チュートリアルを自動解析、チュートリアルと比較)。
2. Dara互換ベンチ(前駆体混合+固相反応生成物、Dara/Jade/人間比較)。
3. Operandoベンチ — グラファイトステージング、LFP二相、P2型固溶体域+OP4転移。FR-313/316の判別・分割正答性、FR-317吸収補正の有無による相分率バイアス評価。
4. 高温ベンチ — 既知反応系での転移温度・相系譜再現。
5. 較正ベンチ — reliability diagram / ECE。`bic` と `nested` の確率較正を別々に評価。
6. jointベンチ — X線+中性子併用時の占有率精度向上の定量(Ni/Fe/Mn系を想定)。

## 13. マイルストーン

| 版 | 内容 |
|---|---|
| M0 (PoC) | GSASIIscriptableラッパ+段階戦略+ガードレール。単一パターン自動多相精密化 |
| M1 | 多仮説木探索+Evidence Engine(bic/aic)+.gpx書き出し+Web UI最小版 |
| M2 | シーケンシャル基盤+高温モード+ledger/snapshot+最終選択2モード |
| M3 | Operandoモード(電気化学同期・吸収補正・FR-313/316判別)+マルチスタート |
| M4 | 中性子/マルチヒストグラムjoint+ChemPlausibilityインターフェース+MCP server |
| M5 | nested sampling裁定+MEM(Dysnomia連携)+OED提案+較正済み確率+ベンチ公開 |

## 14. 主要リスクと緩和

| リスク | 緩和 |
|---|---|
| GSAS-II最小二乗の発散 | ガードレール+保守的探索モード+マルチスタート(FR-230) |
| GSASIIscriptable API変更 | バージョン固定+contract test+Backend抽象化 |
| 候補DBに正解相が無い誤誘導 | 未知相フラグ強制表示、ChemPlausibilityは降格のみ |
| 逐次解析の誤り伝播 | IC-changepoint再探索+定期cold restart |
| `nested` の計算コスト暴走 | 階層的裁定(FR-122)+時間上限+Laplace代替 |
| 吸収補正パラメータと相分率・変位の相関 | 透過法限定+CellConfig由来の事前restraint、相関行列の自動警告 |
| Dysnomia外部依存(配布・ライセンス) | MEMBackend抽象化、未導入環境ではMEM機能を明示的に無効化 |
| エージェント裁定への過信 | `agent`モードでも僅差競合は要確認フラグ+全裁定revert可能 |

## 15. 課題の確定状況 (v0.3)

| # | 課題 | 確定 |
|---|---|---|
| 1 | FR-316 分割仮説の探索順序 | **推奨案で確定**: k を逐次追加し、evidence改善が閾値未満で打ち切り。ペナルティ項の較正値は実装時にベンチ(§12-2)で確定 |
| 2 | FR-317 吸収モデルの粒度 | **確定**: 層状セルは透過法のみ。v1は実効μt 1パラメータ+CellConfig由来restraint |
| 3 | MEM-Rietveld反復の自動運転 | **推奨案で確定**: 既定オフを維持。条件付きautoは運用実績を見て将来判断 |
| 4 | joint精密化のヒストグラム重み | **推奨案で確定**: 統計重みを既定。経験重みはオプションとして実装時に仕様化 |
| 5 | `nested` の事前分布自動構成 | **実装時確定**: M5で失敗モード検証の上で確定 |
