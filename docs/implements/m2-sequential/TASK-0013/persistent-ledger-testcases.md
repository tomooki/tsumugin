# TASK-0013 store/persistent — PersistentLedger TDDテストケース定義書

**機能名**: store/persistent — `PersistentLedger(path)`（JSONL 追記 + 再オープン検証）
**タスクID**: TASK-0013 / **要件名**: m2-sequential
**作成日**: 2026-07-03
**要件定義**: `docs/implements/m2-sequential/TASK-0013/persistent-ledger-requirements.md`
**出力ファイル**: `docs/implements/m2-sequential/TASK-0013/persistent-ledger-testcases.md`
**テスト対象実装**: `src/tsumugin/store/persistent.py`（新規）+ `src/tsumugin/errors.py`（`LedgerIntegrityError` 追記）
**テストファイル**: `tests/test_persistent_store.py`（新規。`tmp_path` 使用）

**【信頼性レベル凡例】**:
- 🔵 **青信号**: 要件定義・既存実装・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: 元の資料から妥当な推測
- 🔴 **赤信号**: 元の資料にない推測

---

## テストケース一覧サマリー

| 分類 | 件数 | テストID |
|---|---|---|
| 正常系 | 6 | N-01〜N-06 |
| 異常系 (破損検出・無修復) | 3 | E-01〜E-03 |
| 境界値 (API 不在・追記のみ・端点) | 5 | B-01〜B-05 |
| **合計** | **14** | |

**信頼性分布**: 🔵 11 / 🟡 3 / 🔴 0 — 品質評価: 高品質

**完了条件との対応**:
- 完了条件① append → 再オープン → verify() True + エントリ全量一致（TC-106-01）→ **N-01**
- 完了条件② 再オープン後の append でチェーン連結（TC-106-02）→ **N-02**
- 完了条件③ 1 行改竄 → LedgerIntegrityError + ファイル無変更（TC-106-04 / EDGE-003）→ **E-01 / E-02**
- 完了条件④ 削除・上書き API 不在 + 追記のみ（TC-106-05/07）→ **B-01 / B-02**
- 完了条件⑤ in-memory Ledger と同一 (kind, payload) 列で同一 hash 列（決定論）→ **N-03**

---

## 1. 正常系テストケース（基本的な動作）

### N-01: 永続追記 → 再オープン → verify() True + エントリ全量一致
- **何をテストするか**: `PersistentLedger` に複数 append し、別インスタンスで同一パスを再オープンすると
  `verify()` が True かつ `entries` が書き込み全量と一致すること。
- **期待される動作**: プロセス再起動相当（別インスタンス）でも永続化された監査ログが検証済みで完全復元される。
- **入力値**:
  ```python
  path = tmp_path / "ledger.jsonl"
  pl = PersistentLedger(path)
  e0 = pl.append("phase_accept", {"hyp": "hyp-0001", "rwp": 12.3})
  e1 = pl.append("snapshot_save", {"snapshot_id": "snap-0000", "n_phases": 2})
  pl2 = PersistentLedger(path)  # 再オープン
  ```
  - **入力データの意味**: 逐次解析で追記される代表的な監査エントリ 2 件。プロセス再起動をまたぐ永続化の主経路。
- **期待される結果**: `pl2.verify() is True`。`pl2.entries == pl.entries`（`index/kind/payload/prev_hash/hash` 全一致）。
  `[e.to_dict() for e in pl2.entries] == [e0.to_dict(), e1.to_dict()]`。
  - **期待結果の理由**: 完了条件①・TC-106-01。JSONL 行 → `LedgerEntry` 再構築 → 検証済み提供の契約（要件定義 2.1/2.3/2.4）。
- **テストの目的**: 永続 roundtrip + 再オープン検証の保証（機能の中核）。
  - **確認ポイント**: `entries` が `LedgerEntry` の不変タプルとして復元され、hash まで一致すること。
- 🔵 (要件定義 §2.1/2.4 完了条件① / TC-106-01 / ledger.py Ledger.verify)

### N-02: 再オープン後の append でハッシュチェーンが連結（index 連番継続・verify True）
- **何をテストするか**: 再オープンした `PersistentLedger` にさらに append すると、`index` が連番継続し
  `prev_hash` が直前 hash に連結し `verify()` が True を保つこと。
