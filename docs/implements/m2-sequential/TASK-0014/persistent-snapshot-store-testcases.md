# TASK-0014 store/persistent — PersistentSnapshotStore TDDテストケース定義書

**機能名**: store/persistent（拡張）— `PersistentSnapshotStore(path, ledger=None)`（snapshot の JSONL 永続 + 再オープン復元/revert）
**タスクID**: TASK-0014 / **要件名**: m2-sequential
**作成日**: 2026-07-03
**要件定義**: `docs/implements/m2-sequential/TASK-0014/persistent-snapshot-store-requirements.md`
**出力ファイル**: `docs/implements/m2-sequential/TASK-0014/persistent-snapshot-store-testcases.md`
**テスト対象実装**: `src/tsumugin/store/persistent.py`（**既存を拡張** — `PersistentSnapshotStore` 追加）
**テストファイル**: `tests/test_persistent_store.py`（**既存に追加**。TASK-0013 の `PersistentLedger` テスト 14 件が既存。`tmp_path` 使用）

**【信頼性レベル凡例】**:
- 🔵 **青信号**: 要件定義・既存実装・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: 元の資料から妥当な推測
- 🔴 **赤信号**: 元の資料にない推測

---

## テストケース一覧サマリー

| 分類 | 件数 | テストID |
|---|---|---|
| 正常系 | 6 | N-01〜N-06 |
| 異常系 (未知 id・新規/空パス) | 2 | E-01〜E-02 |
| 境界値 (API 不在・追記のみ・非破壊 revert・空 phases・current_id) | 5 | B-01〜B-05 |
| **合計** | **13** | |

**信頼性分布**: 🔵 10 / 🟡 3 / 🔴 0 — 品質評価: 高品質

**完了条件との対応**:
- 完了条件① save → 再オープン → load/revert で phases 等価復元（TC-106-03）→ **N-01（load）/ N-02（revert）**
- 完了条件② snapshot ID 連番が再オープン跨ぎで継続 → **N-03**
- 完了条件③ 削除・上書き API 不在（TC-106-05）→ **B-01**
- 完了条件④ `StagedRefinementEngine` に注入して M0 経路が無改変で動く（TC-106-06 / REQ-012）→ **N-06**
- 完了条件⑤ ledger 連携時 `snapshot_save` / `snapshot_revert` が記録される → **N-04（save）/ N-05（revert）**

---

## 1. 正常系テストケース（基本的な動作）

### N-01: 永続保存 → 再オープン → load(snapshot_id) で phases 等価復元
- **何をテストするか**: `PersistentSnapshotStore` に複数 save し、別インスタンスで同一パスを再オープンすると
  `load(snapshot_id)` が保存済み `Snapshot` を返し、その phases が保存時と**値等価**であること。
- **期待される動作**: プロセス再起動相当（別インスタンス）でも永続化された状態スナップショットが完全復元される。
- **入力値**:
  ```python
  path = tmp_path / "snapshots.jsonl"
  st = PersistentSnapshotStore(path)
  p0 = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0), scale=1.0),)
  p1 = (PhaseInstance("A", LatticeParams(5.1, 5.1, 5.1), scale=0.8),
        PhaseInstance("B", LatticeParams(6.0, 6.0, 6.0)),)
  s0 = st.save(p0, label="init")     # snap-0000
  s1 = st.save(p1, label="stage")    # snap-0001
  st2 = PersistentSnapshotStore(path)  # 再オープン
  ```
  - **入力データの意味**: 逐次解析で各段に確定する代表的な phases（相 1 個 → 相 2 個へ変化）。プロセス再起動をまたぐ永続化の主経路。
- **期待される結果**: `st2.load("snap-0000").phases == p0`、`st2.load("snap-0001").phases == p1`。
  `st2.load("snap-0001").label == "stage"`、`st2.load("snap-0001").parent_id == "snap-0000"`。
  - **期待結果の理由**: 完了条件①・TC-106-03。JSONL 行 → `phase_from_dict` で phases 復元 → `Snapshot` 再構築の契約（要件定義 §2.1/2.3）。有限値 phase は `phase_from_dict(phase_to_dict(p)) == p`（要件定義 §3 phases 等価）。
- **テストの目的**: 永続 roundtrip + 再オープン load の保証（機能の中核）。
  - **確認ポイント**: phases が `PhaseInstance` の値等価で復元され、parent_id 連結・label まで保持されること。
