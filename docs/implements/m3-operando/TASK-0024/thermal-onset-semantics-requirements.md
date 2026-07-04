# TASK-0024 要件定義: thermal onset 意味論修正 (Issue #4)

**機能名**: thermal-onset-semantics / **タスクID**: TASK-0024 / **要件名**: m3-operando
**タイプ**: TDD (意味論修正) / **信頼性**: 🔵 (Issue #4 / REQ-021 / D-Q8 / interfaces.py L372-373 / TC-208-01/02)

> すべてのパスはプロジェクトルートからの相対パス。

---

## ⚠️ 前提: 仕様文書の順序不等号の矛盾 (要件確定の根拠)

`docs/tasks/m3-operando/TASK-0024.md` (L12/L20) と `docs/spec/m3-operando/acceptance-criteria.md` TC-208-01 は
disappearing について **「onset(90%) > midpoint」** と記すが、これは採用メカニズム (90% 交差) と**数値的に矛盾**する。
`SIGMOID_DOWN` (中心 400 K, 幅 15, 昇温) の実測交差は 90% ≈ **366.46 K** < 50% = 400 K < 10% ≈ 433.54 K。
単調減少シグモイドでは 90% 交差は**必ず midpoint より低温側**であり、**disappearing でも `onset < midpoint`** が正しい。
これは Issue #4 の目的 (「onset は遷移に先行すべき = 修正前の `onset(10%)>midpoint` を解消」) と整合する。
**本要件は 90% 交差メカニズム + `onset < midpoint` (遷移開始側=低温側) で確定**し、上流 (TC-208-01/TASK-0024.md 本文) の
「> midpoint」表記は**誤記として差し戻し対象**とする (詳細は `note.md` §⚠️ 矛盾フラグ)。🔵

---

## 1. 機能の概要（EARS 要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: `src/tsumugin/sequential/thermal.py::estimate_transition` の **onset (転移開始温度) の意味論を修正**し、
  onset が direction に依らず**「遷移が始まる側 (低温側・先行するエッジ)」**を指すようにする。具体的には
  **disappearing 相 (分率 1→0) の onset を分率 90% 交差**とし、appearing 相 (分率 0→1) は現行の分率 10% 交差を維持する。
- 🔵 **どのような問題を解決するか**: 現状 `estimate_transition` は direction に関わらず分率 10% を横切る**最初の交差**を onset とするため、
  disappearing では 10% 交差が**高温側 (遷移の終端側)** に来て `onset > midpoint` となる。「onset」の命名は遷移の先行 (開始) を含意するため、
  下流で「遷移開始温度」と解釈すると**誤読を招く** (Issue #4)。90% 交差へ切り替えることで onset を遷移開始側 (低温側) に統一する。
- 🔵 **想定されるユーザー**: `estimate_transition` の結果 `TransitionEstimate.onset` を消費する解析・可視化・レポート層 (開発者)。
  disappearing 相の転移温度を扱う operando/高温解析の利用者。フィールド名 `onset` は不変のため呼び出しコードの変更は不要。
- 🔵 **システム内での位置づけ**: `sequential/thermal.py` は Workers 層の**純関数モジュール** (FR-322/323)。乱数・I/O・外部状態を持たない
  決定論関数。本修正は `estimate_transition` 内部の onset レベル選択のみに閉じ、値オブジェクト署名・公開 API は不変。
- **参照した EARS 要件**: REQ-021 (Issue #4)
- **参照したユーザストーリー**: ストーリー 5.1「onset の誤読防止 (Issue #4)」(`docs/spec/m3-operando/user-stories.md` L109-110)
- **参照した設計文書**: `docs/design/m3-operando/design-interview.md` D-Q8 (L44-48)、
  `docs/design/m3-operando/interfaces.py` L372-373、`docs/spec/m3-operando/interview-record.md` Q9 (L50-53)

## 2. 入力・出力の仕様（EARS 機能要件・型定義ベース）

- 🔵 **対象関数署名 (不変)**:
  ```python
  def estimate_transition(
      temperatures: Sequence[float], fractions: Sequence[float], *, phase_ref: str
  ) -> TransitionEstimate | None: ...
  ```
- 🔵 **入力パラメータ (不変)**:
  - `temperatures: Sequence[float]` — フレーム毎の温度 (`fractions` と同長、昇温で単調増加想定)。
  - `fractions: Sequence[float]` — フレーム毎の相分率トラジェクトリ (0..1 想定)。appearing は増加基調、disappearing は減少基調。
  - `phase_ref: str` (キーワード専用) — 対象相の識別子 (結果へ透過保持)。
- 🔵 **出力値 (`TransitionEstimate` フィールド署名は不変・意味論のみ変更)**:
  - `phase_ref: str` — 入力を透過保持。
  - `onset: float | None` — **【修正対象】遷移開始側の分率交差温度 (線形補間)**。
    - direction=="appearing" → **分率 10% 交差**温度 (現行のまま)。
    - direction=="disappearing" → **分率 90% 交差**温度 (新)。
    - 交差が無い場合は `None`。
  - `midpoint: float | None` — 分率 50% 交差温度 (線形補間)。**不変**。
  - `sigma: float | None` — midpoint 交差隣接フレームの温度間隔ベースの散布度 (> 0)。**不変**。
  - `direction: Literal["appearing", "disappearing"]` — `fractions[-1] >= fractions[0]` で判定。**不変**。
- 🔵 **入出力の関係性 (direction 別 onset レベルの真理値表)**:
  | direction | 判定式 | onset 分率レベル | 期待される温度関係 |
  |---|---|---|---|
  | appearing (0→1) | `fractions[-1] >= fractions[0]` | **0.10** | onset(10%) < midpoint(50%) |
  | disappearing (1→0) | それ以外 | **0.90** | onset(90%) < midpoint(50%) |
  - **両方向とも `onset < midpoint`** (onset は遷移開始側=低温側)。🔵 *§⚠️ 前提の実測に基づく*
- 🔵 **具体値 (合成シグモイド, 中心 400 K・幅 15・300..490 K)**:
  | direction | onset (交差レベル) | midpoint | σ |
  |---|---|---|---|
  | appearing (SIGMOID_UP) | ≈ 366.46 K (10%) | ≈ 400 K | > 0 (≈ 10 K) |
  | disappearing (SIGMOID_DOWN) | ≈ 366.46 K (90%) | ≈ 400 K | > 0 (≈ 10 K) |
- 🔵 **データフロー**: `estimate_transition` は (1) 点数チェック → (2) midpoint=50% 交差 (無ければ `None`) → (3) direction 判定 →
  **(4) direction に応じた onset レベル (0.10 / 0.90) で `_interpolate_crossing` を呼ぶ [修正点]** → (5) σ 算出 → (6) `TransitionEstimate` 返却。
- **参照した EARS 要件**: REQ-021
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py` L372-373、`src/tsumugin/sequential/thermal.py` L51-65/L140-218、
  `docs/design/m2-sequential/interfaces.py` (TransitionEstimate 契約)

## 3. 制約条件（EARS 非機能要件・アーキテクチャ設計ベース）

- 🔵 **最小修正 (最重要)**: 変更点は **onset レベルの direction 依存化 1 点**に閉じる。midpoint 算出・direction 判定・σ 算出・
  点数不足縮退・`_interpolate_crossing` の探索アルゴリズムは**無改変**。`_interpolate_crossing` のシグネチャは変えず、
  呼び出し側 `estimate_transition` (L204-206) で onset レベルを選ぶのが最小差分 (例: `onset_level = _ONSET_LEVEL if direction == "appearing" else 1.0 - _ONSET_LEVEL`)。🔵 *D-Q8 / note §3*
- 🔵 **公開 API 非破壊 (P2 / REQ-404)**: `TransitionEstimate` のフィールド (名・型・順序) と `estimate_transition` の引数署名は不変。
  `onset` フィールド名は**維持** (中立名 `crossing_10pct` へ改名しない — API 破壊回避、interview Q9)。`__init__.py::__all__` 変更なし。
- 🔵 **決定論 / 純関数 (NFR-102)**: 副作用なし・入力非破壊・同一入力で**ビット同一**出力。乱数不使用。`==` 決定論を維持。
- 🔵 **非有限漏洩なし (M1 教訓 / CLAUDE.md)**: 90% 交差が無い (定数分率・端点未達等) 場合は onset=`None` に縮退し、例外化・inf/nan 漏洩をしない。
- 🔵 **既存テスト無退行 (TC-208-02)**: 既存 thermal テスト (`tests/test_thermal.py` 18 件) が**意味論修正後の期待値で green**。
  既存の期待値変更は**理由コメント付きで最小修正**。appearing 系テスト・`tests/test_m2_e2e.py` の appearing 経路は**無改変で green**。
- 🔵 **direction 別順序のテスト固定 (REQ-021)**: appearing/disappearing それぞれで onset/midpoint の順序をテストで固定する
  (現状 disappearing の onset は**未検証**のため**検証を追加**)。
- 🔵 **アーキテクチャ制約**: `sequential/thermal.py` は `numpy` + 標準ライブラリのみ。GSAS-II 非依存。Workers 層の純関数。
- 🔵 **フォーマット/Lint**: `uvx ruff check src tests` clean (line-length 100, target py312)。
- 🟢/制約 **git commit しない** (本セッションはユーザー判断)。**質問しない** (自律実行)。コミット時は "Closes #4"。
- **参照した EARS 要件**: REQ-021, REQ-404, NFR-102
- **参照した設計文書**: `docs/design/m3-operando/design-interview.md` D-Q8、`docs/spec/m3-operando/interview-record.md` Q9、
  `docs/spec/m3-operando/note.md` (制約節)、`CLAUDE.md`

## 4. 想定される使用例（Edge ケース・データフローベース）

- 🔵 **基本パターン (appearing)**: 昇温で相 B が出現 (fractions 0→1)。`estimate_transition` が onset=10% 交差 (低温側) を返す →
  `onset < midpoint`、`direction=="appearing"` (`tests/test_thermal.py::test_transition_sigmoid_up_midpoint_onset_sigma` /
  `tests/test_m2_e2e.py::test_e2e_transition_temperature_estimated` 相当)。**無改変で green**。
- 🔵 **基本パターン (disappearing・本タスクの核心)**: 昇温で相が消滅 (fractions 1→0)。`estimate_transition` が onset=**90% 交差** (低温側) を返す →
  `onset < midpoint`、`direction=="disappearing"` (`test_transition_sigmoid_down_direction_disappearing` に onset 検証を追加)。
- 🔵 **エッジ: 交差なし (定数分率)**: `fractions=[0.5]*n` は midpoint 交差が無いため `None` (遷移なし)。onset レベル変更の影響なし
  (`test_transition_constant_fraction_returns_none` 相当)。**無改変で green**。
- 🔵 **エッジ: 点数不足 (空/単一)**: 隣接対が作れず `None` へ縮退 (`test_transition_empty_or_single_frame_returns_none`)。**無改変で green**。
- 🟡 **エッジ: 90% に未達な disappearing (浅い遷移)**: 分率が 0.9 を下回らずに終わる (例 1.0→0.92) 場合、90% 交差が無く onset=`None`。
  midpoint (50%) も無ければ関数全体が `None`。例外化せず縮退 (`_interpolate_crossing` の `None` 経路を踏襲)。
- 🟡 **エッジ: 端点ちょうど 90%**: あるフレームの分率が正確に 0.90 の場合、符号積 `<= 0` の端点一致判定で一意に交差採用 (0 除算なし)。
  既存 `test_transition_crossing_on_grid_point` の 50% 端点一致ロジックと同型で担保。
- 🔵 **エッジ: 決定論**: 同一入力 2 回で `TransitionEstimate` が `==` (ビット同一)。onset レベル選択は決定的 (`test_transition_deterministic_bit_identical` 相当)。
- **参照した Edge ケース**: EDGE 系 (定数分率・点数不足の非例外化縮退, M2 契約)
- **参照した設計文書**: `docs/design/m3-operando/dataflow.md`、`src/tsumugin/sequential/thermal.py` L140-218、`tests/test_thermal.py`

## 5. EARS 要件・設計文書との対応関係

- **参照したユーザストーリー**: ストーリー 5.1「onset の誤読防止 (Issue #4)」— disappearing 相でも onset が「遷移開始側」を指す / Must Have
  (`docs/spec/m3-operando/user-stories.md` L109-110)
- **参照した機能要件**: REQ-021 (Issue #4、`docs/spec/m3-operando/requirements.md` L86-88)
- **参照した非機能要件**: REQ-404 (公開 API 非破壊)、NFR-102 (決定論)、P2 (非破壊性)
- **参照した Edge ケース**: 定数分率 → None、点数不足 → None、90% 未達 → onset None (非例外化縮退)
- **参照した受け入れ基準**:
  - TC-208-01 「appearing で onset(10%) < midpoint、disappearing で onset(90%) が**遷移開始側** — いずれも onset が遷移開始側」
    (`docs/spec/m3-operando/acceptance-criteria.md` L74-75)。※「> midpoint」表記は §⚠️ 前提の通り `< midpoint` へ差し戻し。
  - TC-208-02 「既存 thermal テストが (意味論修正後の期待値で) green」(同 L76)
- **参照した設計文書**:
  - **設計判断 (実装確定)**: `docs/design/m3-operando/design-interview.md` D-Q8 (L44-48)
  - **型/注記**: `docs/design/m3-operando/interfaces.py` L372-373 (「disappearing の onset = 90% 交差 (遷移開始側)。direction 不変」)
  - **インタビュー確定**: `docs/spec/m3-operando/interview-record.md` Q9 (L50-53、命名変更は API 破壊のため回避)
  - **既存実装**: `src/tsumugin/sequential/thermal.py` L29-32 (onset 定数)、L140-170 (`_interpolate_crossing`)、L173-218 (`estimate_transition`)
  - **既存テスト**: `tests/test_thermal.py` (18 件、direction 関連 L134/L155/L332/L351/L369)、`tests/test_m2_e2e.py` L403-424

## 6. 完了条件 (タスクファイル準拠)

- [ ] appearing: onset=10% 交差 < midpoint 🔵
- [ ] disappearing: onset=90% 交差 = 遷移開始側 (低温側)、`onset < midpoint` 🔵 *TC-208-01 (※不等号を差し戻し済み)*
- [ ] direction 別の onset/midpoint 順序をテストで固定 (disappearing の onset 検証を新規追加) 🔵 *REQ-021*
- [ ] 既存 thermal テストが修正後の期待値で green (期待値変更は理由コメント付き最小修正) 🔵 *TC-208-02*
- [ ] `uvx ruff check src tests` clean 🔵
- [ ] (コミット時) "Closes #4" — 本セッションでは commit しない 🔵

---

## 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (メカニズムは 90% 交差で確定、direction 判定・具体値は既存コード + 数値検証で確定)
- 入出力定義: 完全 (direction 別 onset レベル真理値表・具体温度値・None 縮退まで明示)
- 制約条件: 明確 (最小修正・API 非破壊・決定論・非有限漏洩なし・無退行)
- 実装可能性: 確実 (onset レベルの direction 依存化 1 点。既存 _interpolate_crossing を level 引数で再利用)
- 信頼性レベル: 🔵 が大多数 (REQ-021 / D-Q8 / interfaces.py L372-373 / interview Q9 に直接依拠)
- 特記: TASK-0024.md/TC-208-01 の「disappearing onset > midpoint」は 90% 交差メカニズムと矛盾するため
        数値検証に基づき「onset < midpoint (遷移開始側=低温側)」へ確定し、上流へ差し戻しを明記 (note §⚠️)。
```