- **期待される動作**: 永続化された既存チェーンの末尾から途切れなく追記できる（REQ-010(b)）。
- **入力値**:
  ```python
  pl = PersistentLedger(path); pl.append("a", {"i": 0})
  pl2 = PersistentLedger(path)          # 再オープン (既存 1 件)
  e = pl2.append("b", {"i": 1})         # 追記
  ```
  - **入力データの意味**: 「再起動して続きから記録する」実運用シナリオ。
- **期待される結果**: `e.index == 1`。`e.prev_hash == pl2.entries[0].hash`。`pl2.verify() is True`。
  さらに `PersistentLedger(path).entries` の長さが 2 で `verify() is True`（3 回目のオープンでも一貫）。
  - **期待結果の理由**: 完了条件②・TC-106-02。`append` の `index=len(entries)` / `prev_hash=末尾.hash` 規約（要件定義 2.2）。
- **テストの目的**: 再オープン跨ぎのチェーン連結を確認。
  - **確認ポイント**: 連番・prev_hash 連結・verify() True の 3 点が同時に成り立つこと。
- 🔵 (要件定義 §2.2 完了条件② / TC-106-02)

### N-03: 決定論 — in-memory Ledger と同一 (kind, payload) 列で同一 hash 列
- **何をテストするか**: 同一の (kind, payload) 列を in-memory `Ledger` と `PersistentLedger` に流したとき、
  生成される hash 列が完全一致すること。
- **期待される動作**: `_compute_hash` / `_canonical_json` を共有するため両者の監査チェーンがビット同一になる。
- **入力値**:
  ```python
  ops = [("a", {"x": 1}), ("b", {"y": 2, "z": 3}), ("c", {})]
  mem = Ledger();            [mem.append(k, p) for k, p in ops]
  pl = PersistentLedger(path); [pl.append(k, p) for k, p in ops]
  ```
  - **入力データの意味**: NFR-102 / REQ-402 ビット同一・ハッシュチェーン共有の検証。キー順の異なる payload を含む。
- **期待される結果**: `[e.hash for e in pl.entries] == [e.hash for e in mem.entries]`。
  各 index の `prev_hash` も一致。
  - **期待結果の理由**: 完了条件⑤・NFR-102。`ledger.py` の `_compute_hash` を共有する契約（要件定義 §3 決定論 / D-Q5）。
- **テストの目的**: in-memory 版との決定論的一致（共有ハッシュの証跡）を確認。
  - **確認ポイント**: payload の辞書順差が `_canonical_json(sort_keys=True)` で吸収され hash が一致すること。
- 🔵 (要件定義 §3 決定論 / D-Q5 / ledger.py _compute_hash)

### N-04: 新規/空パスで開くと空 ledger・verify() True・初回 append で新規作成
- **何をテストするか**: 存在しないパスで `PersistentLedger` を開くと空 ledger（`entries==()`）で `verify()` True、
  初回 `append` でファイルが新規作成されること。
- **期待される動作**: 未作成ファイルを破損扱いにせず、空チェーン（GENESIS 起点）として扱う。
- **入力値**: `path = tmp_path / "new.jsonl"`（不在）→ `pl = PersistentLedger(path)` → `pl.append("a", {})`
  - **入力データの意味**: 初回起動（ファイル未作成）の境界。GENESIS_HASH 起点の検証。
- **期待される結果**: オープン直後 `pl.entries == ()` かつ `pl.verify() is True`。`append` 後に `path.exists()` が True、
  1 行（`json.loads` 可能・`index==0`・`prev_hash == GENESIS_HASH`）が書かれる。
  - **期待結果の理由**: 要件定義 4.3（新規/空ファイル）。`"a"` は不在ファイルを作成する。
- **テストの目的**: 空/新規境界での安全動作を確認。
  - **確認ポイント**: 空ファイルで例外を出さないこと・初回エントリの prev_hash が GENESIS であること。
- 🟡 (要件定義 4.3。新規ファイル生成タイミングは 🟡 具体化)

### N-05: JSONL 行スキーマが LedgerEntry.to_dict() と一致（後続 TASK-0014 が依存）
- **何をテストするか**: 追記された JSONL の各行が `{"index","kind","payload","prev_hash","hash"}` の
  スキーマ（`LedgerEntry.to_dict()` 準拠）であること。