- 🔵 (要件定義 §2.1/2.3 完了条件① / TC-106-03 / snapshot.py `Snapshot` / serialization.py roundtrip)

### N-02: 再オープン → revert(snapshot_id) で phases tuple 等価復元
- **何をテストするか**: 再オープンした `PersistentSnapshotStore` で `revert(snapshot_id)` を呼ぶと、
  指定 snapshot の `phases` タプルが保存時と等価で返り、`current_id` がその id へ移ること。
- **期待される動作**: 永続化された過去状態へ非破壊 revert して phases を取り戻せる（REQ-011）。
- **入力値**:
  ```python
  st = PersistentSnapshotStore(path)
  p0 = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0)),)
  p1 = (PhaseInstance("A", LatticeParams(5.1, 5.1, 5.1)),)
  st.save(p0, label="init"); st.save(p1, label="stage")
  st2 = PersistentSnapshotStore(path)     # 再オープン
  reverted = st2.revert("snap-0000")       # 過去状態へ revert
  ```
  - **入力データの意味**: 「再起動して過去のスナップショットへ戻す」実運用シナリオ（TC-106-03 の revert 側）。
- **期待される結果**: `reverted == p0`（`tuple[PhaseInstance, ...]` の値等価）。`st2.current_id == "snap-0000"`。
  `st2.snapshots` の長さは 2 のまま（revert で前方履歴を消さない）。
  - **期待結果の理由**: 完了条件①・TC-106-03。`SnapshotStore.revert` の「現在位置を移すだけ」規約（要件定義 §2.4）。
- **テストの目的**: 再オープン跨ぎの非破壊 revert を確認。
  - **確認ポイント**: revert が phases tuple を返し current_id を移すが snapshots は縮小しないこと。
- 🔵 (要件定義 §2.4 完了条件① / TC-106-03 / snapshot.py L53-61)

### N-03: snapshot ID 連番が再オープン跨ぎで継続
- **何をテストするか**: save で `snap-0000` を発番 → 再オープン → さらに save すると `snap-0001` が発番され、
  `parent_id` が直前 snapshot に連結すること。
- **期待される動作**: 永続化された既存 snapshot 数から連番を継続し、再起動をまたいでも ID が重複・巻き戻りしない。
- **入力値**:
  ```python
  st = PersistentSnapshotStore(path)
  st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="a")   # snap-0000
  st2 = PersistentSnapshotStore(path)                                  # 再オープン (既存 1 件)
  s = st2.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="b")  # snap-0001
  ```
  - **入力データの意味**: 「再起動して続きから記録する」実運用シナリオ（完了条件②）。
- **期待される結果**: `s.id == "snap-0001"`。`s.parent_id == "snap-0000"`。`len(st2.snapshots) == 2`。
  さらに 3 回目のオープン `PersistentSnapshotStore(path)` で `snapshots` の長さが 2・id 列が `["snap-0000","snap-0001"]`。
  - **期待結果の理由**: 完了条件②。`save` の `snap_id = f"snap-{len(self._snaps):04d}"` 規約 + 再オープン時の復元数からの継続（要件定義 §2.1/2.2）。
- **テストの目的**: 再オープン跨ぎの ID 連番継続を確認。
  - **確認ポイント**: 連番・parent_id 連結・snapshots 件数の 3 点が同時に成り立つこと。
- 🔵 (要件定義 §2.1/2.2 完了条件② / snapshot.py L31 `snap-{len:04d}`)

### N-04: ledger 連携 — save で snapshot_save が記録される
- **何をテストするか**: `PersistentSnapshotStore(path, ledger=pl)` に `PersistentLedger` を注入して save すると、
  `snapshot_save` エントリが ledger に追記され、payload が in-memory `SnapshotStore` と一致すること。
- **期待される動作**: save 監査が ledger（`PersistentLedger`）へ記録され、ledger 再オープンで検証できる。
- **入力値**:
  ```python
  snap_path = tmp_path / "snapshots.jsonl"
  led_path = tmp_path / "ledger.jsonl"
  pl = PersistentLedger(led_path)
  st = PersistentSnapshotStore(snap_path, ledger=pl)
  st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="init")
  pl2 = PersistentLedger(led_path)   # ledger 再オープン
  ```
  - **入力データの意味**: 完了条件⑤（ledger 連携）の save 側。snapshot 本体と監査 ledger を別ファイルで永続化する構成。
