# TASK-0023 要件定義: `_json.finite_or_none` 統合 (Issue #5)

**機能名**: json-finite-or-none / **タスクID**: TASK-0023 / **要件名**: m3-operando
**タイプ**: TDD (挙動不変リファクタ) / **信頼性**: 🔵 (Issue #5 / REQ-022 / D-Q9 / TC-208-03)

> すべてのパスはプロジェクトルートからの相対パス。

---

## 1. 機能の概要（EARS 要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: JSON 配信・直列化のために数値を純化する共有ユーティリティ関数 `finite_or_none` を
  `src/tsumugin/_json.py` (無依存の葉モジュール) に**単一実装**として新設する。非有限値 (`inf` / `-inf` / `NaN`) と
  `None` を `None` へ写像し、有限値は `float` として返す。
- 🔵 **どのような問題を解決するか**: 現在 `_finite_or_none` 相当のロジックが **3 箇所に重複**している
  (`search/tree.py` L181 定義、`webui/app.py` L27 が private を横断 import、`store/serialization.py` L21 ローカル定義)。
  webui → search/tree の**私的横断 import** と、store 最下層が search と挙動を暗黙共有する状態を、`_json.py` (葉) への
  **一方向・下向き依存**へ正すことで、**レイヤ逆依存を解消し単一情報源化**する。
- 🔵 **想定されるユーザー**: 本関数の直接利用者は tsumugin 内部の配信/直列化層 (開発者)。エンドユーザーへの
  挙動変化は**一切ない** (挙動不変リファクタ)。
- 🔵 **システム内での位置づけ**: `src/tsumugin/_json.py` はルート直下の**無依存な葉モジュール** (標準ライブラリ `math` のみ)。
  上位レイヤ (search / refinement / webui / store) はすべてこれを下向きに import する。**探索固有のセンチネル処理
  (`_EVIDENCE_SENTINEL = 1e18` 以上を None 化) は `search/tree.py` 側に残す** (D-Q9 明記)。
- **参照した EARS 要件**: REQ-022 (Issue #5)
- **参照した設計文書**: `docs/design/m3-operando/design-interview.md` D-Q9、
  `docs/design/m3-operando/interfaces.py` L24-32 (`finite_or_none` 署名)、`docs/spec/m3-operando/interview-record.md` Q10

## 2. 入力・出力の仕様（EARS 機能要件・型定義ベース）

- 🔵 **関数署名** (設計 `interfaces.py` L29 に一致):
  ```python
  def finite_or_none(value: float | None) -> float | None: ...
  ```
- 🔵 **入力パラメータ**:
  - `value: float | None` — 純化対象の数値。`float` (有限・非有限いずれも)、`int` (float 化される)、または `None`。
  - 制約: 数値または `None`。`float(value)` で変換可能であること (非数値型は責務外。既存呼び出し元は数値/None のみ渡す)。
- 🔵 **出力値**:
  - `float | None`。
  - `value` が `None` → `None`。
  - `value` が非有限 (`inf` / `-inf` / `NaN`) → `None`。
  - `value` が有限 → `float(value)` (元値を float 化して返す。`0.0`・負値・極小/極大有限値もそのまま保持)。
- 🔵 **入出力の関係性 (真理値表)**:
  | 入力 `value` | 出力 |
  |---|---|
  | `None` | `None` |
  | `float("inf")` / `float("-inf")` | `None` |
  | `float("nan")` | `None` |
  | `0.0` | `0.0` |
  | `1.0` / `-3.5` / `1e17` | 同値 (`float`) |
  | `5` (int) | `5.0` (float) |
- 🔵 **委譲後の各利用側の期待**:
  - `store/serialization.py`: ローカル `_finite_or_none` を廃し `from .._json import finite_or_none` を利用
    (`None` 入力を渡すため `float | None` 受理が必須)。`_finite_map` / `phase_to_dict` の挙動は不変。
  - `webui/app.py`: L27 の `from ..search.tree import _finite_or_none` を `from .._json import finite_or_none` へ置換。
  - `search/tree.py`: 非有限判定を `finite_or_none` へ委譲しつつ、**センチネル判定 (`>= _EVIDENCE_SENTINEL`) を残す**。
    例: `v = finite_or_none(value); return None if (v is None or v >= _EVIDENCE_SENTINEL) else v`。
- **参照した EARS 要件**: REQ-022
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py` L24-32

## 3. 制約条件（EARS 非機能要件・アーキテクチャ設計ベース）

- 🔵 **挙動不変 (最重要)**: 本タスクは**リファクタ**であり機能追加ではない。3 実装の現行挙動を変えず、
  **既存 433 テスト (430 passed / 3 skipped) を無改変で green** に保つことが完了の絶対条件 (TC-208-03)。
- 🔵 **レイヤ制約**: `_json.py` は**標準ライブラリ `math` のみ** import。numpy / GSAS-II / 上位レイヤ (search/webui/store/…)
  を一切 import しない**無依存の葉モジュール**。全層が下向きに依存する (D-Q9)。
- 🔵 **センチネルの局所性**: `_EVIDENCE_SENTINEL = 1e18` とセンチネル閾値判定は探索の softmax NaN ガード
  (`_FiniteGuardedEvidence`) と対を成す**探索固有契約**。`_json.finite_or_none` に持ち込まず `search/tree.py` に残す。
- 🔵 **決定論 / 純関数 (NFR-102)**: 副作用なし・入力非破壊・同一入力で同一出力。乱数不使用。
- 🔵 **非破壊性 (P2 / NFR-101)**: 既存 model / store / search / webui の公開 API を無改変。削除・上書き API を足さない。
- 🟡 **公開 API (REQ-404)**: `src/tsumugin/__init__.py::__all__` (52 件・昇順) を壊さない。`finite_or_none` の `__all__`
  への追加は**本タスクでは任意** (内部ユーティリティ)。追加する場合は末尾 + 昇順維持 + 昇順検証テストを green に保つ。
- 🔵 **フォーマット/Lint**: `uvx ruff check src tests` clean (line-length 100, target py312)。
- 🟢/制約 **git commit しない** (本セッションはユーザー判断)。**質問しない** (自律実行)。
- **参照した EARS 要件**: REQ-022, REQ-404, NFR-101, NFR-102
- **参照した設計文書**: `docs/design/m3-operando/design-interview.md` D-Q9、`docs/spec/m3-operando/note.md` (制約節)、`CLAUDE.md`

## 4. 想定される使用例（Edge ケース・データフローベース）

- 🔵 **基本パターン (serialization)**: `phase_to_dict` が `scale=inf` の相を直列化 → `finite_or_none(inf)` が `None` →
  `json.dumps(d, allow_nan=False)` が例外なく成功 (`tests/test_serialization.py` E-01 相当)。
- 🔵 **基本パターン (webui/tree)**: `to_summary()` が `rwp=inf` (EDGE-004 の正常経路 chi2=inf に由来) を配信 →
  `finite_or_none(inf)` が `None` → API JSON が `null` を返す (`tests/test_webui.py` の inf 系テスト相当)。
- 🔵 **エッジ: None 入力**: serialization は `None` を渡しうる → `finite_or_none(None)` は `None` (現行 serialization 版の挙動を保存)。
- 🔵 **エッジ: 有限端点 0.0**: `finite_or_none(0.0)` は `0.0` (falsy な有限値を None に潰さない。serialization B-06 相当)。
- 🔵 **エッジ: NaN in Mapping**: `_finite_map` が `sigma["a"]=inf` / `occupancy=nan` を各値純化 → 各々 `None`
  (`tests/test_serialization.py` E-02/E-03 相当)。
- 🔵 **エッジ: センチネル (tree のみ)**: 探索内部で evidence が `_EVIDENCE_SENTINEL` (1e18) 以上 → tree 側の残置判定で `None`。
  `finite_or_none` 単体はセンチネルを知らない (有限なのでそのまま返す) が、tree のラッパが None 化する
  (detail と summary の evidence 表現一致: `tests/test_webui.py::test_detail_and_summary_evidence_representation_is_consistent`)。
- 🔵 **統合対象外 (触らない)**: `sequential/trajectory.py::_num_cell` は戻り値が `str` (CSV セル用に `""` を返す) でシグネチャが異なるため
  本タスクの統合対象外。無改変。
- **参照した Edge ケース**: EDGE-004 (chi2=inf を非例外化・正常経路)
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py`、`docs/spec/m3-operando/acceptance-criteria.md` TC-208-03

## 5. EARS 要件・設計文書との対応関係

- **参照したユーザストーリー**: ストーリー 5.2「JSON 純化の単一情報源化 (Issue #5)」(`docs/spec/m3-operando/user-stories.md` L112-113)
- **参照した機能要件**: REQ-022 (`docs/spec/m3-operando/requirements.md` L89-90)
- **参照した非機能要件**: REQ-404 (公開 API 非破壊)、NFR-101 (非破壊性)、NFR-102 (決定論)
- **参照した Edge ケース**: EDGE-004 (chi2=inf 非例外化、`search/tree.py` docstring)
- **参照した受け入れ基準**: TC-208-03 「finite_or_none が `_json.py` 単一実装になり、tree/webui/serialization が委譲
  (挙動不変・全テスト無退行)」(`docs/spec/m3-operando/acceptance-criteria.md` L77)
- **参照した設計文書**:
  - **アーキテクチャ / 依存方向**: `docs/design/m3-operando/design-interview.md` D-Q9 (L50-53)
  - **型定義**: `docs/design/m3-operando/interfaces.py` L24-32 (`finite_or_none(value: float | None) -> float | None`)
  - **インタビュー確定**: `docs/spec/m3-operando/interview-record.md` Q10 (L55-58)
  - **既存実装**: `src/tsumugin/search/tree.py` L177-192、`src/tsumugin/webui/app.py` L27、`src/tsumugin/store/serialization.py` L21-32

## 6. 完了条件 (タスクファイル準拠)

- [ ] `_json.finite_or_none` が単一実装 (inf/NaN/None → None、有限は float) 🔵
- [ ] tree.py / webui/app.py / serialization.py が委譲 (tree のセンチネル閾値は tree 内) 🔵
- [ ] 既存全テスト無改変 green (433 件) + 新規単体テスト (数件) 🔵
- [ ] `uvx ruff check src tests` clean 🔵
- [ ] (コミット時) "Closes #5" — 本セッションでは commit しない 🔵

---

## 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (署名は interfaces.py L29 で確定、挙動は 3 実装の現行コードで確定)
- 入出力定義: 完全 (真理値表・型・None/有限端点まで明示)
- 制約条件: 明確 (挙動不変・レイヤ制約・センチネル局所性・決定論)
- 実装可能性: 確実 (標準ライブラリのみの純関数抽出 + 3 箇所の委譲差し替え)
- 信頼性レベル: 🔵 が大多数 (REQ-022 / D-Q9 / interfaces.py / TC-208-03 に直接依拠)
```