- **期待される動作**: 1 行 = 1 エントリの `to_dict()` 形式で永続化され、`json.loads` で往復する。
- **入力値**:
  ```python
  pl = PersistentLedger(path)
  pl.append("k", {"p": 1})
  lines = path.read_text(encoding="utf-8").splitlines()
  row = json.loads(lines[0])
  ```
  - **入力データの意味**: TASK-0014（PersistentSnapshotStore）がキー名・行構造に直接依存するため固定する。
- **期待される結果**: `set(row) == {"index", "kind", "payload", "prev_hash", "hash"}`。
  `row["index"] == 0`、`row["kind"] == "k"`、`row["payload"] == {"p": 1}`、`row["prev_hash"] == GENESIS_HASH`、
  `len(row["hash"]) == 64`。1 行あたり改行 1 個で終端。
  - **期待結果の理由**: 要件定義 §6（JSONL 行スキーマ固定）/ ledger.py `LedgerEntry.to_dict()`。
- **テストの目的**: 永続フォーマット（行スキーマ）の凍結。
  - **確認ポイント**: `to_dict()` と同一キー集合であること・payload がネスト dict のまま保存されること。
- 🔵 (要件定義 §2.2/§6 / ledger.py LedgerEntry.to_dict L34-41)

### N-06: 同一契約 — SnapshotStore に注入して snapshot_save が JSONL へ追記（REQ-012 スモーク）
- **何をテストするか**: in-memory `SnapshotStore(ledger=pl)` に `PersistentLedger` を注入し `save()` すると、
  `snapshot_save` エントリが JSONL に追記され、再オープンで検証できること。
- **期待される動作**: `append(kind, payload)` 契約が in-memory `Ledger` と一致するため、既存 store に**無改変注入**できる。
- **入力値**:
  ```python
  pl = PersistentLedger(path)
  store = SnapshotStore(ledger=pl)
  store.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="init")
  pl2 = PersistentLedger(path)
  ```
  - **入力データの意味**: REQ-012（in-memory と同一 IF・無改変注入）の最小スモーク。TASK-0014 の前提契約。
- **期待される結果**: `pl.entries[-1].kind == "snapshot_save"`。`pl2.verify() is True` かつ
  `pl2.entries[-1].payload["snapshot_id"] == "snap-0000"`。
  - **期待結果の理由**: 要件定義 §3（同一契約・無改変注入）/ snapshot.py の ledger 連携（L38-48）。
- **テストの目的**: `Ledger` 互換契約による注入可能性を確認（REQ-012）。
  - **確認ポイント**: `SnapshotStore` 側を一切変更せず PersistentLedger が受け皿になること。
- 🟡 (要件定義 §3 REQ-012 / snapshot.py。SnapshotStore 自体は in-memory のためスモーク位置づけ)

---

## 2. 異常系テストケース（破損検出・無修復、EDGE-003）

### E-01: 1 行の hash 改竄 → 再オープンで LedgerIntegrityError
- **エラーケースの概要**: 永続化済み JSONL の 1 行の `hash` 値を書き換え（ビット腐敗・改ざん相当）た状態で再オープンする。
- **エラー処理の重要性**: 監査ログ（P2 / NFR-105）の完全性は本システムの核心。破損を沈黙して読み進めてはならない。
- **入力値**:
  ```python
  pl = PersistentLedger(path); pl.append("a", {"i": 0}); pl.append("b", {"i": 1})
  lines = path.read_text(encoding="utf-8").splitlines()
  row = json.loads(lines[1]); row["hash"] = "0" * 64      # hash を改竄
  lines[1] = json.dumps(row)
  path.write_text("\n".join(lines) + "\n", encoding="utf-8")
  ```
  - **不正な理由**: 保存 hash が `_compute_hash(...)` の再計算値と一致しなくなる（チェーン不整合）。
  - **実際の発生シナリオ**: 手動編集・ストレージのビット腐敗・不正な外部書き換え。
- **期待される結果**: `PersistentLedger(path)` が `LedgerIntegrityError` を送出する（`pytest.raises(LedgerIntegrityError)`）。
  - **エラーメッセージの内容**: 破損（ハッシュ不整合）を示す明示メッセージ。沈黙 True を返さない。
  - **システムの安全性**: 破損検出時に例外で停止し、健全性が保証できないデータを提供しない。
- **テストの目的**: 改竄の検出（EDGE-003 の核 / TC-106-04）を確認。
  - **品質保証の観点**: 「verify() が常に True」の不変条件が永続化後も維持されることの担保。
- 🔵 (要件定義 §2.1/4.4 / EDGE-003 / TC-106-04 / NFR-105)