- **期待される結果**: `pl.entries[-1].kind == "snapshot_save"`。
  `pl.entries[-1].payload == {"snapshot_id": "snap-0000", "label": "init", "parent_id": None, "n_phases": 1}`。
  `pl2.verify() is True` かつ `pl2.entries[-1].payload["snapshot_id"] == "snap-0000"`。
  - **期待結果の理由**: 完了条件⑤。`SnapshotStore.save` の ledger 記録 payload（`snapshot.py` L38-48）と同一契約（要件定義 §2.2）。
- **テストの目的**: ledger 連携（save 記録）と ledger 永続化の結合を確認。
  - **確認ポイント**: payload のキー集合・値が in-memory 版と一致し、注入 ledger 再オープンで verify() True。
- 🔵 (要件定義 §2.2/完了条件⑤ / snapshot.py L38-48 / TASK-0013 PersistentLedger)

### N-05: ledger 連携 — revert で snapshot_revert が記録される（snapshot ファイルは無変更）
- **何をテストするか**: ledger 注入下で revert すると、`snapshot_revert` エントリが ledger に追記され、
  かつ snapshot JSONL 本体には**追記されない**（revert は状態遷移でありデータ追加ではない）こと。
- **期待される動作**: revert 監査が ledger へ記録される一方、snapshot ファイルは非破壊・追記なしを保つ。
- **入力値**:
  ```python
  pl = PersistentLedger(tmp_path / "ledger.jsonl")
  snap_path = tmp_path / "snapshots.jsonl"
  st = PersistentSnapshotStore(snap_path, ledger=pl)
  st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="init")   # snap-0000
  before = snap_path.read_bytes()
  st.revert("snap-0000")
  after = snap_path.read_bytes()
  ```
  - **入力データの意味**: 完了条件⑤（ledger 連携）の revert 側 + 非破壊 revert の証跡。
- **期待される結果**: `pl.entries[-1].kind == "snapshot_revert"`。
  `pl.entries[-1].payload == {"snapshot_id": "snap-0000", "label": "init"}`。`after == before`（snapshot ファイル無変更）。
  - **期待結果の理由**: 完了条件⑤。`SnapshotStore.revert` の ledger 記録 payload（`snapshot.py` L56-60）と同一契約。revert は snapshot 追記なし（要件定義 §2.4/§3 非破壊 revert）。
- **テストの目的**: ledger 連携（revert 記録）と revert の非破壊性を同時確認。
  - **確認ポイント**: revert が ledger にのみ記録し snapshot JSONL のバイト列を変えないこと。
- 🔵 (要件定義 §2.4/§3 完了条件⑤ / snapshot.py L56-60)

### N-06: StagedRefinementEngine への無改変注入 — M0 経路が動き in-memory 版と等価（TC-106-06 / REQ-012）
- **何をテストするか**: `StagedRefinementEngine(SimulatedBackend(), store=PersistentSnapshotStore(...), ledger=Ledger())`
  を `.run(...)` し、in-memory `SnapshotStore` を注入した同一実行と**等価な結果**が得られ、M0 経路が無改変で完走すること。
- **期待される動作**: `PersistentSnapshotStore` が `SnapshotStore` とダックタイプ互換（`save(...).id` / `revert(id) -> tuple`）のため、エンジンを一切改変せず差し替え可能。
- **入力値**:
  ```python
  backend = SimulatedBackend()
  phases = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0)),)
  tt = np.arange(15.0, 60.0, 0.05)
  y = backend.simulate(phases, tt)

  # in-memory 版（基準）
  eng_mem = StagedRefinementEngine(backend, SnapshotStore(), Ledger())
  rep_mem = eng_mem.run(phases, tt, y)

  # 永続版（差し替え）
  eng_pers = StagedRefinementEngine(
      backend, PersistentSnapshotStore(tmp_path / "snapshots.jsonl"), Ledger())
  rep_pers = eng_pers.run(phases, tt, y)
  ```
  - **入力データの意味**: 完了条件④・TC-106-06。M0 の合成データ（GSAS 非依存）で StagedRefinementEngine の store 注入点（`save`/`revert`）を差し替える REQ-012 の裏取り。
- **期待される結果**: `rep_pers.metrics == rep_mem.metrics`、`rep_pers.final_phases == rep_mem.final_phases`、
  `rep_pers.escalated == rep_mem.escalated`（決定論・等価）。`eng_pers` 実行後に snapshot JSONL が生成され
  `PersistentSnapshotStore(...).snapshots` が非空で再オープン復元できる。例外なく完走。
  - **期待結果の理由**: REQ-012（in-memory と同一 IF・無改変注入）+ NFR-102（決定論ビット同一）。エンジンは store を `save(current, label=...).id` と `revert(id)` でしか使わない（`staged.py` L131/171/197）。
