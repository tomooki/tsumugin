# m4-joint-mcp 要件定義書

## 概要

Tsumugin マイルストーン M4: **中性子・マルチヒストグラム joint 精密化**、**ChemPlausibility プラグイン境界**、
**MCP Server** を実装する。中性子 CW/TOF ヒストグラム取り込み(FR-241)、構造共有・ヒスト独立の joint 精密化
(FR-242)、ヒストグラム重み(FR-243)、X線/中性子コントラストによる占有率解放推奨(FR-244)、探索プライマリ・
検証 joint の分業(FR-245)、化学的妥当性の Protocol 境界と v1 最小ルール(FR-412)、8 ツールの MCP Server
(FR-513)を提供する。`run_mem` は MEM(M5)への薄い委譲/スタブ境界に留める。

上位仕様: [docs/tsumugin_spec_v0.3.md](../../tsumugin_spec_v0.3.md) §6 FR-240系 / §8 FR-412 / §10 FR-513 / §11 NFR / §13 M4。
M0〜M3 資産(HypothesisTreeSearch / RefinementBackend / evidence.rank / FinalSelectionEngine / Trajectory /
export_gpx / analyze_single_pattern / persistent store)の上に構築する。

## 関連文書

- [💬 interview-record.md](interview-record.md) / [📖 user-stories.md](user-stories.md) /
  [✅ acceptance-criteria.md](acceptance-criteria.md) / [📝 note.md](note.md) / [🔧 prep.md](prep.md)

## 機能要件（EARS記法）

**【信頼性レベル凡例】**: 🔵 仕様書・既存実装に依拠 / 🟡 妥当な推測で確定 (根拠記載) / 🔴 根拠なし推測

### 通常要件 — 中性子・マルチヒストグラム取り込み (FR-241)

- REQ-001: システムは **中性子 CW / TOF ヒストグラム**を `HistogramRef(probe="neutron_cw"|"neutron_tof")`
  として取り込めなければならない。`probe`(3 種)・`instprm_ref`・`bank_id` の器は既存を利用する 🔵 *FR-241/§4 HistogramRef*
- REQ-002: システムは **TOF マルチバンク**について、バンクごとの **DIFC / DIFA / ZERO** パラメータを保持
  する値オブジェクト (`TofBankParams` 相当) を持たなければならない。`HistogramRef` へ**末尾・既定値付きで
  非破壊追加**する 🔵 *FR-241/REQ-404*
- REQ-003: システムは 1 フレームに **X線 + 中性子 (+複数バンク) の複数ヒストグラム**を保持できなければ
  ならない。`Frame.histograms: tuple[HistogramRef,...]` の器を利用する 🔵 *FR-241/242/§4 Frame*

### 通常要件 — joint 精密化 (FR-242)

- REQ-004: システムは **joint 精密化入力** (`JointRefinementModel` 相当) を持たなければならない。
  構造パラメータ (格子・座標・占有率・ADP) は**全ヒストで共有**、scale・背景・プロファイルは
  **ヒストごとに独立**とする 🔵 *FR-242*
- REQ-005: システムは同一構造モデルに対し **X線 + 中性子 / 複数バンク / 複数温度点**のヒストグラム群を
  **同時フィット**できなければならない。**GSASIIBackend では GSAS-II ネイティブのマルチヒストグラム機能**を
  利用し、SimulatedBackend では**ヒストごと χ² の合算**で検証可能とする 🔵 *FR-242 (Simulated 検証は 🟡)*
- REQ-006: joint 精密化の結果は、各ヒストの独立指標 (ヒスト別 Rwp/scale) と共有構造パラメータ (±σ) を
  **単一の RefinementResult に集約**しなければならない。ヒスト別値は `RefinementResult.globals`/`warnings`
  (M3 導入済) 相当か joint 専用集約フィールドで保持する 🟡 *FR-242 から導出*
- REQ-007: 1 ヒストグラムの精密化が失敗しても joint 全体を例外で止めず、**chi2=inf 相当へ変換**して
  ガードレール/降格で処理しなければならない 🔵 *CLAUDE.md 不変条件*