### E-02: payload 改竄 → LedgerIntegrityError + ファイル無変更（修復・上書きしない）
- **エラーケースの概要**: 1 行の `payload` を書き換えた状態で再オープンし、例外送出後もファイルが無変更であることを確認する。
- **エラー処理の重要性**: 破損を検出しても**修復・上書きしない**こと（P2）が非破壊性の要。検出処理自体が書き込んではならない。
- **入力値**:
  ```python
  pl = PersistentLedger(path); pl.append("a", {"i": 0})
  lines = path.read_text(encoding="utf-8").splitlines()
  row = json.loads(lines[0]); row["payload"] = {"i": 999}   # payload を改竄
  lines[0] = json.dumps(row)
  corrupted = "\n".join(lines) + "\n"
  path.write_text(corrupted, encoding="utf-8")
  before = path.read_bytes()
  with pytest.raises(LedgerIntegrityError):
      PersistentLedger(path)
  after = path.read_bytes()
  ```
  - **不正な理由**: payload 変更で `_compute_hash` 再計算値が保存 hash と乖離する。
  - **実際の発生シナリオ**: データ改ざん・部分的な書き込み失敗。
- **期待される結果**: `LedgerIntegrityError` 送出。かつ `after == before`（バイト列完全一致 = ファイル無変更）。
  - **エラーメッセージの内容**: 破損検出の明示エラー。修復ログや上書きの副作用なし。
  - **システムの安全性**: 検出時に read しか行わず、破損ファイルへ一切書き込まない。
- **テストの目的**: 破損の検出 + 無修復（TC-106-04 / EDGE-003）を確認。
  - **品質保証の観点**: P2 の構造的保証（破損時も非破壊）の担保。
- 🔵 (要件定義 §3 EDGE-003 / 4.4 無修復 / TC-106-04)

### E-03: 不正 JSON 行 → LedgerIntegrityError（明示エラー・無修復）
- **エラーケースの概要**: JSON として壊れた行（`json.loads` 失敗）を含むファイルを再オープンする。
- **エラー処理の重要性**: パース不能な破損も沈黙せず明示エラーにする（EDGE-003 の精神）。
- **入力値**:
  ```python
  pl = PersistentLedger(path); pl.append("a", {"i": 0})
  with open(path, "a", encoding="utf-8") as f:
      f.write("{ this is not valid json\n")   # 壊れた行を追記
  ```
  - **不正な理由**: `json.loads` が `JSONDecodeError` を出す不正な行。
  - **実際の発生シナリオ**: 書き込み途中でのクラッシュ（部分行）・外部からの不正追記。
- **期待される結果**: `PersistentLedger(path)` が `LedgerIntegrityError` を送出する
  （`JSONDecodeError` を握り潰さず `LedgerIntegrityError` に包む）。ファイルは無変更。
  - **エラーメッセージの内容**: 破損（パース不能）を示す明示メッセージ。
  - **システムの安全性**: 部分破損でも安全側に倒し、不完全なデータを提供しない。
- **テストの目的**: パース破損の明示エラー化を確認。
  - **品質保証の観点**: hash 不整合以外の破損経路も網羅すること。
- 🟡 (要件定義 4.3/4.4。不正 JSON を LedgerIntegrityError に包む方式は 🟡 具体化)

---

## 3. 境界値テストケース（API 不在・追記のみ・端点）

### B-01: 削除・上書き・改変 API が存在しない（in-memory Ledger と同一属性集合）
- **境界値の意味**: 非破壊性（P2 / NFR-101 / REQ-401）を「API が存在しない」という構造で保証する境界。
- **境界値での動作保証**: `PersistentLedger` は `append` / `entries` / `verify` のみを持ち、破壊的メソッドを持たない。
- **入力値**:
  ```python
  pl = PersistentLedger(path)
  for name in ("delete", "remove", "update", "overwrite", "clear", "pop", "truncate", "__delitem__"):
      assert not hasattr(pl, name)
  ```
  - **境界値選択の根拠**: 完了条件④・TC-106-05。in-memory `Ledger` と同一検証（`Ledger` も同名 API を持たない）。
  - **実際の使用場面**: 監査ログの改変不能性を型レベルで保証する。
