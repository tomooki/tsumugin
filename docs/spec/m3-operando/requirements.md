# m3-operando 要件定義書

## 概要

Tsumugin マイルストーン M3: **operando 電池モード**と**マルチスタート大域最適確認**を実装する。
電気化学チャネル同期 (CSV 汎用)、セル固定相テンプレート、固溶体 vs 二相反応の evidence 判別
(FR-313)、IC ペナルティ付き区間自動分割 (FR-316)、実効 μt 吸収補正 v1 (FR-317) を提供し、
判別の信頼性をマルチスタート (FR-230) で担保する。併せて Issue #3/#4/#5 を解消する。

上位仕様: [docs/tsumugin_spec_v0.3.md](../../tsumugin_spec_v0.3.md) §6 FR-230 / §7 FR-310〜317 / §13 M3 / §15。
M0/M1/M2 資産 (StagedRefinementEngine / HypothesisTreeSearch / SequentialEngine / evidence / selection / persistent store) の上に構築する。

## 関連文書

- [💬 interview-record.md](interview-record.md) / [📖 user-stories.md](user-stories.md) /
  [✅ acceptance-criteria.md](acceptance-criteria.md) / [📝 note.md](note.md) / [🔧 prep.md](prep.md)

## 機能要件（EARS記法）

**【信頼性レベル凡例】**: 🔵 仕様書・Issue・既存実装に依拠 / 🟡 妥当な推測で確定 (根拠記載) / 🔴 根拠なし推測

### 通常要件 — マルチスタート (FR-230)

- REQ-001: システムは候補仮説に対し、初期値を**系統摂動**した N 本 (既定 8、設定可 8-16) の
  独立精密化を実行できなければならない。摂動は格子 ±設定幅・scale 対数一様・占有率の
  ラテン超方格とし、**決定論的な固定列** (乱数種固定) で生成する 🔵 *FR-231/NFR-102*
- REQ-002: システムは収束解を**パラメータ空間でクラスタリング**し、basin 数・各 basin の
  chi2/evidence・代表解を報告しなければならない 🔵 *FR-232*
- REQ-003: **複数 basin が検出された場合、各 basin を別仮説へ昇格**し evidence 比較に回さな
  ければならない (多峰性を隠蔽しない)。単一 basin は「大域最適の傍証あり」と報告する 🔵 *FR-232*
- REQ-004: マルチスタートの適用範囲は設定可能とし、既定は「accepted 候補の最終精密化時 +
  FR-313 判別時は必須」でなければならない 🔵 *FR-233*
- REQ-005: 各 start の精密化は独立な純関数構成とし、将来の Worker 並列化 (FR-234) を阻害
  してはならない (M3 の実行は逐次でよい) 🔵 *FR-234 (逐次実行は 🟡)*
- REQ-006: マルチスタート結果は `RefinementMetrics.multistart {n, n_basins}` として仮説に
  記録されなければならない (非破壊フィールド追加) 🔵 *§4 metrics*

### 通常要件 — operando 電池モード (FR-311〜315)

- REQ-007: システムは**電気化学 CSV 汎用マッパ**で V/I/Q (および換算 x) を読み込み、
  `ExternalChannel` (kind=echem 拡張) としてフレームへ同期できなければならない。
  容量→組成 x の換算則 (線形係数) を設定可能とする 🔵 *FR-311/§4 ExternalChannel*
- REQ-008: Biologic .mpr 等のバイナリローダは**インターフェース (Protocol) のみ**定義し、
  M3 では未実装エラーとする 🔵 *FR-311 (実装範囲は指示で確定)*
- REQ-009: システムは**セル固定相テンプレート** (Be 窓・Al 集電体・グラファイト等) を
  プリセットとして提供し、固定相は探索候補に常時含まれつつ構造パラメータは固定 (scale のみ
  解放) で扱えなければならない 🔵 *FR-312 (固定の粒度は 🟡)*
- REQ-010: システムは**固溶体 vs 二相反応判別** — 同一区間に対し (a) 単相・格子連続変化、
  (b) 二相共存・分率変化 の両仮説を**マルチスタート付き (REQ-004 必須適用)** で精密化し、
  Evidence Engine (bic 一次) で判別しなければならない。ΔBIC < 閾値 (既定 10) の僅差競合は
  エスカレーション (M2 selection 連携)。nested 裁定は M5 🔵 *FR-313/FR-122/FR-403*
- REQ-011: システムは**電気化学量との結合出力** — wt_frac(x)・格子(x)・転移点 x/V±σ を
  トラジェクトリ/CSV に含められなければならない 🔵 *FR-314 (dQ/dV 重ね描きはデータ出力のみ 🟡)*
- REQ-012: システムは**充放電往復のヒステリシス解析** — 充電枝/放電枝の分離と、同一 x に
  おける格子・分率の枝間差分を出力できなければならない 🔵 *FR-315 (出力形式は 🟡)*

### 通常要件 — IC 区間自動分割 (FR-316) + Issue #3

- REQ-013: システムは判別区間の境界を **IC ペナルティ付き changepoint 分割**で自動決定
  しなければならない: 区間数 k を 1 から逐次追加し、各分割の合計 evidence (bic + ペナルティ)
  を比較、**改善が閾値未満で打ち切り** (§15-1 確定案)。粗い格子スキャン→境界近傍の細密化の
  2 段で計算量を抑える 🔵 *FR-316*
- REQ-014: 各分割仮説 (k=1,2,…) は **Hypothesis として保存**され、代替分割を閲覧・選択
  できなければならない 🔵 *FR-316*