### 通常要件 — ヒストグラム重み (FR-243)

- REQ-008: システムは **ヒストグラムごとの重み**を設定できなければならない。**既定は統計重み**
  (1/σ² 由来)、経験重み (信頼度スカラ) は**オプション**とする 🔵 *FR-243*
- REQ-009: システムは σ の由来 (共分散 / ヒスト重み由来) を**レポートに明示**しなければならない 🔵 *NFR-107*

### 通常要件 — コントラストによる占有率解放推奨 (FR-244)

- REQ-010: システムは **X線散乱因子 (f, Z 近似) と中性子散乱長 (b) の正規化差 |f_norm − b_norm|**が
  閾値以上のサイトを**散乱コントラスト十分なサイトとして自動検出**しなければならない。中性子散乱長は
  **元素代表値の軽量静的テーブル**を同梱する 🔵 *FR-244 (b テーブル同梱は 🟡)*
- REQ-011: システムは **joint データがある場合に限り**、コントラスト十分なサイトの占有率解放を
  **戦略への追加提案**としなければならない。**推奨のみで自動適用・自動採択は行わない** 🔵 *FR-244*
- REQ-012: コントラスト判定の提案は**理由付きで ledger に記録**されなければならない (どのサイトを
  なぜ推奨したか) 🔵 *FR-244/NFR-105*

### 通常要件 — 探索プライマリ・検証 joint の分業 (FR-245)

- REQ-013: システムは **木探索 (FR-110) をプライマリヒストグラム 1 本で実行**しなければならない
  (`HypothesisTreeSearch` を再利用) 🔵 *FR-245*
- REQ-014: システムは **生存仮説の検証精密化のみを joint で実行**しなければならない (探索コスト抑制)。
  探索段を joint 化してはならない 🔵 *FR-245*

### 通常要件 — ChemPlausibility インターフェース (FR-412)

- REQ-015: システムは **`ChemPlausibility` Protocol 境界**を持たなければならない:
  `score(phase: PhaseRef, context: SynthesisContext) -> PlausibilityResult`。
  `PlausibilityResult = {score: float[0,1], rationale: str, source: str}` の frozen dataclass とする 🔵 *FR-412*
- REQ-016: システムは **`SynthesisContext`** (元素系 / 前駆体 / 雰囲気 / 温度履歴 / 電気化学窓) の
  frozen dataclass を持たなければならない 🔵 *FR-412*
- REQ-017: v1 同梱は **最小ルールモジュール 1 つ以上** (例: 大気下での単体アルカリ金属を降格) でなければ
  ならない 🔵 *FR-412*
- REQ-018: 複数モジュールのスコア合成は **重み付き幾何平均 (既定)** で行わなければならない 🔵 *FR-412*
- REQ-019 (最重要不変条件): **ChemPlausibility スコアは降格のみに使い、候補の除外・rejected 化は行っては
  ならない** (Dara 教訓)。低スコア相も rank から消えてはならない 🔵 *FR-412/P1 Dara 教訓*
- REQ-020: システムは **`PhaseRef`** (相 ID + 組成/元素系ヒント) を持ち、ChemPlausibility.score へ
  渡せなければならない。既存 `PhaseInstance.phase_ref: str` と整合させる 🟡 *FR-412 から導出*

### 通常要件 — MCP Server (FR-513)

- REQ-021: システムは **MCP Server の 8 ツール**を提供しなければならない: `submit_analysis`,
  `list_hypotheses`, `compare_hypotheses`, `accept_hypothesis`, `revert`, `get_trajectory`,
  `export_gpx`, `run_mem` 🔵 *FR-513*
- REQ-022: 各 MCP ツールは **SDK 非依存のツール実処理関数**と **MCP SDK 依存の薄いアダプタ**の 2 層に
  分離しなければならない。実処理関数は M0〜M3 資産へ委譲する
  (`submit_analysis`→pipeline、`accept_hypothesis`/`revert`→FinalSelectionEngine、
  `get_trajectory`→Trajectory、`export_gpx`→export.gpx、`list/compare`→SearchResult/rank) 🔵 *FR-513/設計裁量*
