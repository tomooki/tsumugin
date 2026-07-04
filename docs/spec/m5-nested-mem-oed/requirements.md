# m5-nested-mem-oed 要件定義書

## 概要

Tsumugin マイルストーン M5: **nested sampling 裁定**、**MEM(Dysnomia 連携)電子/核密度解析**、
**OED / 測定フィードバック提案**、**較正済み確率**を実装する。既存 `EvidenceBackend` Protocol に
準拠する `laplace`(FR-121)/ `nested`(FR-121/122)バックエンドを新設し、木探索は `bic` のまま
維持しつつ僅差競合のみ `nested` で再裁定する 2 段構え(FR-122)を提供する。`MEMBackend` 抽象境界と
Dysnomia 連携 v1 実装(FR-600〜606)、僅差競合時の判別測定提案 JSON スキーマ(FR-431/432)、
reliability diagram / ECE による確率較正評価(§12-5)を提供する。M4 の `run_mem` MCP 委譲境界
(`MEMUnavailableError` プレースホルダ)を MEMBackend へ実体化する。

nested(dynesty / UltraNest)/ MEM(Dysnomia)/ OED(PyBOED)の外部依存はすべて **optional
extra** とし、未導入時は明示エラー(`NestedUnavailableError` / `MEMUnavailableError` /
`OEDUnavailableError`)へ縮退する。**コア import(`import tsumugin`)は numpy のみで成功**する。

上位仕様: [docs/tsumugin_spec_v0.3.md](../../tsumugin_spec_v0.3.md)
§5 FR-121/122/123/124/125(Evidence Engine / nested / 階層的裁定 / 確率較正 / 事前分布)/
§8 FR-430/431/432(OED)/ §9 FR-600〜606(MEMBackend)/ §11 NFR-102/103/105/107 /
§12-5 較正ベンチ / §13 M5。
M0〜M4 資産(`EvidenceBackend` / `BICBackend` / `rank` / `HypothesisTreeSearch` /
`JointVerificationResult` / `FinalSelectionEngine` / `mcp.tools` / `mcp.mem` /
`store`(ledger/snapshot))の上に構築する。

## 関連文書

- [💬 interview-record.md](interview-record.md) / [📖 user-stories.md](user-stories.md) /
  [✅ acceptance-criteria.md](acceptance-criteria.md) / [📝 note.md](note.md) / [🔧 prep.md](prep.md)

## 機能要件（EARS記法）

**【信頼性レベル凡例】**: 🔵 仕様書・既存実装に依拠 / 🟡 妥当な推測で確定 (根拠記載) / 🔴 根拠なし推測

---

### 通常要件 — Laplace evidence バックエンド (FR-121)

- REQ-001: システムは **`laplace` EvidenceBackend** を実装しなければならない。既存 `EvidenceBackend`
  Protocol (`name: str` + `score(metrics: RefinementMetrics) -> EvidenceResult`) に準拠する 🔵 *FR-121/evidence/base.py*
- REQ-002: `laplace` は **Hessian 由来の Laplace 近似 evidence** を返さなければならない。ヘッセ行列/
  共分散が利用不能な縮退時は BIC 近似へフォールバックし、警告を `EvidenceResult`/レポートに残す 🟡 *FR-121 (フォールバックは導出)*
- REQ-003: `laplace` の `EvidenceResult.value` は **既存 IC 系と同一符号規約(小さいほど良い)** で返さなければ
  ならない。バックエンド間で evidence のセマンティクスを統一する(BIC 比較の一貫性)🔵 *CLAUDE.md 不変条件/evidence/base.py*

### 通常要件 — nested sampling バックエンド (FR-121/125)

- REQ-004: システムは **`nested` EvidenceBackend** を実装しなければならない。dynesty / UltraNest への
  連携だが**外部依存は optional extra `nested`** とし、コア import は numpy のみを維持する 🔵 *FR-121/CLAUDE.md/NFR-102*
