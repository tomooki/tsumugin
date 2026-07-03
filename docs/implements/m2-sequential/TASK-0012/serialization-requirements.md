# TASK-0012 store/serialization TDD要件定義書

**機能名**: store/serialization — PhaseInstance の dict 相互変換 (`phase_to_dict` / `phase_from_dict`)
**タスクID**: TASK-0012
**要件名**: m2-sequential
**タスクタイプ**: TDD / **推定工数**: 3h / **フェーズ**: Phase 1 - モデル/永続化基盤
**作成日**: 2026-07-03
**出力ファイル**: `docs/implements/m2-sequential/TASK-0012/serialization-requirements.md`

**【信頼性レベル凡例】**:
- 🔵 **青信号**: EARS要件定義書・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: EARS要件定義書・設計文書から妥当な推測
- 🔴 **赤信号**: EARS要件定義書・設計文書にない推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: M2 永続化基盤の最下層として、相インスタンス `PhaseInstance` と「`json.dumps` 可能な素の dict」の間を相互変換する 2 つの純関数 `phase_to_dict` / `phase_from_dict` を新設する。lattice / sigma / occupancies / scale / wt_frac / lifecycle を含む**完全 roundtrip** (`phase_from_dict(phase_to_dict(p)) == p`) を保証する。
- 🔵 **どのような問題を解決するか**: 現行の `Ledger` / `SnapshotStore` はインメモリの `list` のみで、プロセス再起動をまたいだ永続化ができない。永続化 (JSONL) を実装するには、frozen dataclass の相を JSON ネイティブ型へ落とし、再構築する単一情報源が必要。本タスクはその**シリアライズ基盤**を先行実装し、PersistentLedger / PersistentSnapshotStore (TASK-0014) と将来の Project Store (M3+) が共有する。
- 🔵 **想定されるユーザー**: 直接のユーザーは後続タスク (TASK-0014 の永続化ストア、M3+ の Project Store) の実装コード。研究者は永続化された解析結果を再オープンする経路で間接的に依存する。本関数自体は内部データ変換層であり外部 UI を持たない。
- 🔵 **システム内での位置づけ**: `src/tsumugin/store/` レイヤ (永続化基盤、最下層) の純関数モジュール `serialization.py`。上位レイヤ (search / refinement / evidence) には**依存してはならない** (レイヤ逆依存の禁止)。標準ライブラリ (`json` / `math` / `dataclasses`) のみで完結し、numpy・GSAS-II・Protocol に依存しない。
- **参照したEARS要件**: REQ-010 / REQ-011 / REQ-012 (永続化・in-memory 同一 IF の土台)、REQ-402 (決定論)
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` L256-292 (`store/serialization.py` セクション、`phase_to_dict` / `phase_from_dict` 署名)、`docs/design/m2-sequential/design-interview.md` D-Q5 (独立モジュール・単一情報源の設計判断)

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 phase_to_dict（新設 / `src/tsumugin/store/serialization.py`）🔵

- 🔵 **署名**: `phase_to_dict(phase: PhaseInstance) -> dict[str, Any]`
- 🔵 **入力**: `PhaseInstance(phase_ref, lattice, scale=1.0, wt_frac=None, occupancies={}, lifecycle=None)` (TASK-0011 拡張済みモデル)。
- 🟡 **出力 dict スキーマ** (キー名・ネスト構造は interfaces.py 契約に沿って本タスクで確定・固定):
  ```
  {
    "phase_ref": str,
    "lattice": {
      "a": float|None, "b": float|None, "c": float|None,
      "alpha": float|None, "beta": float|None, "gamma": float|None,
      "sigma": { str: float|None, ... }        # 空なら {}
    },
    "scale": float|None,
    "wt_frac": float|None,                      # None はそのまま None
    "occupancies": { str: float|None, ... },    # 空なら {}
    "lifecycle": null | {
      "birth_frame": int|None,
      "death_frame": int|None,
      "confidence": float|None
    }
  }
  ```
- 🟡 **出力の型制約**: 値は **JSON ネイティブ型のみ** (`str` / `int` / `float` / `bool` / `None` / それらの `dict`)。`tuple`・dataclass・numpy スカラを残さない (`occupancies`/`sigma` は `dict(mapping)` で素の dict へコピー)。
- 🟡 **非有限値の純化 (M1 教訓)**: `float` フィールド (scale / lattice の a〜gamma / sigma 値 / occupancies 値 / confidence / wt_frac) のうち `math.isfinite` が False (inf / -inf / NaN) のものは **`None` へ写像**する。これにより出力 dict は `json.dumps(d, allow_nan=False)` 可能となる。
- 🔵 **副作用なし・決定論**: 入力を変更しない純関数。同一入力に対し常に等価 dict を返す。
- 🟡 **例**: `phase_to_dict(PhaseInstance("A", LatticeParams(5,5,5), scale=1.2, wt_frac=0.3))` →
  `{"phase_ref":"A","lattice":{"a":5.0,"b":5.0,"c":5.0,"alpha":90.0,"beta":90.0,"gamma":90.0,"sigma":{}},"scale":1.2,"wt_frac":0.3,"occupancies":{},"lifecycle":null}`

### 2.2 phase_from_dict（新設 / `src/tsumugin/store/serialization.py`）🔵

- 🔵 **署名**: `phase_from_dict(data: Mapping[str, Any]) -> PhaseInstance`
- 🔵 **入力**: `phase_to_dict` が生成した (または後続スキーマの) Mapping。
- 🔵 **出力**: 復元された `PhaseInstance` (frozen dataclass)。ネストされた `lattice` / `lifecycle` も `LatticeParams` / `PhaseLifecycle` として再構築する。
- 🟡 **未知キー無視 (前方互換)**: `data` に定義外のキー (例: 将来追加される `"provenance"`) があっても**無視**する。実装は `**data` 展開ではなく**明示キーの取り出し** (`data["phase_ref"]` / `data.get("scale", 1.0)` 等) による。
- 🟡 **欠損 optional キー補完 (後方互換)**: `scale` 欠落 → `1.0`、`wt_frac` 欠落 → `None`、`occupancies` 欠落 → `{}`、`lifecycle` 欠落または `None` → `None`、`sigma` 欠落 → `{}`、lattice の角欠落 → 既定 90.0。`phase_ref` / `lattice` は必須。
- 🔵 **roundtrip 保証**: 有限値のみの `PhaseInstance` について `phase_from_dict(phase_to_dict(p)) == p` (frozen dataclass の構造的 `==`)。
- 🟡 **非有限入力時の頑健性**: `None` を受けても壊れない (例: 非有限で `None` 化された `scale` → 既定 1.0 へフォールバック)。非有限入力は「精密化失敗の縮退状態」であり、**roundtrip 値保存は非有限では保証しない** (§3 参照)。
- 🟡 **例**: `phase_from_dict({"phase_ref":"A","lattice":{"a":5.0,"b":5.0,"c":5.0},"future_field":123})` → `PhaseInstance("A", LatticeParams(5,5,5))` (未知キー `future_field` 無視、欠損キーは既定)。

- **参照したEARS要件**: REQ-010 / REQ-011 / REQ-012、REQ-402
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` L261-262、既存実装 `src/tsumugin/model/phase.py` (LatticeParams / PhaseLifecycle / PhaseInstance)、`src/tsumugin/search/tree.py` L181-192 (`_finite_or_none` 非有限契約)

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🟡 **JSON 安全性 (完了条件③ / M1 レビュー教訓 / TC-104-03)**: `phase_to_dict` の出力は `json.dumps(d, allow_nan=False)` が**例外を出さず**成功しなければならない。非有限 float (inf / NaN) は `None` へ写像する。`allow_nan=False` は inf/NaN で `ValueError` を出すため、この設定での成功が JSON 純度の検証手段。
- 🔵 **完全 roundtrip 等価 (完了条件① / `==` 比較)**: 全フィールド (finite 値) を持つ `PhaseInstance` が `phase_from_dict(phase_to_dict(p)) == p`。
- 🔵 **縮退 roundtrip (完了条件②)**: `lifecycle=None` / `sigma={}` / `occupancies={}` の最小相でも roundtrip 等価。
- 🟡 **前方互換 (完了条件④)**: `phase_from_dict` は未知キーを無視。スキーマ進化 (キー追加) に対して壊れない。
- 🔵 **非破壊性 (P2 / NFR-101 / NFR-105)**: 既存 model / store の API を無改変。`Ledger` / `SnapshotStore` へ削除・上書き API を足さない。本タスクは純関数追加のみ。
- 🔵 **決定論 (NFR-102 / REQ-402 / REQ-403)**: 乱数不使用。同一入力に対し常に等価 dict。辞書順差は `ledger.py::_canonical_json(sort_keys=True)` が吸収するため、`phase_to_dict` の出力を `_canonical_json` に渡した文字列は決定論的。
- 🔵 **レイヤ制約 (アーキテクチャ)**: `store/` は最下層。上位の `search/tree.py::_finite_or_none` を **import しない** (逆依存回避)。非有限判定は `serialization.py` にローカル `_finite_or_none` を定義する (センチネル `_EVIDENCE_SENTINEL` は evidence 固有のため不要、単純な `math.isfinite` 判定)。
- 🔵 **スコープ境界**: 本タスクは phase 単体の 2 関数のみ。JSONL ファイル I/O・ハッシュチェーン永続化・`PersistentLedger`/`PersistentSnapshotStore` は TASK-0014。`_canonical_json` の公開昇格は本タスクでは任意 (D-Q5)。
- 🔵 **型注釈必須**: `dict[str, Any]` / `Mapping[str, Any]` を正しく付す。`from __future__ import annotations` を付す。`any` 回避。
- 🔵 **命名規則 / Lint**: 関数 snake_case、内部ヘルパは `_` 接頭辞。`uvx ruff check src tests` (line-length 100, target py312) 準拠。
- 🔴 **git commit しない** (ユーザー判断。本セッション制約)。**質問しない** (自律実行)。