- REQ-015 (Issue #3): 新規未マッチピーク指標は**強度閾値と持続条件 (連続 M フレーム、既定 2)**
  を持ち、単発ノイズで changepoint / 局所探索が連発しないよう較正されなければならない 🔵 *Issue #3*

### 通常要件 — 吸収補正 v1 (FR-317)

- REQ-016: システムは **CellConfig** データモデル (geometry: transmission|capillary、
  layers (role/material/thickness_mm/density)、beam (energy or wavelength/size)) を持たな
  ければならない (§4。層状セルは透過法のみ) 🔵 *FR-317/§4 CellConfig*
- REQ-017: 吸収補正は**実効 μt の 1 パラメータをフィット変数**として精密化し、CellConfig
  由来の計算値 (提供時) を **restraint (許容幅付き soft bound)** として機能させなければ
  ならない 🔵 *FR-317 v1 確定案*
- REQ-018: CellConfig 未提供時は**経験的推定モード** — 実効 μt を弱 restraint で精密化し、
  結果に**明示警告**と逆算 μt の提示を含めなければならない 🔵 *FR-317*
- REQ-019: 組成→μt のエネルギー依存計算 (xraylib 等) は **Protocol インターフェースのみ**
  定義し、M3 では未実装エラーとする (CellConfig 提供時の restraint 中心値はユーザー指定
  μt_calc を受け取る) 🔵 *FR-317 (実装範囲は指示で確定)*
- REQ-020: 吸収補正は前方モデルに透過配置の吸収因子として乗算され、SimulatedBackend で
  検証可能でなければならない (GSAS-II 側は scale への吸収の畳み込みとして v1 近似) 🟡 *設計裁量*

### 通常要件 — Issue #4/#5 解消

- REQ-021 (Issue #4): `estimate_transition` の disappearing 相の onset は**遷移開始側**
  (90% 交差) を返すよう修正し、direction 別の onset/midpoint 順序をテストで固定しなければ
  ならない 🔵 *Issue #4*
- REQ-022 (Issue #5): `_finite_or_none` は共有ユーティリティ `tsumugin/_json.py` へ統合し、
  tree.py / webui / serialization の 3 実装を単一情報源にしなければならない (挙動不変) 🔵 *Issue #5*

### 条件付き要件

- REQ-101: FR-313 判別で両仮説の evidence 差が閾値未満の場合、システムは自動確定せず
  暫定判別 + Review Queue 通知としなければならない 🔵 *FR-122/FR-403*
- REQ-102: マルチスタートで発散 (chi2=inf) した start は basin クラスタリングから除外し、
  除外数を報告しなければならない (全滅時は判別を放棄せず警告付きで単一仮説報告) 🟡
- REQ-103: μt 精密化値が restraint 幅を超えて逸脱した場合、警告 (相関疑い §14) を出さな
  ければならない 🔵 *§14 リスク緩和*
- REQ-104: 充放電データで x が非単調 (往復) の場合、システムは枝分離 (充電/放電) を
  自動判定しなければならない 🟡 *FR-315 から導出*

### 制約要件

- REQ-401: 全新機能は P2 非破壊 (追記 + ledger 記録) と NFR-105 を維持しなければならない 🔵
- REQ-402: マルチスタート・区間分割・判別を含む全出力は同一入力でビット同一でなければ
  ならない (摂動列は決定論生成) 🔵 *NFR-102*
- REQ-403: コア依存は numpy のみを維持する。xraylib / .mpr パーサ等は Protocol +
  未実装エラー (将来 optional extra) 🔵 *CLAUDE.md*
- REQ-404: データモデル拡張 (CellConfig 新設 / ExternalChannel の echem 対応 /
  RefinementMetrics.multistart) は既存 API 後方互換の非破壊追加でなければならない 🔵 *REQ-404 踏襲*

## 非機能要件

- NFR-001: マルチスタート N=8 の判別テスト (合成データ) が CI 実用時間 (単一判別 < 30 秒) 🟡
- NFR-002: 区間分割の粗→細 2 段スキャンにより、フル逐次再精密化を区間境界近傍に限定 🔵 *FR-316*
- NFR-201: 決定論・追記専用・ハッシュチェーン (M0〜M2 と同一) 🔵

## Edgeケース

- EDGE-001: マルチスタート全 start が単一 basin → n_basins=1、「大域最適の傍証あり」報告 🔵
- EDGE-002: 全 start 発散 → 警告付きで元の仮説を維持 (クラッシュしない) 🟡
- EDGE-003: echem CSV の列欠損/行数不一致 → 明示エラー (列名を示す)、部分同期は警告 🟡
- EDGE-004: 区間分割で k=1 (分割なし) が最良 → そのまま採択 (固溶体単区間) 🔵
- EDGE-005: FR-313 で両仮説とも高 R → 未知相フラグ + エスカレーション (判別しない) 🔵 *FR-403*
- EDGE-006: μt=0 (吸収なし) 境界 → 補正因子 1 で既存結果と一致 🔵
- EDGE-007: ヒステリシス解析で片枝のみのデータ → 差分 None + 警告 🟡
- EDGE-101: N=1 のマルチスタート → 摂動なし 1 本 (基準解のみ、basin=1) 🟡

## M3 スコープ外 (明示)

- nested sampling 裁定 (M5)、xraylib 実装・.mpr 実装 (インターフェースのみ)、
  Ray/multiprocessing 並列 (FR-234 実行系)、dQ/dV プロット描画 (データ出力のみ)、
  中性子吸収補正モデル (M4)、フレーム依存 μ 平滑追跡 (M-later、v1 は区間一定)
