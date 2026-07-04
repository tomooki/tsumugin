# TASK-0029 TDD要件定義: operando/echem — CSV マッパ + Loader Protocol (FR-311)

**機能名**: echem-csv-loader / **タスクID**: TASK-0029 / **要件名**: m3-operando
**タイプ**: TDD / **フェーズ**: Phase 3 (operando 電池モード) / **信頼性**: 🔵 4 / 🟡 1
**出力ファイル**: `docs/implements/m3-operando/TASK-0029/echem-csv-loader-requirements.md`
**作成日時**: 2026-07-04

> 本書のすべてのパスはプロジェクトルートからの相対パス。信頼性レベル: 🔵 要件・仕様・設計に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測。

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 電気化学測定 (充放電) の汎用 CSV を読み込み、電圧 (V) / 電流 (I) / 容量 (Q)、および
  容量→組成 x への線形換算値を、粉末回折フレームに同期した `ExternalChannel` 群として供給する入力層。
  併せて機種別バイナリ (.mpr 等) 用の交換境界 Protocol を定義する。
- 🔵 **解決する問題**: operando 電池計測では回折データと電気化学量が別ファイル・別列名で得られる。ユーザ指定の
  列名マッピングと換算則で両者をフレーム単位に紐付け、後段の x 依存解析 (格子(x)・分率(x)・転移点 x/V) の
  入力を安全 (eval 不使用) かつ決定論的に整える。
- 🔵 **想定ユーザー**: operando 電池計測を Rietveld 解析する研究者、および結合出力 (TASK-0034) や区間判別
  (`discrimination.py`) を駆動する上位パイプライン。
- 🔵 **システム内での位置づけ**: `src/tsumugin/operando/echem.py` (新規モジュール)。M3 operando の**入口**。
  データフロー `FrameSeries + echem CSV → read_echem_csv → EchemData → ExternalChannel 群` の中核 (dataflow.md L16-17)。
  コア依存は numpy のみ維持し、本機能自体は stdlib のみで完結する。
- **参照したEARS要件**: REQ-007 (CSV マッパ + 換算), REQ-008 (Protocol のみ / 未実装エラー) 🔵
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` L37/L114/L130, `docs/design/m3-operando/dataflow.md` L16-17

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

契約は `docs/design/m3-operando/interfaces.py` L199-228。

### 2.1 `EchemData` (frozen dataclass) — 🔵

- フィールド (要素は `float | None`、欠損は None、全 tuple):
  - `voltage: tuple[float | None, ...]` — 位置必須 🔵
  - `current: tuple[float | None, ...] = ()` 🔵
  - `capacity: tuple[float | None, ...] = ()` 🔵
  - `composition_x: tuple[float | None, ...] = ()` — 換算済み x 🔵
- メソッド `to_channels() -> tuple[ExternalChannel, ...]` 🟡:
  - 非空フィールドを対応 kind (`"voltage"`/`"current"`/`"capacity"`/`"composition"`) の `ExternalChannel` へ変換。
  - `sync_map` は `{frame_index: 値}`。**None フレームは sync_map に含めない** (欠損=不同期、捏造しない / dataflow.md L124)。
  - 空フィールド (既定 `()`) はチャネルを生成しない。
- 🔵 frozen・等価比較 (`==`)・生成が可能。全フィールド tuple のためハッシュ可。

### 2.2 `read_echem_csv(path, *, column_map, capacity_to_x=None) -> EchemData` — 🔵

- **入力**:
  - `path: str` — CSV ファイルパス 🔵
  - `column_map: Mapping[str, str]` — 論理名→CSV 列名。例 `{"frame":"index","voltage":"Ewe/V","current":"I/mA","capacity":"Q/mAh"}` 🔵
  - `capacity_to_x: tuple[float, float] | None = None` — `(slope, intercept)`。指定時 `x = slope·Q + intercept` 🔵
- **処理**:
  - stdlib `csv` で読み (pandas 等不使用) 🔵。数値セルは `float()` で明示変換 (**eval/exec/ast.literal_eval 禁止**) 🔵。
  - `column_map` の各論理列を CSV ヘッダ列名で抽出し tuple 化 🔵。
  - `capacity_to_x` 指定かつ capacity 取得時、各要素に線形換算を適用し `composition_x` を生成 🔵。
- **出力**: `EchemData` (フレーム同期済み) 🔵
- **エラー/警告** (§3・§4 参照): 列欠損=列名入り `ValueError`、数値変換失敗=列名入り明示エラー、行数不一致=None+警告 🟡

### 2.3 `EchemLoader` Protocol / `BiologicMprLoader` スタブ — 🔵

- `EchemLoader` (Protocol): `load(self, path: str) -> EchemData` — 機種別ローダの交換境界 🔵
- `BiologicMprLoader`: `load` は M3 では **`NotImplementedError`** を送出するスタブ (Biologic .mpr バイナリは後続スコープ) 🔵

### 2.4 入出力の関係性・データフロー — 🔵

- `read_echem_csv` (or `EchemLoader.load`) → `EchemData` → `to_channels()` → `ExternalChannel` 群 → 上位でフレーム同期利用。
- x は `capacity` と `capacity_to_x` から派生 (独立入力ではない)。
- **参照したEARS要件**: REQ-007 (V/I/Q + 換算 x, 線形係数設定可) 🔵
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py` L199-228, `docs/design/m3-operando/dataflow.md` L16-17/L124

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **セキュリティ (NFR / 完了条件)**: CSV 数値変換は `float()` のみ。**`eval`/`exec`/`ast.literal_eval` を使わない**
  (信頼できない CSV を安全に読む)。変換失敗は列名を示す明示エラーに変換。参照: architecture.md L130。