- **テストの目的**: 既存エンジンへの無改変注入（TC-106-06）と M0 経路不変を確認。
  - **確認ポイント**: 永続版と in-memory 版でレポートが等価（挙動が変わらない）こと・snapshot が永続化されること。
- 🔵 (要件定義 §3 REQ-012 / TC-106-06 / staged.py L65-83,131,171,197 / backends/simulated.py)

---

## 2. 異常系テストケース（未知 id・新規/空パス）

### E-01: 存在しない snapshot_id への load / revert は KeyError（in-memory と同一縮退）
- **エラーケースの概要**: 保存されていない snapshot_id を `load` / `revert` に渡す。
- **エラー処理の重要性**: 未知 id を沈黙して None や空を返すと、上位が誤った状態で continue するため、in-memory `SnapshotStore` と同じく KeyError で明示的に失敗させる必要がある。
- **入力値**:
  ```python
  st = PersistentSnapshotStore(tmp_path / "snapshots.jsonl")
  st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="init")   # snap-0000 のみ
  # 未知 id
  st.load("snap-9999")     # -> KeyError
  st.revert("snap-9999")   # -> KeyError
  ```
  - **不正な理由**: `self._index` に存在しないキー。`SnapshotStore.load`/`revert` は `self._index[snapshot_id]` で KeyError。
  - **実際の発生シナリオ**: 誤った id 参照・別セッションの id 混入・タイプミス。
- **期待される結果**: `load("snap-9999")` と `revert("snap-9999")` がいずれも `pytest.raises(KeyError)`。
  - **エラーメッセージの内容**: KeyError（辞書アクセス由来）。沈黙 None を返さない。
  - **システムの安全性**: 未知状態への遷移を防ぎ、存在する snapshot のみ操作対象とする。
- **テストの目的**: 未知 id の明示的失敗（in-memory 版との縮退一致）を確認。
  - **品質保証の観点**: 永続版でも in-memory 版と同じ失敗契約を守ること。
- 🔵 (要件定義 §2.3/2.4/§4.4 / snapshot.py L50-51,53-54 `self._index[snapshot_id]`)

### E-02: 新規/空パスで開くと空ストア・初回 save でファイル新規作成
- **エラーケースの概要**: 存在しないパスで `PersistentSnapshotStore` を開く（初回起動の境界）。
- **エラー処理の重要性**: 未作成ファイルを破損扱い・例外にせず、空ストアとして扱えること（縮退の健全性）。
- **入力値**:
  ```python
  path = tmp_path / "new.jsonl"           # 不在
  st = PersistentSnapshotStore(path)
  # オープン直後
  st.snapshots                            # == ()
  st.current_id                           # is None
  path.exists()                           # False（読み取りのみ・作らない）
  st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="init")   # 初回 save で作成
  ```
  - **不正な理由**: （擬似異常）ファイル未作成という縮退入力。
  - **実際の発生シナリオ**: 新規解析セッションの初回起動。
- **期待される結果**: オープン直後 `st.snapshots == ()` かつ `st.current_id is None` かつ `not path.exists()`。
  `save` 後に `path.exists()` が True、1 行（`json.loads` 可能・`id == "snap-0000"`・`parent_id is None`）が書かれる。
  - **エラーメッセージの内容**: 該当なし（例外を出さず空ストアとして開く）。
  - **システムの安全性**: 空/新規で例外・誤検出を出さず、初回 save まではファイルに触れない。
- **テストの目的**: 空/新規境界での安全動作を確認。
  - **品質保証の観点**: `PersistentLedger` の N-04 と対をなす、snapshot ストアの新規境界の担保。
- 🟡 (要件定義 §4.3。新規ファイル生成タイミングは 🟡 具体化 / persistent.py PersistentLedger の同方針)

---

## 3. 境界値テストケース（API 不在・追記のみ・非破壊 revert・空 phases・current_id）