- REQ-023: **`final_selection_mode` (agent/human, FR-402) は MCP 経由でも同一適用**されなければならない。
  `human` モードでは `accept_hypothesis` がエージェント権限で accepted 化してはならない 🔵 *FR-402/FR-513*
- REQ-024: MCP `revert` は **追記型スナップショット revert (superseded 化)** でなければならず、破壊的削除で
  あってはならない。**MCP ツールに破壊的操作を実装してはならない** 🔵 *FR-513/P2/NFR-101*
- REQ-025: MCP 経由の全状態変更操作 (submit / accept / revert / mode 切替) は**理由付きで ledger に記録**
  されなければならない 🔵 *NFR-105/FR-424*

### 条件付き要件

- REQ-101: **`run_mem` が呼ばれた場合**、システムは MEM バックエンド未実装を示す**明示エラー
  (`NotImplementedError` 相当) または「M5 で提供予定」プレースホルダ応答**を返さなければならない
  (破壊的操作を伴わない) 🔵 *FR-513/FR-600系 M5 委譲*
- REQ-102: **MCP SDK (`mcp` パッケージ) が未導入の場合**、システムは MCP サーバ起動 API のみを
  **friendly error (`MCPUnavailableError` 相当)** に縮退させ、ツール実処理関数自体は SDK 非依存で
  動作させなければならない 🔵 *設計裁量/optional extra 方式*
- REQ-103: **コントラストが全サイトで閾値未満の場合**、占有率解放推奨は空 (提案なし) とし、
  警告なく通常精密化を続行しなければならない 🟡 *FR-244 から導出*
- REQ-104: **joint データがない (単一ヒスト) 場合**、コントラスト占有率解放推奨は発動してはならない
  (joint データがある場合のみ) 🔵 *FR-244*
- REQ-105: **ChemPlausibility モジュールが未登録の場合**、rank は降格なしの素の evidence 順位を返さな
  ければならない (ChemPlausibility は任意プラグイン) 🟡 *FR-412 から導出*
- REQ-106: **`accept_hypothesis` が human モードで agent により呼ばれた場合**、システムは accepted 化を
  拒否し推奨提示に留めなければならない 🔵 *FR-402/REQ-023*

### 状態要件

- REQ-201: **final_selection_mode が human にある間**、MCP `accept_hypothesis` は人間操作に相当する
  `by="human"` 経由でのみ accepted 化を行わなければならない 🔵 *FR-402*
- REQ-202: **joint 検証精密化の実行中にある間**、探索段のプライマリヒストグラム結果は不変で
  なければならない (joint は探索を書き換えない) 🔵 *FR-245*

### オプション要件

- REQ-301: システムは経験重み (信頼度スカラ) によるヒストグラム重み上書きを**提供してもよい** 🔵 *FR-243*
- REQ-302: システムは中性子ヒストグラムに対する吸収/多重散乱補正を **FR-317 と同一インターフェースで
  切替可能にしてもよい** (M4 では最小・境界のみ) 🔵 *FR-317 末項*
- REQ-303: MCP Server は stdio トランスポートに加え、ローカルバインド (`127.0.0.1`) の別トランスポートを
  提供してもよい (既定はローカル・無認証ネットワーク公開はしない) 🟡 *P2/セキュリティ*

### 制約要件

- REQ-401: 全新機能は **P2 非破壊 (追記 + ledger 記録)** と **NFR-105 (追記専用 + ハッシュチェーン)** を
  維持しなければならない。joint 昇格・コントラスト提案・ChemPlausibility 降格・MCP 操作も削除/上書き
  API を持ってはならない 🔵 *P2/NFR-101/NFR-105*
- REQ-402: joint 精密化・コントラスト判定・スコア合成・MCP 応答を含む全出力は同一入力で**ビット同一**で
  なければならない (ヒスト順・元素順・スコア合成順を決定論化) 🔵 *NFR-102*