- **期待される結果**: 上記いずれの破壊的属性も `hasattr` が False。公開メソッド集合が in-memory `Ledger` と一致
  （`append` / `entries` / `verify` を持つ）。
  - **境界での正確性**: 破壊的 API の不在を明示検証。
  - **一貫した動作**: in-memory 版と同じ「追記のみ」の表面積。
- **テストの目的**: 削除・上書き API 不在の保証（TC-106-05）。
  - **堅牢性の確認**: 誤って破壊的 API を足していないこと。
- 🔵 (要件定義 §3 P2/REQ-401 / TC-106-05 / ledger.py Ledger)

### B-02: 追記のみで成長 — 書き込み前後で先頭バイト列が不変（NFR-203）
- **境界値の意味**: 追記モード（`"a"`）が既存バイト列を一切書き換えない境界（NFR-203 / P2）。
- **境界値での動作保証**: 新規 append は末尾に 1 行を足すだけで、既存部分のバイト列は保存される。
- **入力値**:
  ```python
  pl = PersistentLedger(path); pl.append("a", {"i": 0})
  before = path.read_bytes()                  # 追記前のバイト列
  pl.append("b", {"i": 1})                     # 追記
  after = path.read_bytes()
  ```
  - **境界値選択の根拠**: 完了条件④・TC-106-07。既存バイト列不変が「追記のみ」の観測可能な証跡。
  - **実際の使用場面**: 監査ログの過去エントリが物理的に書き換わらないことの保証。
- **期待される結果**: `after.startswith(before)` が True（先頭 `len(before)` バイトが完全一致）。
  `len(after) > len(before)`（末尾に 1 行増加）。追加分 `after[len(before):]` は `json.loads` 可能な 1 行 + 改行。
  - **境界での正確性**: 既存バイト列が 1 バイトも変わらないこと。
  - **一貫した動作**: 何回 append しても先頭は不変で末尾のみ伸びる。
- **テストの目的**: 追記のみの成長（TC-106-07 / NFR-203）を確認。
  - **堅牢性の確認**: `"w"` / `truncate` / `seek` 上書きを使っていないことの観測的証明。
- 🔵 (要件定義 §3 NFR-203 / TC-106-07)

### B-03: エントリ 0 件（空 ledger）の verify() True
- **境界値の意味**: エントリ数の下限 0。空チェーン（GENESIS のみ）の検証境界。
- **境界値での動作保証**: 空でも `verify()` が True（GENESIS 起点で矛盾がない）。
- **入力値**: `pl = PersistentLedger(tmp_path / "empty.jsonl")`（append しない）
  - **境界値選択の根拠**: エントリ 0 件の最小境界。in-memory `Ledger` も空で verify() True。
  - **実際の使用場面**: 記録がまだ無い解析セッションの初期状態。
- **期待される結果**: `pl.entries == ()` かつ `pl.verify() is True`。
  - **境界での正確性**: 空リストの検証ループが True を返す（`ledger.py` L69-79 と同一）。
  - **一貫した動作**: 0 件・1 件・多数件で検証ロジックが一貫。
- **テストの目的**: 空 ledger の検証境界を確認。
  - **堅牢性の確認**: 空で例外・False を出さないこと。
- 🔵 (要件定義 4.3 / ledger.py Ledger.verify 空リスト True)

### B-04: エントリ 1 件の再オープン検証（最小の永続チェーン）
- **境界値の意味**: エントリ数 1 の最小の永続チェーン。単一エントリでも GENESIS 連結が検証される境界。
- **境界値での動作保証**: 1 件でも `prev_hash == GENESIS_HASH` かつ hash 整合で verify() True。
- **入力値**: `pl = PersistentLedger(path); pl.append("solo", {"v": 1})` → `pl2 = PersistentLedger(path)`
  - **境界値選択の根拠**: 0 件（B-03）と多数件（N-01）の間の 1 件境界。
  - **実際の使用場面**: 最初の 1 エントリだけ記録して再起動するケース。
- **期待される結果**: `pl2.entries[0].index == 0`、`pl2.entries[0].prev_hash == GENESIS_HASH`、`pl2.verify() is True`、
  `pl2.entries[0] == pl.entries[0]`。
  - **境界での正確性**: 単一エントリの GENESIS 連結が保持される。
  - **一貫した動作**: 件数によらず検証が成立。
- **テストの目的**: 最小チェーンの再オープン検証を確認。
  - **堅牢性の確認**: 1 件でチェーンロジックが破綻しないこと。
- 🔵 (要件定義 §2.1/2.4 / ledger.py GENESIS_HASH)