- 🔵 **依存制約 (REQ-403 / REQ-005 系)**: stdlib `csv` 限定。pandas 等の外部 CSV パーサ不使用。コア依存は numpy のみ維持。
  本機能自体は numpy にも GSAS-II にも xraylib にも依存しない。
- 🔵 **決定論 (NFR-102 / REQ-402)**: 同一 CSV → ビット同一 `EchemData`。行順・列順は CSV 記載順で確定。乱数不使用。
- 🔵 **後方互換 / 非破壊 (REQ-404)**: `ExternalChannel` / `ChannelKind` (TASK-0025 で voltage/current/capacity/composition
  拡張済) を**利用のみ**。model を変更しない。既存全テストを無改変で維持。
- 🔵 **アーキテクチャ制約**: 新規 `src/tsumugin/operando/` ディレクトリ配下 `echem.py`。frozen dataclass +
  `typing.Protocol` 境界。未実装機種ローダは呼出時 `NotImplementedError` (M0/M1/M2 スタブ規約と同型)。
- 🔵 **型注釈必須**: `tuple[float | None, ...]` / `Mapping[str, str]` / `tuple[float, float] | None`。`any` 回避。
  `from __future__ import annotations` を冒頭に置く。line-length 100・ruff clean。
- **参照したEARS要件**: REQ-007/008, REQ-402 (決定論), REQ-403 (コア依存 numpy), REQ-404 (非破壊), NFR-102 🔵
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` L37/L114/L130, `CLAUDE.md` (不変条件・規約)

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本使用パターン — 🔵

- **正常読込 (TC-202-01)**: `frame,V,I,Q` 列 CSV を `column_map={"frame":..,"voltage":..,"current":..,"capacity":..}`
  で読み、`to_channels()` が voltage/current/capacity kind の `ExternalChannel` 群を返す。各 `value_for(frame)` が正しい値。
- **容量→x 換算 (TC-202-02)**: `capacity_to_x=(a, b)` 指定で `composition_x[i] == a·Q[i] + b`、
  `composition` kind チャネルが生成される。

### 4.2 データフロー — 🔵

- `FrameSeries + echem CSV` → `read_echem_csv (列マッピング + 容量→x 換算)` → `EchemData` → `ExternalChannel 群 (フレーム同期)`
  (dataflow.md L16-17)。欠損は frame_index キーの外部結合で None (捏造しない / L124)。

### 4.3 エッジ・エラーケース (EDGE-003 / D-Q7 確定政策) — 🟡

- **列欠損 = 明示エラー (TC-202-03a)**: `column_map` が要求する列が CSV ヘッダに無い → **列名を含む `ValueError`**
  (処理継続不能)。dataflow.md L110 準拠。
- **行数不一致 = None+警告 (TC-202-03b)**: 列間で行数が異なる → **短い方に合わせ欠損を None + `warnings.warn(UserWarning)`**
  (部分同期は縮退継続)。M2 温度チャネル欠損 (None+警告) と同一政策 (design-interview D-Q7)。
- **数値変換失敗 = 明示エラー**: 数値でないセル (例 `"abc"`) → **列名を含む明示エラー**。`eval` を経由しない (完了条件)。
- **未実装機種ローダ (TC-202-04)**: `BiologicMprLoader().load(path)` → `NotImplementedError` (REQ-008)。

### 4.4 政策の非対称性 (厳守) — 🟡

- **列欠損 = エラー** (列名提示・停止) / **行数不一致 = 警告** (縮退継続)。EDGE-003 の「明示エラー」と「部分同期は警告」を取り違えない。
- **参照したEARS要件**: REQ-007 (基本), REQ-008 (未実装エラー), EDGE-003 (列欠損/行数不一致) 🔵🟡
- **参照した設計文書**: `docs/design/m3-operando/dataflow.md` L16-17/L110/L124, `docs/design/m3-operando/design-interview.md` D-Q7

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: `docs/spec/m3-operando/user-stories.md` — operando 電池計測の電気化学同期入力
- **参照した機能要件**: REQ-007 (電気化学 CSV 汎用マッパ + 容量→x 線形換算), REQ-008 (バイナリローダは Protocol のみ / M3 未実装エラー)
- **参照した非機能要件**: NFR-102 (再現性/決定論), REQ-402 (決定論), REQ-403 (コア依存 numpy), REQ-404 (非破壊拡張)
- **参照した Edge ケース**: EDGE-003 (echem CSV 列欠損/行数不一致 → 明示エラー/部分同期は警告)
- **参照した受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md` L22-27
  - TC-202-01 (列マッピング読込 + V/I/Q 同期) 🔵
  - TC-202-02 (容量→x 線形換算) 🔵
  - TC-202-03 (列欠損=列名エラー / 行数不一致=None+警告) 🟡
  - TC-202-04 (未実装 .mpr ローダ = NotImplementedError) 🔵
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m3-operando/architecture.md` L37 (operando/echem.py 役割), L114 (operando/ 新規), L130 (eval 不使用)
  - **データフロー**: `docs/design/m3-operando/dataflow.md` L16-17 (読込フロー), L110 (列欠損エラー), L124 (欠損 None・捏造しない)
  - **型定義**: `docs/design/m3-operando/interfaces.py` L199-208 (EchemData), L211-218 (read_echem_csv), L221-228 (EchemLoader/BiologicMprLoader)
  - **設計判断**: `docs/design/m3-operando/design-interview.md` D-Q7 (echem 同期の欠損政策 — 確定)
  - **データベース**: 該当なし (ファイル I/O のみ・DB 非使用)
  - **API仕様**: 該当なし (ライブラリ内部 API / HTTP エンドポイント非使用)

---

## 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (契約は interfaces.py L199-228 で確定、欠損政策は D-Q7 で確定)
- 入出力定義: 完全 (EchemData/read_echem_csv/EchemLoader の型・既定・変換規則を明記)
- 制約条件: 明確 (eval 不使用・stdlib csv 限定・決定論・非破壊)
- 実装可能性: 確実 (TASK-0025 で ChannelKind/ExternalChannel 整備済、依存は stdlib のみ)
- 信頼性レベル: 🔵 4 / 🟡 1 — 🟡 は EDGE-003 (列欠損/行数不一致) の警告文言・縮退詳細に集中し要件へ遡及可能
```

**次のお勧めステップ**: `/tsumiki:tdd-testcases m3-operando TASK-0029` でテストケースの洗い出しを行います。