### B-01: 削除・上書き・改変 API が存在しない（in-memory SnapshotStore と同一属性集合）
- **境界値の意味**: 非破壊性（P2 / NFR-101 / REQ-401）を「API が存在しない」という構造で保証する境界。
- **境界値での動作保証**: `PersistentSnapshotStore` は `save` / `load` / `revert` / `snapshots` / `current_id` のみを持ち、破壊的メソッドを持たない。
- **入力値**:
  ```python
  st = PersistentSnapshotStore(tmp_path / "snapshots.jsonl")
  for name in ("delete", "remove", "update", "overwrite", "clear", "pop", "truncate", "__delitem__"):
      assert not hasattr(st, name)
  for name in ("save", "load", "revert", "snapshots", "current_id"):
      assert hasattr(st, name)
  ```
  - **境界値選択の根拠**: 完了条件③・TC-106-05。in-memory `SnapshotStore` と同一検証（`SnapshotStore` も同名破壊 API を持たない）。
  - **実際の使用場面**: 状態履歴の改変不能性を型レベルで保証する。
- **期待される結果**: 破壊的属性はいずれも `hasattr` が False。公開メソッド集合が in-memory `SnapshotStore` と一致（save/load/revert/snapshots/current_id を持つ）。
  - **境界での正確性**: 破壊的 API の不在を明示検証。
  - **一貫した動作**: in-memory 版と同じ「追記 + revert のみ」の表面積。
- **テストの目的**: 削除・上書き API 不在の保証（TC-106-05）。
  - **堅牢性の確認**: 誤って破壊的 API を足していないこと。
- 🔵 (要件定義 §3 P2/REQ-401 / TC-106-05 / snapshot.py SnapshotStore)

### B-02: 追記のみで成長 — save 前後で先頭バイト列が不変（NFR-203）
- **境界値の意味**: 追記モード（`"a"`）が既存バイト列を一切書き換えない境界（NFR-203 / P2）。
- **境界値での動作保証**: 新規 save は snapshot JSONL 末尾に 1 行を足すだけで、既存部分のバイト列は保存される。
- **入力値**:
  ```python
  path = tmp_path / "snapshots.jsonl"
  st = PersistentSnapshotStore(path)
  st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="a")   # snap-0000
  before = path.read_bytes()
  st.save((PhaseInstance("B", LatticeParams(6, 6, 6)),), label="b")   # snap-0001（追記）
  after = path.read_bytes()
  ```
  - **境界値選択の根拠**: 完了条件（非破壊）・NFR-203。既存バイト列不変が「追記のみ」の観測可能な証跡。
  - **実際の使用場面**: 過去 snapshot が物理的に書き換わらないことの保証。
- **期待される結果**: `after.startswith(before)` が True（先頭 `len(before)` バイトが完全一致）。
  `len(after) > len(before)`（末尾に 1 行増加）。追加分 `after[len(before):]` は `json.loads` 可能な 1 行 + 改行。
  - **境界での正確性**: 既存バイト列が 1 バイトも変わらないこと。
  - **一貫した動作**: 何回 save しても先頭は不変で末尾のみ伸びる。
- **テストの目的**: 追記のみの成長（NFR-203）を確認。
  - **堅牢性の確認**: `"w"` / `truncate` / `seek` 上書きを使っていないことの観測的証明。
- 🔵 (要件定義 §3 NFR-203 / persistent.py PersistentLedger.append の追記パターン)

### B-03: 非破壊 revert — revert は snapshot JSONL に追記せず前方履歴を消さない
- **境界値の意味**: revert が「現在位置を移すだけ」でデータ追加も削除もしない非破壊境界（REQ-011 / P2）。
- **境界値での動作保証**: revert 後も `snapshots` は縮小せず、snapshot ファイルのバイト列も不変。revert 後の save は新規 ID を発番する。
- **入力値**:
  ```python
  path = tmp_path / "snapshots.jsonl"
  st = PersistentSnapshotStore(path)     # ledger なし（revert 記録なし = ファイル観点に集中）
  st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="a")   # snap-0000
  st.save((PhaseInstance("B", LatticeParams(6, 6, 6)),), label="b")   # snap-0001
  before = path.read_bytes()
  st.revert("snap-0000")                  # 過去へ現在位置を移す
  after = path.read_bytes()
  s2 = st.save((PhaseInstance("C", LatticeParams(7, 7, 7)),), label="c")  # revert 後の save
  ```
  - **境界値選択の根拠**: REQ-011「revert は前方履歴を消さず現在位置を移すだけ」の観測的境界。
  - **実際の使用場面**: 誤った段から過去へ戻し、別分岐で再開する運用。