### B-05: 末尾の空行・改行のみの行はスキップ（破損扱いにしない）
- **境界値の意味**: 正常な追記の副産物である末尾改行・空行を、破損と誤判定しない境界。
- **境界値での動作保証**: 末尾に余分な空行があっても `verify()` True・エントリ数が正しい。
- **入力値**:
  ```python
  pl = PersistentLedger(path); pl.append("a", {"i": 0})
  with open(path, "a", encoding="utf-8") as f:
      f.write("\n")          # 余分な空行
  pl2 = PersistentLedger(path)
  ```
  - **境界値選択の根拠**: 各行が `"...\n"` で終わるため、末尾空文字列が生じ得る境界（要件定義 §2.1-4）。
  - **実際の使用場面**: エディタ保存や追記の末尾改行。
- **期待される結果**: `pl2.verify() is True` かつ `len(pl2.entries) == 1`（空行は無視され破損扱いにならない）。
  - **境界での正確性**: 空/空白のみの行をスキップし、不正 JSON（E-03）とは区別する。
  - **一貫した動作**: 末尾改行の有無で結果が変わらない。
- **テストの目的**: 空行スキップの許容（正常系の頑健性）を確認。
  - **堅牢性の確認**: 末尾改行を `JSONDecodeError` にしないこと。
- 🟡 (要件定義 §2.1-4/4.3。空行スキップ方式は 🟡 具体化)

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 🔵
  - **言語選択の理由**: プロジェクト全体が Python 3.12（uv 管理, src layout + hatchling）。本タスクは標準ライブラリ
    （`json` / `pathlib` / `os`）のみで完結。
  - **テストに適した機能**: `tmp_path` フィクスチャによる隔離ファイル、`pytest.raises` による例外検証、
    `Path.read_bytes()` によるバイト列比較（追記のみ・無変更の検証）。
- **テストフレームワーク**: pytest >= 8 + pytest-cov 🔵
  - **フレームワーク選択の理由**: `pyproject.toml [tool.pytest.ini_options]` で設定済み。既存 `tests/test_ledger.py` が pytest 準拠。
  - **テスト実行環境**: `uv run pytest tests/test_persistent_store.py`（単体）/ `uv run pytest`（全体回帰 = 223 passed / 3 skipped 維持）。
    依存導入は `uv sync --extra gsas`（プレーン `uv sync` は禁止）。本タスクは GSAS-II 非依存のため `gsas` マーカー不要。
- 🔵 (note.md §5 テスト関連情報 / pyproject.toml)

---

## 5. テストケース実装時の日本語コメント指針

各テストに以下の形式で日本語コメントを付す（既存 `tests/test_ledger.py` / M1 `test_clustering.py` の慣習に準拠）。

### 永続 roundtrip の標準形

```python
import json
import pytest
from tsumugin.store.ledger import GENESIS_HASH, Ledger
from tsumugin.store.persistent import PersistentLedger
from tsumugin.errors import LedgerIntegrityError

# 【テスト目的】: append → 再オープン → verify() True + エントリ全量一致を確認 (完了条件① / TC-106-01)
# 【テスト内容】: PersistentLedger へ 2 件追記し、別インスタンスで再オープンして検証・突合
# 【期待される動作】: verify() True、entries が書き込み全量と一致
# 🔵 信頼性: 完了条件① / ledger.py Ledger.verify
def test_append_reopen_verify_and_entries_match(tmp_path):
    # 【テストデータ準備】: 逐次解析の代表的な監査エントリ 2 件を用意
    # 【初期条件設定】: 空の JSONL パスから開始
    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    e0 = pl.append("phase_accept", {"hyp": "hyp-0001", "rwp": 12.3})
    e1 = pl.append("snapshot_save", {"snapshot_id": "snap-0000", "n_phases": 2})

    # 【実際の処理実行】: 同一パスを別インスタンスで再オープン
    # 【処理内容】: JSONL 各行 → LedgerEntry 再構築 → verify()
    pl2 = PersistentLedger(path)

    # 【結果検証】: 検証成功かつエントリ全量一致
    # 🔵 信頼性: TC-106-01
    assert pl2.verify() is True                       # 【確認内容】: 再オープン後もチェーン健全
    assert pl2.entries == (e0, e1)                     # 【確認内容】: hash まで含め全量一致
```

### 改竄検出・無修復の標準形