- **参照したEARS要件**: REQ-010 / REQ-011 / REQ-012、NFR-101、NFR-102 (決定論)、NFR-105、REQ-402、REQ-403
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` (L256-292)、`docs/design/m2-sequential/design-interview.md` (D-Q5)、`docs/spec/m2-sequential/note.md` (非破壊/レイヤ制約節)、`docs/spec/m2-sequential/acceptance-criteria.md` (TC-104-03)、`CLAUDE.md` (不変条件)

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本的な使用パターン 🔵

- **完全直列化**: 逐次精密化で確定した相 `PhaseInstance("A", LatticeParams(5.01,5.01,5.01,sigma={"a":0.002}), scale=1.2, wt_frac=0.35, occupancies={"Fe":0.98}, lifecycle=PhaseLifecycle(birth_frame=10))` → `phase_to_dict` で素の dict → JSONL 1 行 (TASK-0014) → 再オープン時 `phase_from_dict` で復元。
- **スナップショット直列化**: `SnapshotStore.save(phases, ...)` の phases (tuple) を、各要素へ `phase_to_dict` を適用して永続化 (TASK-0014 が本 2 関数を利用)。
- **決定論的ハッシュ**: `phase_to_dict` の出力 dict を `ledger.py::_canonical_json` に渡してハッシュチェーンの payload とする (素の型のみのため通る)。

### 4.2 データフロー 🔵

- 直列化: `PhaseInstance` → `phase_to_dict` → JSON-safe dict → (`_canonical_json` / `json.dumps`) → JSONL 永続化 (TASK-0014)。
- 復元: JSONL 行 → `json.loads` → Mapping → `phase_from_dict` → `PhaseInstance` → SnapshotStore/エンジンへ供給。

### 4.3 エッジケース 🔵🟡

- 🟡 **EDGE (非有限, M1 教訓)**: 精密化失敗などで `scale=inf` / `lattice.a=nan` / `sigma` 値 `inf` / `wt_frac=inf` / `confidence=nan` を持つ相 → `phase_to_dict` が該当値を `None` へ写像 → `json.dumps(allow_nan=False)` 成功。roundtrip 値保存は非有限では保証しない (JSON 安全性のみ保証)。
- 🔵 **縮退 (最小相)**: `PhaseInstance("x", LatticeParams(5,5,5))` (lifecycle=None / sigma={} / occupancies={} / wt_frac=None) → roundtrip 等価。
- 🟡 **未知キー (前方互換)**: 将来スキーマで追加されたキーを含む dict → `phase_from_dict` が無視して既知フィールドのみで復元。
- 🟡 **欠損 optional キー (後方互換)**: 旧スキーマ由来で `lifecycle` / `occupancies` / `wt_frac` を欠く dict → 既定 (None / {} / None) で補完。
- 🔵 **境界値保持**: `confidence` の端点 (0.0 / 1.0)、lifecycle 部分指定 (birth_frame のみ, death=None)、lattice 既定角 (90.0) が roundtrip で保持される。

### 4.4 エラーケース 🔵🟡

- 🟡 **非有限は例外にしない**: 非有限値は `None` へ縮退させ、`ValueError` 等を送出しない (P5 縮退規約と同精神。M1 の `_finite_or_none` に倣う)。
- 🔵 **必須キー欠落 (契約違反)**: `phase_ref` / `lattice` を欠く不正 dict は roundtrip の対象外 (`phase_to_dict` の出力には常に両者が含まれるため通常経路では発生しない)。実装は `data["phase_ref"]` の `KeyError` に委ねてよい (本タスクでは頑健化を必須にしない — スコープ限定)。
- 🔴 **注意 (非スコープ)**: `confidence` の範囲 [0,1] 検証や `wt_frac` の [0,1] 検証は本タスクでは行わない (器のシリアライズのみ。検証は算出側スコープ)。

- **参照したEARS要件**: REQ-010 / REQ-011 / REQ-012、REQ-402
- **参照した設計文書**: `docs/design/m2-sequential/dataflow.md`、`docs/design/m2-sequential/interfaces.py` (L256-292)、`docs/spec/m2-sequential/acceptance-criteria.md` (TC-104-03 / TC-106)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: m2-sequential 永続化・再現性 (プロセス再起動をまたぐ ledger/snapshot 復元, user-stories.md)
- **参照した機能要件**:
  - REQ-010 (Ledger を追記専用 JSONL へ永続化、再オープンで verify()=True + 追記可能)
  - REQ-011 (SnapshotStore を同様に永続化、再オープン後に任意 snapshot_id へ revert)
  - REQ-012 (永続化ストアは in-memory と同一 IF、既存エンジンに無改変注入)
  - → 本タスクは上記 3 要件が要求する**phase の JSON 相互変換基盤**を先行実装する位置づけ。
- **参照した非機能要件**: NFR-101 (追記/非破壊 P2)、NFR-102 / REQ-402 (決定論・ビット同一)、NFR-105 (ハッシュチェーン)、REQ-403 (性能・純関数で軽量)
- **参照したEdgeケース**: 非有限値の JSON 純化 (M1 レビュー教訓)、未知キー無視 (前方互換)、欠損キー補完 (後方互換)
- **参照した受け入れ基準** (`docs/spec/m2-sequential/acceptance-criteria.md`):
  - TC-104-03 (非有限値が漏れない、失敗フレームは空欄/None 表現) — 本タスクの「非有限 → None」と同根の契約
  - TC-106-01〜07 (PersistentLedger/Snapshot の roundtrip・revert 復元) — 本タスクの phase roundtrip の上に成立
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m2-sequential/architecture.md` (store 永続化基盤層、レイヤ分離)
  - **データフロー**: `docs/design/m2-sequential/dataflow.md` (直列化/復元パス)
  - **型定義**: `docs/design/m2-sequential/interfaces.py` L256-292 (`phase_to_dict` / `phase_from_dict` / PersistentLedger / PersistentSnapshotStore)
  - **設計ヒアリング**: `docs/design/m2-sequential/design-interview.md` D-Q5 (独立モジュール・単一情報源・`_canonical_json` 共有)
  - **既存実装**: `src/tsumugin/model/phase.py` (LatticeParams / PhaseLifecycle / PhaseInstance)、`src/tsumugin/store/{ledger,snapshot}.py`、`src/tsumugin/search/tree.py` (`_finite_or_none`)
  - **タスク定義**: `docs/tasks/m2-sequential/TASK-0012.md`
  - **コンテキストノート**: `docs/implements/m2-sequential/TASK-0012/note.md`

---

## 完了条件（タスク定義より）

- [ ] 全フィールド入り PhaseInstance の roundtrip 等価 (`==` 比較) 🔵
- [ ] lifecycle=None / sigma 空 / occupancies 空の縮退 roundtrip 🔵
- [ ] dict が `json.dumps(allow_nan=False)` 可能 (非有限値は None 化) 🟡 *M1 教訓*
- [ ] 未知キーを無視して前方互換 (from_dict) 🟡

## 信頼性レベルサマリー

- 🔵 青信号: 機能概要・システム内位置づけ・roundtrip/縮退の完了条件・レイヤ制約・非破壊性・決定論は interfaces.py / requirements.md / 既存実装に直接依拠。
- 🟡 黄信号: dict の具体スキーマ (キー名/ネスト)、非有限 → None の写像詳細、未知キー無視・欠損補完の実装方式は設計文書 (🟡 JSON 可換) からの妥当な具体化。
- 🔴 赤信号: git commit しない / 質問しない のセッション運用制約、confidence 範囲検証を非スコープとする旨のみ。
- **品質判定**: 高品質 — 要件の曖昧さなし / 入出力定義完全 (dict スキーマ確定) / 制約条件明確 / 実装可能性確実 (標準ライブラリのみ)。