- **期待される結果**: `after == before`（revert は snapshot ファイルへ追記しない）。`st.current_id == "snap-0000"`（revert 直後）。
  `len(st.snapshots) == 2`（revert では消えない）。`s2.id == "snap-0002"`（連番継続）・`s2.parent_id == "snap-0000"`（revert 位置が親）。revert 後は `snapshots` 長さ 3。
  - **境界での正確性**: revert がファイル無変更・履歴非削除・現在位置移動を同時に満たす。
  - **一貫した動作**: revert → save で分岐履歴が追記で保持される。
- **テストの目的**: 非破壊 revert（前方履歴保持・ファイル無変更）を確認。
  - **堅牢性の確認**: revert が破壊的操作にならないこと。
- 🔵 (要件定義 §2.4/§3 REQ-011/P2 / snapshot.py L53-61)

### B-04: 空 phases のスナップショット（n_phases=0 の境界）
- **境界値の意味**: phases タプルが空（相ゼロ）の下限境界。空でも save/reopen/load/revert が成立するか。
- **境界値での動作保証**: `save((), label=...)` で空 phases の Snapshot を作り、再オープンで空タプルが復元される。
- **入力値**:
  ```python
  path = tmp_path / "snapshots.jsonl"
  st = PersistentSnapshotStore(path)
  s = st.save((), label="empty")          # phases 空タプル
  st2 = PersistentSnapshotStore(path)     # 再オープン
  ```
  - **境界値選択の根拠**: phases 数の下限 0。空配列が JSON 直列化・復元で保持される境界。
  - **実際の使用場面**: 全相消失や初期化前の状態を記録するケース。
- **期待される結果**: `s.phases == ()`。`st2.load("snap-0000").phases == ()`。`st2.revert("snap-0000") == ()`。
  ledger 注入時の `snapshot_save` payload は `n_phases == 0`。
  - **境界での正確性**: 空 phases 配列が `[]` として直列化され `()` へ復元されること。
  - **一貫した動作**: phases 0 個・1 個・複数個で復元ロジックが一貫。
- **テストの目的**: 空 phases 境界の復元を確認。
  - **堅牢性の確認**: 空タプルで例外を出さないこと。
- 🟡 (要件定義 §4.3 空 phases。空配列 roundtrip は妥当な推測 / serialization.py phase_to_dict の phases ループ)

### B-05: current_id の初期値と再オープン後の値（状態プロパティの境界）
- **境界値の意味**: `current_id` の下限（未 save = None）と再オープン後の値（最新 save）の境界。
- **境界値での動作保証**: save 前は None、save 後は最新 id、再オープン後も最新 save の id を指す（後続 save の parent_id 連結が成立）。
- **入力値**:
  ```python
  path = tmp_path / "snapshots.jsonl"
  st = PersistentSnapshotStore(path)
  cid_empty = st.current_id                 # 未 save
  st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="a")   # snap-0000
  st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="b")   # snap-0001
  cid_after_save = st.current_id
  st2 = PersistentSnapshotStore(path)       # 再オープン
  cid_reopen = st2.current_id
  s = st2.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="c")  # snap-0002
  ```
  - **境界値選択の根拠**: `current_id` は revert/再オープン跨ぎの「現在位置」を担う状態。TASK-0014.md が同一契約に含める。
  - **実際の使用場面**: warm-continue（前回位置から続ける）・parent_id 連結の起点確定。
- **期待される結果**: `cid_empty is None`。`cid_after_save == "snap-0001"`。`cid_reopen == "snap-0001"`（再オープンで最新 save を指す）。`s.parent_id == "snap-0001"`（後続 save が最新に連結）。
  - **境界での正確性**: 未 save の None・save 後の最新・再オープン後の最新の 3 状態が正しいこと。
  - **一貫した動作**: 再オープン前後で current_id の意味（最新 save 位置）が一貫。
- **テストの目的**: current_id の境界（None / 最新 / 再オープン復元）を確認。
  - **堅牢性の確認**: 再オープンで parent_id 連結が途切れないこと。
- 🟡 (要件定義 §2.1/2.5。再オープン時 current_id を最新 save に設定する挙動は 🟡 設計判断 / snapshot.py L67-69)

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 🔵
  - **言語選択の理由**: プロジェクト全体が Python 3.12（uv 管理, src layout + hatchling）。本タスクは標準ライブラリ
    （`json` / `pathlib` / `os`）+ 同層 `serialization` / `snapshot` のみで完結。TC-106-06 のみ numpy + SimulatedBackend を使う。
  - **テストに適した機能**: `tmp_path` フィクスチャによる隔離ファイル、frozen dataclass（`PhaseInstance`/`Snapshot`）の値等価比較、`pytest.raises` による例外検証、`Path.read_bytes()` によるバイト列比較（追記のみ・無変更の検証）。
