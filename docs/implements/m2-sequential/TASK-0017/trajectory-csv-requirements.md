# TASK-0017 TDD 要件定義書: Trajectory + FrameRecord + to_csv

**機能名**: trajectory-csv (時系列トラジェクトリ出力 + CSV 書き出し)
**要件名**: m2-sequential / **タスクID**: TASK-0017 / **タイプ**: TDD / **推定 3h**
**出力ファイル**: `docs/implements/m2-sequential/TASK-0017/trajectory-csv-requirements.md`
**作成日**: 2026-07-03 / **信頼性サマリー**: 🔵 FR-306 / REQ-005 / REQ-402 に依拠

> 本書のすべてのファイルパスはプロジェクトルートからの相対パス。
> 【信頼性凡例】🔵 EARS要件・設計文書にほぼ依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 時系列 (operando/高温) 逐次 Rietveld 解析の各フレーム結果を **1 行 = 1 フレーム**の構造化レコード (`FrameRecord`) として保持し、それらの列と相ライフサイクルをまとめた `Trajectory` を、**stdlib `csv` で CSV ファイルへ書き出せる**ようにする (`Trajectory.to_csv`)。
- 🔵 **解決する問題**: 逐次解析の出力 (フレーム軸値・相ごとの格子/scale/wt_frac・Rwp/GOF・changepoint・ライフサイクル) を、外部ツール (表計算・反応経路解析・JMAK 等) へ渡せる汎用フォーマットで永続化する。REQ-009 の「外部委譲出口」を CSV で満たす。
- 🔵 **想定ユーザー**: operando/高温実験の解析者、および後続の `SequentialEngine` (TASK-0019) — トラジェクトリを組み立てて `to_csv` を呼ぶ内部利用者。
- 🔵 **システム内の位置づけ**: `src/tsumugin/sequential/trajectory.py` (新設)。`sequential/` パッケージの出力層。上流は `FrameSeries`/`LifecycleTracker`/`detect_changepoint` の各結果 (それらの結合は TASK-0019 の責務。本タスクは器と CSV 化のみ)。
- **参照した EARS 要件**: REQ-005 (トラジェクトリ + CSV 出力), REQ-009 (外部委譲出口), REQ-402 (決定論), FR-306。
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` L141-165 (`FrameRecord` / `Trajectory` / `to_csv`)、`docs/tasks/m2-sequential/TASK-0017.md`。

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 データ型 `FrameRecord` (frozen dataclass) 🔵 interfaces.py L141-153

| フィールド | 型 | 制約・意味 | 信頼性 |
|---|---|---|---|
| `frame_index` | `int` | フレーム番号 (0 起点想定、負値は入力側責務) | 🔵 |
| `axis_value` | `float \| None` | フレーム軸値。index 軸/欠損は None 可 | 🔵 |
| `temperature` | `float \| None` | `ExternalChannel(temperature)` 由来。無ければ None | 🔵 |
| `phases` | `tuple[PhaseInstance, ...]` | 当該フレームの確定相集合 (順序保持) | 🔵 |
| `rwp` | `float \| None` | 重み付きプロファイル R。失敗フレームは None | 🔵 |
| `chi2` | `float \| None` | GOF (χ²)。失敗フレームは None | 🔵 |
| `changepoint` | `bool` | changepoint 判定フラグ | 🔵 |
| `changepoint_reasons` | `tuple[str, ...]` | `"rwp_jump"`/`"lattice_jump"`/`"new_peaks"` の部分集合 | 🔵 |
| `refine_failed` | `bool` | 精密化失敗フラグ (EDGE-002) | 🟡 |

### 2.2 データ型 `Trajectory` (frozen dataclass) 🔵 interfaces.py L156-165

| フィールド | 型 | 意味 | 信頼性 |
|---|---|---|---|
| `records` | `tuple[FrameRecord, ...]` | フレーム順の行 | 🔵 |
| `lifecycles` | `Mapping[str, PhaseLifecycle]` | 相 ref → birth/death/confidence | 🔵 |

### 2.3 メソッド `Trajectory.to_csv(self, path: str) -> str` 🔵 interfaces.py L163-165

- **入力**: `path` (書き出し先の文字列パス)。
- **出力 (戻り値)**: 書き出しに成功した `path` を `str` で返す (入力 path と一致)。`export_gpx` と同一契約。🔵
- **副作用**: `path` に stdlib `csv` 形式の CSV ファイルを 1 つ生成する。🔵
- **CSV 構造** (実装時にテストで凍結する列レイアウト):
  - 1 行目 = ヘッダ、以降 `len(records)` 行のデータ行 (1 フレーム 1 行)。🔵 TC-104-02
  - **フレーム共通列 (固定・先頭順)**: `frame_index, axis_value, temperature, rwp, chi2, changepoint, changepoint_reasons, refine_failed`。🔵🟡
  - **相ごと列**: 全 `records[*].phases` の `phase_ref` と `lifecycles` のキーの**和集合を `sorted()` 昇順**で確定し、各 ref につき `<ref>.a, <ref>.b, <ref>.c, <ref>.scale, <ref>.wt_frac, <ref>.birth_frame, <ref>.death_frame, <ref>.confidence` を出力。🟡 (完了条件①「相ごと格子 abc/scale/wt_frac + lifecycle」を満たす具体化)
  - `changepoint_reasons` (tuple) は決定論区切り (例 `|`) で 1 セルへ連結。🟡
  - 当該フレームに存在しない相の列、`None`/非有限の数値セルは**空文字列**。🔵 TC-104-03
- **入出力の関係性**: `to_csv` は純粋に `records`/`lifecycles` から CSV を導出する決定論写像 (I/O 以外の副作用なし)。同一 `Trajectory` から常に同一バイト列を生成する。🔵 REQ-402
- **参照した EARS 要件**: REQ-005, REQ-402。**参照した設計文書**: `docs/design/m2-sequential/interfaces.py` L141-165, `src/tsumugin/model/phase.py` (PhaseInstance/PhaseLifecycle/LatticeParams)。

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **CSV ライブラリ制約 (REQ-005)**: 書き出しは **stdlib `csv` のみ**。pandas/DataFrame/parquet 禁止 (parquet は M2 スコープ外)。
- 🔵 **決定論 (REQ-402 / NFR-102)**: 同一入力・同一設定で全出力バイト同一。乱数・時刻・環境依存・dict や set の非決定反復順に依存しない。相 ref は `sorted()` で昇順固定。列順は明示リストで構築。`open(..., newline="", encoding="utf-8")` で改行/エンコーディングを固定しバイト同一を担保。
- 🔵 **非有限値を漏らさない (完了条件③ / TC-104-03 / M1 レビュー教訓)**: `None` / `inf` / `-inf` / `NaN` は CSV に文字列として出さず**空欄**にする。`store/serialization.py` の `_finite_or_none` と同思想のローカル純化を用いる (レイヤ横断 import を避け trajectory.py 内に閉じる)。有限端点 (0.0/負値/極小) は保持。
- 🔵 **不変性 (CLAUDE.md P2 系規約)**: `FrameRecord` / `Trajectory` は `@dataclass(frozen=True)`。
- 🔵 **型の再利用 (REQ-404 非破壊)**: `PhaseInstance` / `PhaseLifecycle` は `src/tsumugin/model/phase.py` の既存型 (TASK-0011) を import して使う。**新設しない**。
- 🔵 **エクスポート規約**: `src/tsumugin/sequential/__init__.py` の `__all__` に `FrameRecord` / `Trajectory` をアルファベット昇順維持で追加。
- 🔵 **コーディング規約 (CLAUDE.md)**: 型注釈必須 (`any` 回避)、docstring 様式 (【機能概要】【実装方針】【テスト対応】+ 信頼性レベル)、`uvx ruff check` (line-length 100, py312) クリーン。
- 🟡 **パフォーマンス**: 明示 NFR は無いが、フレーム数 × 相数の 2 重ループの単純線形処理で足りる (REQ-403 の 100 フレーム目標に十分)。
- **参照した EARS 要件**: REQ-005, REQ-402, REQ-404。**参照した設計文書**: `CLAUDE.md` (不変条件・規約), `src/tsumugin/store/serialization.py` (非有限純化), `src/tsumugin/export/gpx.py` (path 返却契約)。

---

## 4. 想定される使用例（EARSEdgeケース・データフローベース）

### 4.1 基本使用パターン 🔵
1. 上流 (TASK-0019 SequentialEngine 想定) が各フレームの精密化結果から `FrameRecord` を生成し、`LifecycleTracker.finalize()` の結果を `lifecycles` にして `Trajectory` を構築。
2. `traj.to_csv("out.csv")` を呼ぶ → CSV が書かれ、`"out.csv"` が返る。
3. `csv.reader`/`csv.DictReader` で読み戻し、外部解析へ渡す (REQ-009)。

### 4.2 データフロー 🔵
`FrameSeries`/精密化結果/`ChangepointSignal`/`PhaseLifecycle`
→ (TASK-0019 で結合) → `tuple[FrameRecord]` + `lifecycles`
→ `Trajectory` → `to_csv` → CSV ファイル → 外部ツール。
(本タスクの責務は破線右側の `Trajectory` 構築と `to_csv` のみ。)

### 4.3 エッジケース 🔵🟡
- **EC-1 (空トラジェクトリ)** 🟡: `records=()` → ヘッダのみ (相列も無し) の CSV、データ行 0、例外なし。EDGE-001 の CSV 面。
- **EC-2 (単一フレーム)** 🟡: `records` 長 1 → データ行 1。EDGE-101 の CSV 面。
- **EC-3 (相なしフレーム)** 🟡: `phases=()` のフレーム → フレーム共通列のみ埋まり相列は空欄 (相列自体は他フレーム/lifecycles 由来で存在し得る)。
- **EC-4 (フレーム間で相集合が異なる)** 🔵: 途中で相 B が出現 → B の列は出現前フレームで空欄、出現後で値。列順は和集合 sorted で安定。REQ-402/TC-104-01。
- **EC-5 (lifecycles にのみ存在する相)** 🟡: あるフレームの `phases` には無いが `lifecycles` にキーがある相 → その相列 (格子等は全フレーム空、lifecycle 列のみ値) を出力。

### 4.4 エラー・失敗ケース 🔵
- **ER-1 (精密化失敗フレーム)**: `rwp=None`/`chi2=inf`/`refine_failed=True` → `rwp`/`chi2` セルは空欄、`refine_failed` は `True`。`inf`/`nan` 文字列がファイルに出ない。TC-104-03 / EDGE-002。
- **ER-2 (非有限が wt_frac/格子に混入)** 🟡: 相の `wt_frac=NaN` 等 → 空欄化。
- **参照した EARS 要件**: EDGE-001 (空), EDGE-101 (単一), EDGE-002 (失敗フレーム)。**参照した設計文書**: `docs/spec/m2-sequential/acceptance-criteria.md` TC-104 系 / TC-101-05,06 / TC-108-01 (CSV 出力まで完走)。

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: `docs/spec/m2-sequential/user-stories.md` — operando/高温解析結果の外部連携 (トラジェクトリ出力)。
- **参照した機能要件**: REQ-005 (トラジェクトリ + CSV), REQ-009 (外部委譲出口としての CSV 流用)。
- **参照した非機能要件**: REQ-402 / NFR-102 (決定論・ビット同一), REQ-403 (処理時間目標、参考)。
- **参照した Edge ケース**: EDGE-001 (空フレーム列), EDGE-101 (単一フレーム), EDGE-002 (中間フレーム失敗)。
- **参照した受け入れ基準**: `docs/spec/m2-sequential/acceptance-criteria.md`
  - TC-104-01 (必須列: 軸値・相ごと格子/scale/wt_frac・Rwp・changepoint・lifecycle) 🔵
  - TC-104-02 (to_csv → csv.reader 読み戻し可、行数 = フレーム数) 🔵
  - TC-104-03 (非有限値が漏れない・失敗フレームは空欄/None 表現) 🟡
  - TC-108-01 (E2E で「CSV 出力まで完走」) — 後続の統合ゲート 🔵
- **参照した設計文書**:
  - **型定義**: `docs/design/m2-sequential/interfaces.py` L141-153 (`FrameRecord`), L156-165 (`Trajectory`/`to_csv`), L31-45 (`PhaseLifecycle`), L44-54 (`ExternalChannel`)。
  - **モデル**: `src/tsumugin/model/phase.py` (`PhaseInstance`/`PhaseLifecycle`/`LatticeParams`)。
  - **参考パターン**: `src/tsumugin/store/serialization.py` (`_finite_or_none` = M1 非有限教訓), `src/tsumugin/export/gpx.py` (書き出しパス返却契約), `src/tsumugin/sequential/{changepoint,lifecycle,series}.py` (docstring/決定論様式)。
  - **タスクノート**: `docs/implements/m2-sequential/TASK-0017/note.md`。

---

## 6. 完了条件 (TASK-0017.md 由来) と要件の対応

| 完了条件 | 対応要件 | 受け入れ基準 |
|---|---|---|
| ① 必須列 (軸値/相ごと格子 abc/scale/wt_frac/Rwp/changepoint/lifecycle) が含まれる | §2.3 CSV 構造 | TC-104-01 🔵 |
| ② to_csv → csv.reader 読み戻し、行数 = フレーム数 | §2.3 / §4.1 | TC-104-02 🔵 |
| ③ 失敗フレーム (rwp=None) 空欄・非有限がファイルに漏れない | §3 非有限制約 / §4.4 | TC-104-03 🔵 |
| ④ 列順が決定論 (2 回出力でバイト同一) | §3 決定論制約 | REQ-402 🔵 |

---

## 7. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (契約は interfaces.py L141-165 に固定、完了条件が受け入れ基準に 1:1 対応)
- 入出力定義: 完全 (FrameRecord 9 フィールド / Trajectory 2 フィールド + to_csv 契約を明記)
- 制約条件: 明確 (stdlib csv 限定 / 決定論バイト同一 / 非有限空欄 / frozen / 型再利用)
- 実装可能性: 確実 (標準ライブラリのみ、既存 _finite_or_none パターン流用、前提 TASK-0011/0016 実装済)
- 信頼性レベル: 🔵 が多数 (契約・要件由来)。🟡 は CSV 列レイアウト詳細 (列名・区切り・相列の並び) と
  refine_failed セマンティクスに限定 — いずれもテストで凍結して確定する
```

**残る決定事項 (testcases フェーズで凍結)**: (a) 相ごと列の正確な列名 (`<ref>.a` 等) と α/β/γ・σ・volume を含めるか、(b) `changepoint_reasons` の連結区切り文字、(c) `bool` の CSV 表現 (`True`/`False` 文字列 or `1`/`0`)、(d) 空トラジェクトリ時のヘッダ有無。これらはテストケース洗い出しで固定する。