- REQ-005: **外部サンプラ(dynesty / UltraNest)が未導入の場合**、`nested` バックエンドの実行 API は
  **明示エラー `NestedUnavailableError`** へ縮退しなければならない(`MCPUnavailableError` 系と対称)🔵 *FR-121/CLAUDE.md optional extra 方式*
- REQ-006: `nested` は **logZ とその誤差(logz_err)** を返さなければならない。`EvidenceResult.logz_err`
  (既存フィールド・M0 では None) に誤差を格納する 🔵 *FR-121/FR-124/evidence/base.py*
- REQ-007: `nested` は evidence 比較で他バックエンド (bic/laplace) と同一符号規約に整合する `value`
  (小さいほど良い、例 `-logZ`) を `EvidenceResult.value` に返さなければならない。logZ 生値は付随情報として
  保持する 🟡 *FR-121/rank の value 昇順規約から導出*
- REQ-008: `nested` の **事前分布は精密化 restraint(格子シフト上限・占有率拘束等)から自動構成**
  されなければならず、手動上書き(事前分布指定オブジェクト)を受理しなければならない 🔵 *FR-125*
- REQ-009: システムは **サンプラー種(乱数種)を固定**し、同一入力・同一種で再現可能な logZ を返さなければ
  ならない。logZ は誤差併記で報告する(ビット同一はサンプラの確率的性質上 logZ±誤差の範囲で保証)🔵 *NFR-102/FR-121*

### 通常要件 — 階層的裁定 (FR-122)

- REQ-010: システムは **木探索・枝刈りを `bic` のまま**実行しなければならない(既存 `HypothesisTreeSearch`
  を再利用)。探索段を nested 化してはならない(計算コスト抑制)🔵 *FR-122/search/tree.py*
- REQ-011: システムは **生き残った上位仮説間で evidence 差が閾値未満(既定 ΔBIC < 10)の競合のみ**
  `nested` で再裁定しなければならない。既存 `rank` の `close_competitor`(close_threshold=10.0)を
  再裁定対象の判定に用いる 🔵 *FR-122/evidence/ranking.py*
- REQ-012: システムは **フル nested 運転(全生存仮説を nested で裁定)を設定で可能**にしなければならない。
  既定は 2 段構え(bic 一次 + 競合のみ nested)とする 🔵 *FR-122*
- REQ-013: 階層的裁定の結果(どの仮説を bic 一次で確定し、どの競合を nested で再裁定したか)は
  **理由付きで ledger に記録**されなければならない 🔵 *FR-122/NFR-105/FR-424*

### 通常要件 — 確率較正 (FR-124)

- REQ-014: システムは **仮説確率を softmax + 温度較正**で出力しなければならない(既存 `rank` の
  `temperature` を再利用)。温度較正パラメータは較正ベンチ(§12-5)由来の値を設定可能とする 🔵 *FR-124/evidence/ranking.py*
- REQ-015: システムは **backend 間で確率の意味が異なること(BIC 近似 vs logZ)をレポートに明記**
  しなければならない。確率出力に用いた evidence backend 名を応答/レポートに含める 🔵 *FR-124*
- REQ-016: システムは **reliability diagram / ECE(Expected Calibration Error)** を計算する較正評価
  ユーティリティを提供しなければならない。**`bic` と `nested` の較正を別々に評価**できなければならない 🔵 *FR-124/§12-5*
- REQ-017: 較正評価は **正解ラベル付きベンチデータ(予測確率, 真偽)群**を入力とし、ビン分割済み
  reliability 曲線と ECE スカラを決定論的に返さなければならない 🟡 *§12-5 から導出*

### 通常要件 — MEMBackend 抽象境界 (FR-602)

- REQ-018: システムは **`MEMBackend` 抽象インターフェース(`typing.Protocol`)** を定義しなければ
  ならない。`RefinementBackend` / `EvidenceBackend` / `ChemPlausibility` と同型の交換可能境界とする 🔵 *FR-602/P7*
