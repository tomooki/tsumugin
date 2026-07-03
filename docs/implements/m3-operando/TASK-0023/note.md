# TASK-0023 TDD 開発コンテキストノート

**タスク**: `_json.finite_or_none` 統合 — 3 実装 (tree/webui/serialization) を単一情報源へ集約 (Issue #5)
**要件名**: m3-operando / **タスクID**: TASK-0023 / **タイプ**: TDD / **推定 2h**
**フェーズ**: Phase 1 (技術負債+モデル) / **信頼性**: 🔵 4/4 (Issue #5 / 設計 D-Q9 / REQ-022)
**作成日時**: 2026-07-03 / **ブランチ**: milestone/m3-operando

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

`src/tsumugin/_json.py` を**新規作成**し、公開名 `finite_or_none(value) -> float | None` を単一実装として置く。
インフ/NaN/None → None、有限値は `float` を返す純関数。以下 3 箇所の重複実装を**委譲へ統合**する:

1. `src/tsumugin/search/tree.py` L181 `_finite_or_none` (定義元) — **センチネル判定 (`>= _EVIDENCE_SENTINEL`) は tree 側に残す**
2. `src/tsumugin/webui/app.py` L27 — `from ..search.tree import _finite_or_none` の**私的横断 import (レイヤ逆依存の温床)**
3. `src/tsumugin/store/serialization.py` L21 `_finite_or_none` (ローカル定義)

**🚨 絶対制約 (完了条件と直結)**:
- **挙動不変リファクタ** — 既存 **433 テスト (430 passed / 3 skipped)** を**無改変で green** に保つことが絶対条件 🔵
- **`_json.finite_or_none` が単一実装** (inf/NaN/None → None、有限は `float`) 🔵
- **tree.py / webui/app.py / serialization.py が委譲** — ただし **tree のセンチネル閾値判定は tree 内に残す** (センチネルは探索固有) 🔵 *D-Q9 / interview Q10*
- **レイヤ制約厳守**: `_json.py` は**無依存の葉モジュール** (標準ライブラリ `math` のみ)。全層が下向き import する。store 最下層から search への逆依存を解消する 🔵 *D-Q9*
- **公開 API 非破壊 (REQ-404)**: `__init__.py::__all__` (52 件・昇順) を壊さない。`finite_or_none` の `__all__` 追加は本タスクでは**任意** (内部ユーティリティ。追加するなら末尾 + 昇順維持)
- **git commit しない** (本セッションはユーザー判断)。**質問しない** (自律実行)。

**参照元**: `docs/tasks/m3-operando/TASK-0023.md`, `docs/design/m3-operando/design-interview.md` D-Q9,
`docs/spec/m3-operando/interview-record.md` Q10, `docs/spec/m3-operando/requirements.md` REQ-022,
`docs/spec/m3-operando/acceptance-criteria.md` TC-208-03

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling ビルド)。本タスクは**標準ライブラリ (`math`) のみ**で完結し、
  numpy にも GSAS-II にも依存しない純データ変換ユーティリティ。
- **アーキテクチャパターン**: レイヤ分離 (Interfaces / Agent / Orchestrator / Workers / Data)。
  `_json.py` は**ルート直下の無依存な葉モジュール**として全層の下向き依存先になる (逆依存回避)。
- **モジュール配置**: `src/tsumugin/_json.py` (新規)。現状 `search/tree.py`・`store/serialization.py`・
  `webui/app.py`・`sequential/trajectory.py` に同思想の非有限純化が散在。
- **参照元**: `docs/spec/m3-operando/note.md` (技術スタック節), `pyproject.toml`, `CLAUDE.md`

## 2. 開発ルール

- **TDD 厳守**: Red → Green → Refactor。テストなしの実装コミット禁止。
- **命名規則**: 関数 snake_case、定数 UPPER_SNAKE。公開名は `finite_or_none` (先頭アンダースコアなし)。
- **型チェック**: 型注釈必須 (`float | None`)。`any` 回避。
- **docstring**: 日本語可。FR/NFR/REQ 番号を紐づける慣習。信頼性レベル 🔵🟡🔴 表記。
- **フォーマット/Lint**: `uvx ruff check src tests` (line-length 100, target py312)。
- **非破壊追加**: frozen dataclass の新フィールドは末尾・既定値付き (本タスクは dataclass 変更なし)。
- **タスク毎コミット**: 完了 (テスト green + ruff clean) ごとに 1 コミット。**本セッションでは commit 禁止**。
  Issue #5 は該当コミットに "Closes #5" を含める (コミット自体は本タスク外)。
- **参照元**: `CLAUDE.md`, `docs/spec/m3-operando/note.md` (開発ルール節), `docs/tasks/m3-operando/overview.md`

## 3. 関連実装

### 統合対象の 3 実装 (挙動を厳密に読み取ること)

- **`src/tsumugin/search/tree.py`** (定義元・**センチネルは残す**):
  - L177-178: `_EVIDENCE_SENTINEL = 1e18` (有限 BIC を確実に上回る大きな有限センチネル)。
  - L181-192: `_finite_or_none(value: float) -> float | None`:
    ```python
    v = float(value)
    if not math.isfinite(v) or v >= _EVIDENCE_SENTINEL:
        return None
    return v
    ```
    → **非有限判定 (`not math.isfinite`) は `_json.finite_or_none` へ委譲**、**センチネル判定 (`>= _EVIDENCE_SENTINEL`) は tree 内に残す**
    のが D-Q9 の確定方針。統合後の tree 側は例えば
    `v = finite_or_none(value); if v is None or v >= _EVIDENCE_SENTINEL: return None; return v` の形。
  - 使用箇所: `to_summary()` L150/151/155 (rwp/gof/evidence.value の JSON 純化)。`_EVIDENCE_SENTINEL` は
    `_FiniteGuardedEvidence._SENTINEL` (L208) とも共有 → **センチネル定数と判定は tree に残す必要がある** (探索内部の softmax NaN ガードと同一値契約)。

- **`src/tsumugin/webui/app.py`** (私的横断 import の解消):
  - L27: `from ..search.tree import _finite_or_none` → **`from .._json import finite_or_none` へ置換** (レイヤ逆依存の温床を除去)。
  - webui は evidence センチネル純化を **to_summary() 経由で受ける**ため、app.py 側は素の非有限純化 (`finite_or_none`) で足りるか要確認
    (detail API `/api/hypotheses/{id}` の evidence 表現が to_summary と一致する契約: `tests/test_webui.py` L429)。

- **`src/tsumugin/store/serialization.py`** (ローカル定義の解消):
  - L21-32: `_finite_or_none(value: float | None) -> float | None` (**`None` 入力を許容**し `None` を返す点が tree 版と異なる)。
    ```python
    if value is None:
        return None
    v = float(value)
    return v if math.isfinite(v) else None
    ```
    → **統合先 `finite_or_none` は `None` 入力を許容する仕様** (`float | None -> float | None`) に揃えるのが安全 (serialization は `None` を渡す)。
  - 使用箇所多数: `phase_to_dict` (lattice a/b/c/角/scale/wt_frac/confidence)、`_finite_map` (L41 内包で各値を純化)。

### 統合対象外だが同思想 (要注意・**触らない**)

- **`src/tsumugin/sequential/trajectory.py`** L183-197 `_num_cell(value) -> str`:
  非有限/None → **空文字列 `""`** を返す **CSV セル用** (戻り値 `str`)。**シグネチャが異なる** (`-> str` vs `-> float | None`) ため
  TASK-0023 の統合対象**ではない** (タスク概要は tree/webui/serialization の 3 実装のみを明示)。**本タスクでは無改変**。

**参照元**: `src/tsumugin/search/tree.py`, `src/tsumugin/webui/app.py`, `src/tsumugin/store/serialization.py`,
`src/tsumugin/sequential/trajectory.py`

## 4. 設計文書

- **D-Q9 (Issue #5 の依存方向・確定)** — `docs/design/m3-operando/design-interview.md` L50-53:
  > `tsumugin/_json.py` (無依存の葉モジュール) に `finite_or_none` を置き、tree.py (センチネル判定は tree 内に残す)・
  > webui/app.py・store/serialization.py が import。**根拠**: store 最下層から search への逆依存回避 🔵。
- **Q10 (Issue #5 の共有先・確定)** — `docs/spec/m3-operando/interview-record.md` L55-58:
  > `src/tsumugin/_json.py` に `finite_or_none` (公開名) を新設し、tree.py / webui / serialization から利用。
  > tree.py のセンチネル対応は tree 側に残す (センチネルは探索固有)。
- **REQ-022 (Issue #5)** — `docs/spec/m3-operando/requirements.md` L89-90:
  > `_finite_or_none` は共有ユーティリティ `tsumugin/_json.py` へ統合し、tree.py / webui / serialization の 3 実装を
  > 単一情報源にしなければならない (**挙動不変**) 🔵。
- **ユーザストーリー 5.2 (JSON 純化の単一情報源化)** — `docs/spec/m3-operando/user-stories.md` L112-113:
  finite_or_none の 3 重実装を `_json.py` に統合 / 優先度 Should Have。
- **公開 API**: `src/tsumugin/__init__.py::__all__` (52 件・アルファベット昇順、`test_m1/m2_symbols_in_dunder_all_and_sorted` が昇順固定)。
- **参照元**: `docs/design/m3-operando/design-interview.md`, `docs/spec/m3-operando/{interview-record,requirements,user-stories}.md`,
  `src/tsumugin/__init__.py`

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov (+ httpx, dev グループ)。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **コマンド**: `uv run pytest` (既定) / `uv run pytest --cov=tsumugin` / `uv run pytest -m gsas` (GSAS-II 契約)。
  **依存導入は `uv sync --extra gsas`** (プレーン `uv sync` は gsas extra が外れるため禁止)。Web は `--extra web` 併用。
- **ベースライン**: **430 passed / 3 skipped** (GSAS-II 導入済み。3 skip は未導入環境用 gsas マーカー分)。この 433 件を**無改変で維持**。
- **テストディレクトリ**: `tests/` (実装ファイルと 1:1、計 29 ファイル)。命名は `test_{module}.py`。
- **新規テストファイル**: `tests/test_json.py` (新設) を想定 — `finite_or_none` の単体テスト数件。
- **既存の挙動契約テスト (無改変で通ること)**:
  - `tests/test_serialization.py`: E-01 (scale=inf → None + JSON), E-02 (lattice.a=nan / sigma inf → None),
    E-03 (wt_frac=inf / occupancy=nan / confidence=nan → None), B-06 (有限端点 0.0/1.0 保持), N-03 (`json.dumps(allow_nan=False)` 成功)。
  - `tests/test_webui.py`: `test_summary_with_infinite_metrics_is_strict_json` (chi2=inf → null),
    `test_api_result_with_infinite_metrics_returns_null`, `test_detail_and_summary_evidence_representation_is_consistent`
    (detail と summary の evidence 表現一致 = **センチネル純化の tree 残置が効く箇所**)。
  - `tests/test_tree_search.py`: to_summary の JSON 直列化・ランキング決定論 (センチネル経路含む)。
- **参照元**: `pyproject.toml`, `tests/test_serialization.py`, `tests/test_webui.py`, `tests/test_tree_search.py`

## 6. 注意事項

### 技術的制約
- **挙動不変が最優先**: リファクタであり機能追加ではない。3 実装の**現行挙動を 1 mm も変えない**こと。
  特に serialization 版は `None` 入力を許容し `None` を返す → **統合先 `finite_or_none` は `float | None` を受け `float | None` を返す**契約に揃える
  (tree 版は `float` のみ受けるが、`None` を渡さないので上位互換で問題なし)。
- **センチネルは tree 固有**: `_EVIDENCE_SENTINEL = 1e18` と `>= _EVIDENCE_SENTINEL` 判定は探索の softmax NaN ガード
  (`_FiniteGuardedEvidence`) と対を成す**探索内部契約**。`_json.finite_or_none` に持ち込まず tree 側へ残す (D-Q9 明記)。
  webui/serialization はセンチネルを扱わないため、素の `finite_or_none` を使う。
- **レイヤ逆依存の解消が本質**: 現状 webui → search/tree の私的 import と、store が最下層でありながら
  search の同名関数と挙動を暗黙共有している状態を、`_json.py` (葉) への一方向下向き依存へ正す。
- **標準ライブラリのみ**: `_json.py` は `math` のみ import。numpy / GSAS-II / 上位レイヤを一切 import しない。

### セキュリティ・非破壊性
- 純関数のみ。副作用なし・決定論 (NFR-102)。既存 model / store / search の公開 API は無改変 (削除・上書き API を足さない, P2)。

### パフォーマンス
- ホットパスではない (JSON 配信時の値純化)。性能要件なし。可読性・単一情報源を優先。

- **参照元**: `docs/tasks/m3-operando/TASK-0023.md`, `docs/spec/m3-operando/note.md` (注意事項節),
  `docs/design/m3-operando/design-interview.md` D-Q9, `CLAUDE.md`