```python
# 【テスト目的】: payload 改竄を再オープンで検出し、かつファイルを無変更に保つことを確認 (EDGE-003 / TC-106-04)
# 【テスト内容】: 1 行の payload を書き換えた JSONL を再オープン
# 【期待される動作】: LedgerIntegrityError 送出、ファイルのバイト列が無変更
# 🔵 信頼性: 完了条件③ / EDGE-003
def test_tampered_payload_raises_and_file_unchanged(tmp_path):
    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    pl.append("a", {"i": 0})

    # 【テストデータ準備】: 保存済み 1 行の payload を改竄
    lines = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0]); row["payload"] = {"i": 999}
    lines[0] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = path.read_bytes()

    # 【実際の処理実行】: 破損ファイルを再オープン
    # 【結果検証】: 明示エラー + ファイル無変更
    with pytest.raises(LedgerIntegrityError):          # 【確認内容】: 破損を沈黙せず送出
        PersistentLedger(path)
    assert path.read_bytes() == before                 # 【確認内容】: 修復・上書きしない (P2)
```

### 追記のみ成長の標準形

```python
# 【テスト目的】: append 前後で先頭バイト列が不変であることを確認 (NFR-203 / TC-106-07)
# 【テスト内容】: 1 件追記後にバイト列を記録し、再追記後の先頭と比較
# 【期待される動作】: after.startswith(before) かつ末尾のみ伸長
# 🔵 信頼性: NFR-203 / TC-106-07
def test_append_only_growth_prefix_unchanged(tmp_path):
    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    pl.append("a", {"i": 0})
    before = path.read_bytes()          # 【初期条件設定】: 追記前のバイト列

    pl.append("b", {"i": 1})            # 【実際の処理実行】: 追記モードで 1 行追加

    after = path.read_bytes()
    assert after.startswith(before)     # 【確認内容】: 既存バイト列が不変 (追記のみ)
    assert len(after) > len(before)     # 【確認内容】: 末尾に 1 行増加
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: 要件定義 §1（PersistentLedger の JSONL 永続化・再オープン検証・破損無修復・store 最下層）
- **参照した入力・出力仕様**: 要件定義 §2.1（__init__ 再オープン検証）、§2.2（append 追記 I/O）、§2.3（entries）、
  §2.4（verify）、§2.5（LedgerIntegrityError）、§2.6（データフロー）
- **参照した制約条件**: 要件定義 §3（追記モード限定 / 再オープン検証 / 破損無修復 / 決定論 / 同一契約 / レイヤ制約 /
  ledger.py 挙動不変）
- **参照した使用例**: 要件定義 §4（永続追記・再オープン・注入 / 新規空ファイル / 改竄・不正 JSON / 空行スキップ）
- **参照した受け入れ基準**: TC-106-01（N-01）、TC-106-02（N-02）、TC-106-04/EDGE-003（E-01/E-02）、
  TC-106-05（B-01）、TC-106-07/NFR-203（B-02）
- **参照した完了条件**: ① N-01 / ② N-02 / ③ E-01・E-02 / ④ B-01・B-02 / ⑤ N-03
- **回帰ゲート（テスト外）**: `uv run pytest` 全体で既存 223 passed / 3 skipped を維持（新規テストのみ増加）。
  `ledger.py` を公開昇格でリファクタする場合も `tests/test_ledger.py` が緑のまま（挙動不変）。

---

## 品質判定結果

- **テストケース分類**: 正常系 6 / 異常系（破損検出・無修復）3 / 境界値（API 不在・追記のみ・端点）5 を網羅 ✅
- **期待値定義**: 各ケースに具体的期待値（`verify() is True` / `pytest.raises(LedgerIntegrityError)` /
  バイト列 `startswith` / `entries` 一致 / `not hasattr`）を明記 ✅
- **技術選択**: Python 3.12 + pytest（`tmp_path`）で確定 ✅
- **実装可能性**: 標準ライブラリ + 既存 `ledger.py` 関数の共有のみで確実に実現可能 ✅
- **信頼性レベル**: 🔵 11 / 🟡 3 / 🔴 0 — **✅ 高品質**
  - 🟡 が 3 件（N-04 新規ファイル生成タイミング / E-03 不正 JSON の例外包み / B-05 空行スキップ）あるのは、
    設計文書が「JSONL 選定は 🟡」とする実装詳細に由来するため。いずれも要件へ遡及可能で曖昧さなし。