- **テストフレームワーク**: pytest >= 8 + pytest-cov 🔵
  - **フレームワーク選択の理由**: `pyproject.toml [tool.pytest.ini_options]` で設定済み。既存 `tests/test_persistent_store.py`（TASK-0013）/ `tests/test_snapshot.py` が pytest 準拠。同ファイルへ追記する。
  - **テスト実行環境**: `uv run pytest tests/test_persistent_store.py`（単体）/ `uv run pytest`（全体回帰 = 既存を壊さない）。
    依存導入は `uv sync --extra gsas`（プレーン `uv sync` は禁止）。本タスクは GSAS-II 非依存のため `gsas` マーカー不要。
- 🔵 (note.md §5 テスト関連情報 / pyproject.toml)

---

## 5. テストケース実装時の日本語コメント指針

各テストに以下の形式で日本語コメントを付す（既存 `tests/test_persistent_store.py`（TASK-0013）/ `tests/test_snapshot.py` の慣習に準拠）。

### 永続 roundtrip（load/revert 等価復元）の標準形

```python
import json
import numpy as np
import pytest
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore
from tsumugin.store.persistent import PersistentLedger, PersistentSnapshotStore

# 【テスト目的】: save → 再オープン → load/revert で phases 等価復元を確認 (完了条件① / TC-106-03)
# 【テスト内容】: PersistentSnapshotStore へ 2 件 save し、別インスタンスで再オープンして load/revert
# 【期待される動作】: load(id).phases / revert(id) が保存時 phases と値等価
# 🔵 信頼性: 完了条件① / snapshot.py Snapshot / serialization.py roundtrip
def test_snapshot_save_reopen_load_revert_roundtrip(tmp_path):
    # 【テストデータ準備】: 逐次解析で確定する代表的な phases（相 1 個 → 2 個）
    # 【初期条件設定】: 空の snapshot JSONL パスから開始
    path = tmp_path / "snapshots.jsonl"
    st = PersistentSnapshotStore(path)
    p0 = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0), scale=1.0),)
    p1 = (PhaseInstance("A", LatticeParams(5.1, 5.1, 5.1), scale=0.8),
          PhaseInstance("B", LatticeParams(6.0, 6.0, 6.0)))
    st.save(p0, label="init")
    st.save(p1, label="stage")

    # 【実際の処理実行】: 同一パスを別インスタンスで再オープン（プロセス再起動相当）
    st2 = PersistentSnapshotStore(path)

    # 【結果検証】: load / revert が保存時 phases と等価
    assert st2.load("snap-0000").phases == p0        # 【確認内容】: load で phases 等価復元
    assert st2.revert("snap-0001") == p1              # 【確認内容】: revert で phases tuple 等価復元
    assert st2.load("snap-0001").parent_id == "snap-0000"  # 【確認内容】: parent_id 連結の復元
```

### ledger 連携 + 非破壊 revert の標準形

```python
# 【テスト目的】: revert で snapshot_revert が ledger に記録され snapshot ファイルは無変更 (完了条件⑤ / P2)
# 【テスト内容】: ledger 注入下で save → revert し、ledger 記録と snapshot ファイル無変更を確認
# 【期待される動作】: ledger に snapshot_revert 追記、snapshot JSONL のバイト列は不変
# 🔵 信頼性: 完了条件⑤ / snapshot.py L56-60
def test_snapshot_revert_records_ledger_and_file_unchanged(tmp_path):
    pl = PersistentLedger(tmp_path / "ledger.jsonl")
    snap_path = tmp_path / "snapshots.jsonl"
    st = PersistentSnapshotStore(snap_path, ledger=pl)
    st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="init")   # snap-0000
    before = snap_path.read_bytes()

    st.revert("snap-0000")                             # 【実際の処理実行】: 過去へ revert

    assert pl.entries[-1].kind == "snapshot_revert"    # 【確認内容】: revert が ledger に記録
    assert snap_path.read_bytes() == before            # 【確認内容】: snapshot ファイル無変更 (追記なし)
```

### エンジン無改変注入（TC-106-06）の標準形