- REQ-019: `MEMBackend` の v1 実装は **Dysnomia 連携(外部バイナリのラッパ: 入出力ファイル自動生成・
  実行・回収)** でなければならない。**外部依存は optional extra `mem`** とする 🔵 *FR-602/CLAUDE.md optional extra*
- REQ-020: **Dysnomia バイナリ未導入の場合**、MEM 実行 API は **明示エラー `MEMUnavailableError`**
  (M4 で errors.py に定義済) へ縮退しなければならない。将来の内製ソルバ/他ソルバも同一インターフェースで
  交換可能とする 🔵 *FR-602/errors.py/リスク表*

### 通常要件 — MEM 入力生成 (FR-601)

- REQ-021: システムは **精密化済み仮説から観測構造因子 F_obs(位相はモデル由来)を抽出**し、MEM 入力
  ファイルを自動生成しなければならない 🔵 *FR-601*
- REQ-022: システムは **プローブに応じた密度種別**を選択しなければならない: **X線 → 電子密度、
  中性子 → 核密度**。joint 精密化結果(`JointVerificationResult`)を入力元とする 🔵 *FR-601/FR-605/joint/*
- REQ-023: MEM 入力生成は **決定論的(反射順・F_obs 順を固定)** でなければならず、同一仮説から
  ビット同一の入力ファイルを生成しなければならない 🔵 *NFR-102*

### 通常要件 — MEM-Rietveld 反復 (FR-603)

- REQ-024: システムは **MEM-Rietveld 反復(MPF 型: MEM 密度 → F_calc 更新 → 再精密化サイクル)** を
  提供しなければならない。**既定オフ**とし、最大反復数・収束判定を設定可能とする 🔵 *FR-603/§15-3*
- REQ-025: MEM-Rietveld 反復の **各サイクルは仮説の子スナップショットとして保存**されなければならない。
  既存 `SnapshotStore`(追記型)へ子スナップショットを追記し、**削除・上書きを行ってはならない** 🔵 *FR-603/P2/NFR-101*
- REQ-026: MEM-Rietveld 反復は **収束判定(密度変化/R 値変化が閾値未満)または最大反復到達で停止**
  しなければならない。停止理由を ledger に記録する 🔵 *FR-603/NFR-105*

### 通常要件 — MEM 出力 (FR-604)

- REQ-027: システムは **密度マップ(VESTA 互換 .grd 等)** を出力しなければならない 🔵 *FR-604/FR-504*
- REQ-028: システムは **指定サイト/結合経路に沿った 1D / 2D 断面**を出力しなければならない 🔵 *FR-604*
- REQ-029: システムは **ボンド経路の最小密度値(伝導経路解析: Na/K 伝導パス可視化を想定)** を
  抽出・出力しなければならない 🔵 *FR-604*

### 通常要件 — MEM 適用ガード (FR-605)

- REQ-030: システムは **推奨条件(joint 精密化済みかつ単相 or 主相支配的)** を判定し、条件を満たさない
  データ(多相・低統計)への適用時は **信頼性警告を表示**しなければならない 🔵 *FR-605*
- REQ-031 (最重要不変条件): MEM 適用ガードは **警告のみで、候補・仮説の除外は行ってはならない**
  (Dara 教訓と同じ思想)。ガード発動時も MEM 実行自体は継続可能とする 🔵 *FR-605/P1 Dara 教訓/FR-412 と同型*

### 通常要件 — MEM フレームスポット解析 (FR-606)

- REQ-032: システムは **MEM をシーケンシャル解析の指定フレーム(例: 充電端・放電端・転移前後)に対する
  スポット解析として実行**できなければならない。フレーム指定は `Frame.index` 等で行う 🔵 *FR-606/sequential/*

### 通常要件 — MCP run_mem 実体化 (FR-513 / M4 境界の接続)

- REQ-033: システムは **M4 の `run_mem` MCP 委譲境界(`mcp/mem.py::run_mem_boundary`)を MEMBackend へ
  委譲するよう接続**しなければならない。M4 の placeholder 契約(`placeholder=True` の dict スキーマ)と
  整合させ、後方互換を壊してはならない 🔵 *REQ-033/FR-513/mcp/mem.py*
- REQ-034: `run_mem` MCP ツールは **MEM 実行結果(密度マップパス・断面・最小密度・警告)を素の型 dict**
  で返さなければならず、**破壊的操作を伴ってはならない**(子スナップショット追記のみ)🔵 *FR-513/P2/NFR-101/mcp/tools.py*

### 通常要件 — OED / 測定フィードバック (FR-431/432)

- REQ-035: システムは **僅差競合時の判別測定提案**(高統計再測定・追加温度点・joint 用中性子測定・
  組成分析)を **情報利得順で提案する JSON スキーマ**を生成しなければならない 🔵 *FR-431*
- REQ-036: OED 提案は **PyBOED 獲得関数への接続**を境界として持たなければならないが、**v1 は提案生成のみ**
  とする。**外部依存 optional extra `oed`**、未導入時は `OEDUnavailableError` へ縮退する 🔵 *FR-432/CLAUDE.md optional extra*
- REQ-037: OED 提案は **非破壊(ledger 追記記録のみ、状態変更なし)** でなければならない。提案生成は
  仮説の accepted/rejected 化・データ改変を一切伴ってはならない 🔵 *FR-432/P2/NFR-101*
- REQ-038: OED 提案の発動条件は **僅差競合(既存 `rank` の `close_competitor` / ΔlogZ < 閾値)** で
  なければならない。僅差競合が無い場合は提案を空とする 🔵 *FR-431/FR-403/evidence/ranking.py*

### 条件付き要件

- REQ-101: **`nested` 裁定が時間上限(既定 1 仮説 30 分, NFR-103)を超過した場合**、システムは
  **打ち切り + Laplace evidence 代替へフォールバック + 警告**を行わなければならない(打ち切りは例外でなく
  縮退)🔵 *NFR-103/FR-121*
- REQ-102: **僅差競合が生存仮説間に存在しない場合**、システムは nested 再裁定を発動せず bic 一次判定を
  最終結果としなければならない(2 段構えの下段をスキップ)🔵 *FR-122/REQ-011*
- REQ-103: **MEM 適用ガードの推奨条件を満たさない場合(多相 or 低統計)**、システムは信頼性警告を付した
  上で MEM 実行を継続しなければならない(除外・中止はしない)🔵 *FR-605/REQ-031*
- REQ-104: **`run_mem` が MEMBackend 未導入(Dysnomia 未導入)で呼ばれた場合**、システムは
  `MEMUnavailableError` を MCP エラー dict へ変換し、クラッシュ・破壊的操作を伴わずに応答しなければ
  ならない 🔵 *REQ-020/FR-513/mcp/mem.py*
- REQ-105: **OED 外部依存(PyBOED)未導入で獲得関数接続 API が呼ばれた場合**、システムは
  `OEDUnavailableError` へ縮退しなければならない。提案生成(v1 スコープ)は外部依存なしで動作させる 🔵 *REQ-036/CLAUDE.md*
- REQ-106: **較正ベンチに `nested` の logZ が含まれる場合**、システムは `bic` と `nested` の
  reliability diagram / ECE を別系列として分離出力しなければならない 🔵 *FR-124/§12-5/REQ-016*
- REQ-107: **MEM-Rietveld 反復が発散(密度負値/R 値悪化)した場合**、システムは当該サイクルを
  子スナップショットとして残しつつ反復を停止し、理由を ledger 記録しなければならない(ロールバックは
  revert 経由・破壊しない)🟡 *FR-603/FR-210 ガードレール思想から導出*

### 状態要件

- REQ-201: **`nested` バックエンドが選択されている間**、木探索段の評価は `bic` で行われ、探索結果は
  nested により書き換えられてはならない(探索は bic 固定・裁定のみ nested)🔵 *FR-122/REQ-010*
- REQ-202: **MEM-Rietveld 反復が実行中にある間**、元の joint 精密化済み仮説(親スナップショット)は
  不変でなければならない。各サイクルは子スナップショットとして追記される 🔵 *FR-603/P2/REQ-025*
- REQ-203: **final_selection_mode が human にある間**、nested 再裁定・OED 提案・MEM 結果は
  **推奨/情報提示に留まり**、仮説の accepted 化は人間操作でのみ行われなければならない 🔵 *FR-402/FR-403/M4 REQ-023 踏襲*

### オプション要件

- REQ-301: システムは **`nested` の事前分布を手動オブジェクトで完全上書き**する API を提供してもよい
  (restraint 自動構成の既定を明示指定で置換)🔵 *FR-125*
- REQ-302: システムは **MEM-Rietveld 反復の条件付き auto 運転**(推奨条件充足時のみ自動反復)を将来
  提供してもよいが、**v1 は既定オフを維持**する 🔵 *FR-603/§15-3*
- REQ-303: システムは **UltraNest / dynesty のどちらを nested 実装に用いるか設定で選択可能**にしてもよい
  (いずれも optional extra `nested`)🟡 *FR-121/interview Q で確定*
- REQ-304: OED 提案は **提案ごとの推定情報利得スカラ**を JSON に含めてもよい(v1 は簡易近似で足る)🟡 *FR-431 から導出*

### 制約要件

- REQ-401: 全新機能は **P2 非破壊(追記 + ledger 記録)** と **NFR-105(追記専用 + ハッシュチェーン)** を
  維持しなければならない。nested 裁定・MEM 反復(子スナップショット)・OED 提案・較正評価も削除/上書き API を
  持ってはならない。`ledger.verify()` は常に True 🔵 *P2/NFR-101/NFR-105*
- REQ-402: システムは **サンプラー種を固定**し、nested の logZ を **誤差併記で再現可能**にしなければ
  ならない。MEM 入力生成・OED 提案・較正評価は同一入力で **ビット同一**でなければならない(反射順・
  提案順・ビン順を決定論化)🔵 *NFR-102*
- REQ-403: **コア依存は numpy のみを維持する**。`nested`(dynesty/ultranest)/ `mem`(dysnomia)/
  `oed`(pyboed)は**すべて optional extra + friendly error**とする。`import tsumugin` は追加依存なしで
  成功しなければならない 🔵 *CLAUDE.md/REQ-403 踏襲*
- REQ-404: データモデル・公開 API 拡張(`NestedBackend` / `LaplaceBackend` / `MEMBackend` /
  `MEMResult` / `OEDProposal` / `CalibrationReport` 等)は既存 API 後方互換の**非破壊追加**でなければ
  ならない。公開 `__all__` は**末尾追加 + 昇順維持**(既存 test で検証)🔵 *M4 REQ-404 踏襲*
- REQ-405: **NFR-103 性能上限**を守らなければならない: `nested` 裁定は 1 仮説 ≤ 30 分を目標とし、超過時は
  打ち切り + Laplace 代替 + 警告。MEM スポット解析は spot 単位で完結し全フレーム自動反復を既定にしない 🔵 *NFR-103/FR-606*
- REQ-406: Dysnomia / dynesty / UltraNest / PyBOED は **バージョン固定 + contract test**(GSAS-II と同様、
  NFR-106)で扱わなければならない。外部バイナリ(Dysnomia)は入出力ファイル契約を固定する 🔵 *NFR-106/リスク表*

## 非機能要件

- NFR-001: `nested` 裁定は **1 仮説 ≤ 30 分を目標**とし、超過時は打ち切り + Laplace 代替 + 警告
  (NFR-103 の実装保証)🔵 *NFR-103*
- NFR-002: MEM / nested / OED テストは **外部依存なしで通過する層(境界・入力生成・提案スキーマ・較正)を
  通常 pytest で網羅**し、外部バイナリ/サンプラ依存は `@pytest.mark.nested` / `@pytest.mark.mem` /
  `@pytest.mark.oed` 相当で分離する 🟡 *M4 `@pytest.mark.mcp` パターン踏襲*
- NFR-003: 決定論・追記専用・ハッシュチェーン(M0〜M4 と同一)。nested は logZ±誤差でサンプラ種固定
  再現性 🔵 *NFR-102/105*
- NFR-004: 較正評価(reliability diagram / ECE)は `bic` と `nested` を別系列で評価し、レポートに
  backend 名と確率意味の違いを明記 🔵 *FR-124/§12-5*
- NFR-005: MEM-Rietveld 反復の各サイクルは子スナップショット追記で、親仮説・joint 結果は不変
  (P2 構造保証)🔵 *FR-603/P2*

## Edgeケース

- EDGE-001: `nested` 外部サンプラ未導入で nested 実行 → `NestedUnavailableError`、コア import は成功 🔵 *REQ-005*
- EDGE-002: `nested` 裁定が 30 分超過 → 打ち切り + Laplace 代替 + 警告(例外化しない)🔵 *REQ-101/NFR-103*
- EDGE-003: 生存仮説間に僅差競合なし → nested 再裁定を発動せず bic 一次判定を最終結果とする 🔵 *REQ-102*
- EDGE-004: フル nested 運転設定で全生存仮説を nested 裁定 → 各仮説 logZ±誤差を返し bic 一次をスキップ 🔵 *REQ-012*
- EDGE-005: Laplace の Hessian が特異/取得不能 → BIC 近似へフォールバック + 警告 🟡 *REQ-002*
- EDGE-006: Dysnomia バイナリ未導入で MEM 実行 → `MEMUnavailableError`(M4 の run_mem 境界と整合)、破壊なし 🔵 *REQ-020/REQ-104*
- EDGE-007: MEM 適用ガード条件不成立(多相/低統計)→ 信頼性警告を付し MEM 実行は継続(除外・中止しない)🔵 *REQ-031/REQ-103*
- EDGE-008: MEM-Rietveld 反復が発散 → 当該サイクルを子スナップショットに残し停止・ledger 記録(破壊しない)🟡 *REQ-107*
- EDGE-009: MEM-Rietveld 反復が収束前に最大反復到達 → 停止理由「max_iter」を ledger 記録し最終密度を返す 🔵 *REQ-026*
- EDGE-010: OED 提案発動条件(僅差競合)が無い → 提案 JSON は空配列、状態変更なし 🔵 *REQ-038*
- EDGE-011: PyBOED 未導入で獲得関数接続 API 呼び出し → `OEDUnavailableError`、提案生成(v1)は動作 🔵 *REQ-105*
- EDGE-012: 較正ベンチに nested logZ を含む → bic と nested の reliability/ECE を別系列出力 🔵 *REQ-106/REQ-016*
- EDGE-013: `run_mem` MCP を MEMBackend 実装済みで呼ぶ → 密度マップパス等を素の型 dict で返し破壊操作なし 🔵 *REQ-034*
- EDGE-014: nested 種固定・2 回実行 → logZ が誤差範囲内で一致(サンプラの確率性を logz_err で明示)🔵 *REQ-009/NFR-102*

## M5 スコープ外 (明示)

- ab initio 構造決定(§1.2 非スコープ・未知相フラグと外部引き渡しのみ)、
- PDF 解析・磁気構造精密化・2D 方位解析(§1.2 非スコープ)、
- MEM-Rietveld 反復の条件付き auto 運転本実装(v1 は既定オフ・REQ-302)、
- PyBOED 獲得関数による能動的次測定「実行」(v1 は提案生成のみ・REQ-036/FR-432)、
- Dysnomia 以外の内製 MEM ソルバ(MEMBackend 境界は用意するが v1 実装は Dysnomia 連携のみ)、
- nested 事前分布の高度な階層モデル(v1 は restraint 自動構成 + 手動上書き・FR-125)、
- ベンチ公開の CI/公開基盤整備(§13 M5 の「ベンチ公開」は較正ベンチ実装までを M5 要件とし公開運用は M-later)。
