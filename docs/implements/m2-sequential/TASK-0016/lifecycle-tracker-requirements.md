# TASK-0016 TDD 要件定義書: LifecycleTracker (ヒステリシス付き birth/death)

**機能名**: LifecycleTracker (相ライフサイクル・ヒステリシス追跡)
**要件名**: m2-sequential / **タスクID**: TASK-0016 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 2 時系列コンポーネント / **信頼性サマリー**: 🔵 4 / 🟡 1

> すべてのファイルパスはプロジェクトルートからの相対パス。
> 信頼性: 🔵 資料準拠(推測なし) / 🟡 妥当な推測 / 🔴 資料外推測。

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 時系列 (operando/高温) 解析で、各相 (phase_ref) が **いつ出現 (birth) し
  いつ消滅 (death) したか** を、フレーム列を通じて **ヒステリシス** (連続 N フレームの存在/不在で確定)
  付きで追跡し、相ごとに `PhaseLifecycle`(birth_frame / death_frame / confidence) を確定する。
- 🔵 **解決する問題**: 精密化のフレーム間ノイズによる相の **点滅 (1〜2 フレームの偽出現/偽消失)** を抑制し、
  相の実在区間を安定して同定する。ヒステリシスにより偽 birth/偽 death を除去する (REQ-004 / FR-305)。
- 🔵 **想定ユーザー**: シーケンシャル解析エンジン (後続 TASK-0019 `SequentialEngine`) が内部ドライバとして
  毎フレーム `observe()` を呼び、実行終了時に `finalize()` で相ライフサイクル辞書を取得する。
- 🔵 **システム内での位置づけ**: `src/tsumugin/sequential/` パッケージの一コンポーネント
  (`changepoint.py` の changepoint 検出と並ぶ時系列解析部品)。model 層の既存値オブジェクト
  `PhaseLifecycle` (TASK-0011 実装済) を出力型として再利用する。
- **参照した EARS 要件**: REQ-004, REQ-201, FR-305
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py`(L118-133), `docs/design/m2-sequential/architecture.md`

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 実装対象 (`src/tsumugin/sequential/lifecycle.py` 新規)

- 🔵 **`LifecycleConfig`** (frozen dataclass) — 設定値オブジェクト:
  - `hysteresis: int = 3` — 連続 N フレームで birth/death を確定する窓幅 (既定 N=3)。
  - `presence_wt_frac: float = 1e-3` — 存在判定の wt_frac 下限 (Config に保持・文書化)。

- 🔵 **`LifecycleTracker`** — ステートフルなトラッカークラス:
  - `__init__(self, *, config: LifecycleConfig = LifecycleConfig()) -> None`
    キーワード専用引数 `config`。内部に相ごとの観測履歴 (可変状態) を保持。
  - `observe(self, frame_index: int, present_refs: Sequence[str]) -> None`
    - **入力**: `frame_index` (当該フレーム番号, int)、`present_refs` (そのフレームで存在する相 ref の列)。
    - **効果**: 各相の連続 present/absent ランを更新 (戻り値なし)。**呼び出しは frame_index 昇順を想定**。
  - `finalize(self) -> Mapping[str, PhaseLifecycle]`
    - **出力**: `{phase_ref: PhaseLifecycle}`。各 `PhaseLifecycle` は
      `birth_frame: int | None` / `death_frame: int | None` / `confidence: float`。

### 出力セマンティクス (中核ロジック)

- 🔵 **birth_frame**: ある相が **連続 hysteresis フレーム存在**したら birth 確定。値は
  その連続の **最初のフレーム** (N フレーム目で確定するが記録するのは連続開始 frame)。
- 🔵 **death_frame**: birth 済みの相が **連続 hysteresis フレーム不在**になったら death 確定。値は
  その **不在連続の最初のフレーム**。未消滅は `None`。
- 🔵 **death 取り消し (REQ-201)**: death 確定前でも、不在連続がヒステリシス窓に満たないうちに
  **再出現**したら不在ランをリセットし連続 (存在継続) 扱いに戻す。
- 🟡 **confidence**: **存在フレーム率** = 存在フレーム数 / 総観測フレーム数 (実装時に分母を確定し docstring に根拠明記)。
  全フレーム存在の相は 1.0。
- **入出力の関係性**: 観測列 (frame_index × present_refs の系列) → 相ごとに 1 つの `PhaseLifecycle` へ縮約。
- **データフロー**: `SequentialEngine` が各フレームの present 相集合を `observe()` に流し込み、
  終了時 `finalize()` で相ライフサイクル辞書を得て `Trajectory` / 相へ反映 (後続タスク)。
- **参照した EARS 要件**: REQ-004, REQ-201
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py`(L118-133 契約 / L31-45 `PhaseLifecycle`),
  `src/tsumugin/model/phase.py`(`PhaseLifecycle` 実体), `docs/design/m2-sequential/dataflow.md`

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **決定論 (REQ-402 / NFR-202)**: 乱数不使用。相 ref の走査は安定順序 (初出順またはソート)。
  同一入力・同一 Config で `finalize()` 出力がビット同一。
- 🔵 **モデル非破壊 (REQ-404 / P2)**: 出力型 `PhaseLifecycle` は既存 (`model/phase.py`, TASK-0011) を
  **再利用**し、新設・改変しない。フィールド名 (birth_frame/death_frame/confidence) を変えない。