```python
# 【テスト目的】: StagedRefinementEngine に PersistentSnapshotStore を注入して M0 経路が in-memory 版と等価 (TC-106-06 / REQ-012)
# 【テスト内容】: 同一入力で in-memory SnapshotStore 版と永続版を run し RefinementReport を比較
# 【期待される動作】: metrics / final_phases / escalated が等価、例外なく完走
# 🔵 信頼性: REQ-012 / TC-106-06 / staged.py L131,171,197
def test_persistent_snapshot_store_injectable_into_staged_engine(tmp_path):
    from tsumugin.backends.simulated import SimulatedBackend
    from tsumugin.refinement.staged import StagedRefinementEngine

    backend = SimulatedBackend()
    phases = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0)),)
    tt = np.arange(15.0, 60.0, 0.05)
    y = backend.simulate(phases, tt)

    rep_mem = StagedRefinementEngine(backend, SnapshotStore(), Ledger()).run(phases, tt, y)
    rep_pers = StagedRefinementEngine(
        backend, PersistentSnapshotStore(tmp_path / "snapshots.jsonl"), Ledger()).run(phases, tt, y)

    assert rep_pers.metrics == rep_mem.metrics                 # 【確認内容】: メトリクス等価 (決定論)
    assert rep_pers.final_phases == rep_mem.final_phases       # 【確認内容】: 最終 phases 等価
    assert rep_pers.escalated == rep_mem.escalated             # 【確認内容】: エスカレーション判定一致
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: 要件定義 §1（PersistentSnapshotStore の JSONL 永続化・再オープン復元/revert・store 最下層・serialization 共有）
- **参照した入力・出力仕様**: 要件定義 §2.1（__init__ 再オープン復元）、§2.2（save 追記 I/O + ledger 記録）、
  §2.3（load）、§2.4（revert 非破壊）、§2.5（snapshots / current_id）、§2.6（行スキーマ）、§2.7（データフロー）
- **参照した制約条件**: 要件定義 §3（追記モード限定 / 非破壊 revert / 同一契約・無改変注入 / phases 等価 / 決定論 /
  レイヤ制約 / 既存実装挙動不変 / 破損検出は非スコープ）
- **参照した使用例**: 要件定義 §4（永続保存・再オープン・注入 / 空新規ファイル / 空 phases / 未知 id / revert 後 save）
- **参照した受け入れ基準**: TC-106-03（N-01/N-02）、TC-106-05（B-01）、TC-106-06（N-06）
- **参照した完了条件**: ① N-01・N-02 / ② N-03 / ③ B-01 / ④ N-06 / ⑤ N-04・N-05
- **回帰ゲート（テスト外）**: `uv run pytest` 全体で既存テスト（M0/M1/M2 TASK-0011〜0013、`tests/test_snapshot.py` /
  `test_serialization.py` / `test_persistent_store.py` の PersistentLedger 14 件）を維持（新規テストのみ増加）。
  `snapshot.py` / `serialization.py` / `persistent.py::PersistentLedger` は挙動不変。

---

## 品質判定結果

- **テストケース分類**: 正常系 6 / 異常系（未知 id・新規空パス）2 / 境界値（API 不在・追記のみ・非破壊 revert・空 phases・current_id）5 を網羅 ✅
- **期待値定義**: 各ケースに具体的期待値（`load(id).phases == p` / `revert(id) == p` / `snap-000N` 連番 /
  `pytest.raises(KeyError)` / `not hasattr` / バイト列 `startswith`・無変更 / `RefinementReport` 等価）を明記 ✅
- **技術選択**: Python 3.12 + pytest（`tmp_path`）で確定。TC-106-06 のみ numpy + SimulatedBackend ✅
- **実装可能性**: 標準ライブラリ + 既存 `snapshot.py` / `serialization.py` / `persistent.py` の共有のみで確実に実現可能 ✅
- **信頼性レベル**: 🔵 10 / 🟡 3 / 🔴 0 — **✅ 高品質**
  - 🟡 が 3 件（E-02 新規ファイル生成タイミング / B-04 空 phases roundtrip / B-05 再オープン時 current_id を最新 save に設定）
    あるのは、設計文書が「JSONL 選定は 🟡」「current_id 復元挙動は実装確定」とする実装詳細に由来するため。いずれも要件へ遡及可能で曖昧さなし。

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-red m2-sequential TASK-0014` で Red フェーズ（失敗テスト作成）を開始します。