- REQ-403: **コア依存は numpy のみを維持する**。MCP SDK (`mcp`) は optional extra + friendly error、
  中性子散乱長は軽量静的テーブル (重依存不可) とする 🔵 *CLAUDE.md*
- REQ-404: データモデル拡張 (`TofBankParams` / `JointRefinementModel` / `PhaseRef` / `SynthesisContext` /
  `PlausibilityResult`) は既存 API 後方互換の**非破壊追加**でなければならない。公開 `__all__` は
  末尾追加 + 昇順維持 🔵 *REQ-404 踏襲*
- REQ-405: **MCP Server はネットワークへ無認証公開してはならない**。既定はローカル (stdio / 127.0.0.1)
  バインドとする 🔵 *P2/セキュリティ制約*

## 非機能要件

- NFR-001: joint 精密化テスト (2 ヒスト合成データ) が CI 実用時間内 (単一 joint < 30 秒) 🟡
- NFR-002: FR-245 により joint は生存仮説のみに限定適用し、探索コストを増やさない 🔵 *FR-245*
- NFR-003: MCP ツール実処理関数は SDK 非依存で通常 pytest により網羅される (SDK 依存は `@pytest.mark.mcp` 等で分離) 🟡
- NFR-201: 決定論・追記専用・ハッシュチェーン (M0〜M3 と同一) 🔵 *NFR-102/105*

## Edgeケース

- EDGE-001: joint で 1 ヒストの精密化のみ失敗 → 当該ヒストを chi2=inf 扱いにし joint 全体はクラッシュしない 🔵 *REQ-007*
- EDGE-002: TOF バンクが 1 本のみ (単バンク) → DIFC 系は 1 セット、マルチバンク経路と同一結果 🟡
- EDGE-003: 全サイトでコントラスト閾値未満 → 占有率解放推奨は空、通常続行 🟡 *REQ-103*
- EDGE-004: 単一ヒスト (joint データなし) でコントラスト判定呼び出し → 推奨発動せず (joint 条件不成立) 🔵 *REQ-104*
- EDGE-005: ChemPlausibility が全相に低スコアを付与 → 全相の順位が下がるが**どの相も rank から消えない** 🔵 *REQ-019*
- EDGE-006: ChemPlausibility モジュール未登録 → 素の evidence 順位 (降格なし) 🟡 *REQ-105*
- EDGE-007: 複数 ChemPlausibility モジュールの 1 つが score=0 を返す → 重み付き幾何平均で合成 (0 の伝播は仕様どおり降格) 🟡 *REQ-018*
- EDGE-008: MCP `run_mem` 呼び出し → 明示エラー / プレースホルダ (破壊的操作なし) 🔵 *REQ-101*
- EDGE-009: MCP SDK 未導入で MCP サーバ起動 → friendly error、ツール実処理関数は動作 🔵 *REQ-102*
- EDGE-010: MCP `accept_hypothesis` が human モードで agent 実行 → accepted 化拒否・推奨提示 🔵 *REQ-106/REQ-201*
- EDGE-011: MCP `export_gpx` を GSAS-II 未導入環境で実行 → `GSASUnavailableError` を MCP エラーへ変換 (クラッシュしない) 🟡 *export_gpx 既存契約*

## M4 スコープ外 (明示)

- nested sampling 裁定 (FR-122, M5)、MEM 本体 (Dysnomia, FR-601〜606, M5 — `run_mem` は境界のみ)、
  OED 提案本体 (FR-430系, M5)、較正済み確率 / reliability diagram / ECE (M5)、
  xraylib 実装 / 中性子散乱長の同位体別精密テーブル (v1 は元素代表値の静的テーブル)、
  中性子吸収/多重散乱補正の本実装 (v1 は FR-317 と同一 IF の境界のみ)、
  MCP Server のネットワーク公開時認証 (既定ローカルバインドで回避)、
  Ray/multiprocessing 並列 (FR-234 実行系は M-later)。