- 🔵 **契約固定**: シグネチャは `docs/design/m2-sequential/interfaces.py` L118-133 準拠
  (`LifecycleConfig` フィールド名・既定値、`LifecycleTracker` のメソッド名/引数名)。後続 TASK-0019 が依存。
- 🔵 **コーディング規約 (CLAUDE.md)**: frozen dataclass の Config、型注釈必須 (`any` 回避)、
  日本語 docstring 可、`uvx ruff check` (line-length 100, py312) 通過。snake_case/PascalCase。
- 🟡 **パフォーマンス**: 合成 100 フレーム規模で軽量 (O(フレーム数 × 相数))。numpy 不要・標準ライブラリで実装可。
- 🔵 **公開面**: `src/tsumugin/sequential/__init__.py` の `__all__` に `LifecycleConfig` / `LifecycleTracker` を
  アルファベット昇順で追加。
- **参照した EARS 要件**: REQ-402, REQ-404, NFR-202
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py`, `CLAUDE.md`(不変条件/規約),
  `src/tsumugin/sequential/{changepoint,__init__}.py`(既存様式)

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 基本使用パターン
- 🔵 **birth 確定 (TC-103-01)**: frame 10 から相 B が連続出現 → `birth_frame == 10`。
- 🔵 **death 確定 (TC-103-02)**: 相 A が frame 15 から連続不在 → `death_frame == 15`。
- 🔵 **点滅抑制 (TC-103-03)**: 相が 1 フレームだけ (< N=3) 出現 → birth と認定されない (`birth_frame is None`)。
- 🔵 **death 取り消し (TC-103-04 / REQ-201)**: death 判定に至る前 (窓内) に再出現 → death 取り消し・連続扱い。
- 🟡 **全フレーム存在**: 相が全フレーム present → `birth_frame == 最初の frame`, `death_frame is None`,
  `confidence == 1.0`。

### エッジ/縮退ケース
- 🟡 **空観測 (EDGE-001 系)**: `observe()` を一度も呼ばず `finalize()` → 空 Mapping (例外なし)。
- 🟡 **単一フレーム (EDGE-101 系)**: 1 フレームのみ観測 → hysteresis 未達なら birth 未確定。
- 🟡 **death 後に再度出現**: death 確定後に窓を超えて再出現した場合の扱い (再 birth するか) は
  テストで意味論を固定する (基本は 1 相 1 ライフサイクルの範囲で TC-103 を満たすことを優先)。
- **参照した EARS 要件**: REQ-004, REQ-201, EDGE-001, EDGE-101
- **参照した設計文書**: `docs/spec/m2-sequential/acceptance-criteria.md`(TC-103 系),
  `docs/design/m2-sequential/dataflow.md`

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: `docs/spec/m2-sequential/user-stories.md` (相ライフサイクル追跡)
- **参照した機能要件**: REQ-004 (相ライフサイクル + ヒステリシス点滅抑制)
- **参照した状態要件**: REQ-201 (death 後の窓内再出現で death 取り消し・連続扱い)
- **参照した非機能要件**: NFR-202 (決定論), REQ-402 (ビット同一出力), REQ-404 (モデル非破壊)
- **参照した Edge ケース**: EDGE-001 (空フレーム列 → 空), EDGE-101 (単一フレーム)
- **参照した受け入れ基準**: `docs/spec/m2-sequential/acceptance-criteria.md` L37-42
  - TC-103-01 (birth_frame=10) / TC-103-02 (death_frame=15) / TC-103-03 (点滅非認定) /
    TC-103-04 (death 取り消し / REQ-201)
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m2-sequential/architecture.md` (sequential パッケージ構成)
  - **データフロー**: `docs/design/m2-sequential/dataflow.md` (フレーム観測 → lifecycle 縮約)
  - **型定義/契約**: `docs/design/m2-sequential/interfaces.py` L118-133 (`LifecycleConfig`/`LifecycleTracker`),
    L31-45 (`PhaseLifecycle`)
  - **既存実装**: `src/tsumugin/model/phase.py` (`PhaseLifecycle` 値オブジェクト),
    `src/tsumugin/sequential/{changepoint,series,__init__}.py` (同パッケージ様式)
- **タスク定義**: `docs/tasks/m2-sequential/TASK-0016.md`
- **開発コンテキスト**: `docs/implements/m2-sequential/TASK-0016/note.md`

---

## 品質判定

✅ **高品質**
- 要件の曖昧さ: なし (契約は interfaces.py L118-133 に固定、意味論は TC-103 系で確定)
- 入出力定義: 完全 (Config フィールド / observe・finalize シグネチャ / PhaseLifecycle 出力型を明記)
- 制約条件: 明確 (決定論・モデル非破壊・契約固定・規約)
- 実装可能性: 確実 (標準ライブラリのみ、依存 TASK-0011 実装済)
- 信頼性レベル: 🔵 が支配的 (confidence 算出式のみ 🟡 = 実装時確定)

**残る 🟡 判断点** (テストで固定する):
1. `confidence` の分母 (総観測フレーム数 or birth〜death 区間) の定義。
2. death 確定後の再出現時の扱い (再 birth の有無)。
