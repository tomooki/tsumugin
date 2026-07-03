"""TASK-0013 store/persistent — PersistentLedger の TDD Red フェーズテスト。

JSONL 追記 + 再オープン検証 + 破損無修復（EDGE-003）を検証する。
対象実装（未実装）: tsumugin.store.persistent.PersistentLedger /
tsumugin.errors.LedgerIntegrityError。tmp_path フィクスチャで隔離ファイルを使う。
既存の tests/test_ledger.py のスタイルに準拠。
"""

from __future__ import annotations

import json

import pytest

from tsumugin.errors import LedgerIntegrityError
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.store.ledger import GENESIS_HASH, Ledger
from tsumugin.store.persistent import PersistentLedger
from tsumugin.store.snapshot import SnapshotStore

# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_append_reopen_verify_and_entries_match(tmp_path):
    # 【テスト目的】: append → 再オープン → verify() True + エントリ全量一致 (完了条件① / TC-106-01)
    # 【テスト内容】: PersistentLedger へ 2 件追記し、別インスタンスで再オープンして検証・突合
    # 【期待される動作】: verify() True、entries が書き込み全量と hash まで一致
    # 🔵 信頼性: 要件定義 §2.1/2.4 完了条件① / TC-106-01 / ledger.py Ledger.verify

    # 【テストデータ準備】: 逐次解析の代表的な監査エントリ 2 件を用意
    # 【初期条件設定】: 空の JSONL パスから開始
    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    e0 = pl.append("phase_accept", {"hyp": "hyp-0001", "rwp": 12.3})
    e1 = pl.append("snapshot_save", {"snapshot_id": "snap-0000", "n_phases": 2})

    # 【実際の処理実行】: 同一パスを別インスタンスで再オープン（プロセス再起動相当）
    # 【処理内容】: JSONL 各行 → LedgerEntry 再構築 → verify()
    pl2 = PersistentLedger(path)

    # 【結果検証】: 検証成功かつエントリ全量一致
    assert pl2.verify() is True  # 【確認内容】: 再オープン後もチェーンが健全
    assert pl2.entries == (e0, e1)  # 【確認内容】: index/kind/payload/prev_hash/hash 全量一致
    assert [e.to_dict() for e in pl2.entries] == [e0.to_dict(), e1.to_dict()]
    # 【確認内容】: to_dict() 表現でも書き込み全量と一致


def test_reopen_append_chain_links(tmp_path):
    # 【テスト目的】: 再オープン後の append で index 連番継続・prev_hash 連結・verify() True (TC-106-02)
    # 【テスト内容】: 1 件永続化 → 再オープン → 追記し、チェーン連結を確認
    # 【期待される動作】: 既存チェーン末尾から途切れなく追記できる (REQ-010(b))
    # 🔵 信頼性: 要件定義 §2.2 完了条件② / TC-106-02

    # 【テストデータ準備】: 「再起動して続きから記録する」実運用シナリオ
    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    pl.append("a", {"i": 0})

    # 【実際の処理実行】: 再オープン（既存 1 件）してさらに 1 件追記
    pl2 = PersistentLedger(path)
    e = pl2.append("b", {"i": 1})

    # 【結果検証】: 連番・prev_hash 連結・verify() True の 3 点が同時に成立
    assert e.index == 1  # 【確認内容】: index が連番継続
    assert e.prev_hash == pl2.entries[0].hash  # 【確認内容】: prev_hash が直前 hash に連結
    assert pl2.verify() is True  # 【確認内容】: 追記後もチェーンが健全

    # 【追加検証】: 3 回目のオープンでも一貫（永続化された 2 件が復元・検証される）
    pl3 = PersistentLedger(path)
    assert len(pl3.entries) == 2  # 【確認内容】: 永続化件数が 2
    assert pl3.verify() is True  # 【確認内容】: 再々オープンでも検証成功


def test_deterministic_hashes_match_in_memory_ledger(tmp_path):
    # 【テスト目的】: in-memory Ledger と同一 (kind, payload) 列で同一 hash 列（決定論） (完了条件⑤)
    # 【テスト内容】: 同じ操作列を Ledger と PersistentLedger に流し hash 列を突合
    # 【期待される動作】: _compute_hash/_canonical_json 共有により監査チェーンがビット同一
    # 🔵 信頼性: 要件定義 §3 決定論 / NFR-102 / ledger.py _compute_hash

    # 【テストデータ準備】: キー順の異なる payload を含む操作列
    ops = [("a", {"x": 1}), ("b", {"y": 2, "z": 3}), ("c", {})]
    mem = Ledger()
    for k, p in ops:
        mem.append(k, p)

    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    for k, p in ops:
        pl.append(k, p)

    # 【結果検証】: hash 列・prev_hash 列が完全一致
    assert [e.hash for e in pl.entries] == [e.hash for e in mem.entries]
    # 【確認内容】: 永続版と in-memory 版の hash 列がビット同一
    assert [e.prev_hash for e in pl.entries] == [e.prev_hash for e in mem.entries]
    # 【確認内容】: prev_hash 連結も一致


def test_new_path_opens_empty_and_first_append_creates_file(tmp_path):
    # 【テスト目的】: 不在パスで開くと空 ledger・verify() True、初回 append で新規作成 (要件定義 4.3)
    # 【テスト内容】: 未作成ファイルを破損扱いにせず、空チェーン (GENESIS 起点) として扱う
    # 【期待される動作】: オープン直後は entries==()、初回 append 後にファイル生成
    # 🟡 信頼性: 要件定義 4.3。新規ファイル生成タイミングは 🟡 具体化

    # 【テストデータ準備】: 存在しないパス（初回起動の境界）
    path = tmp_path / "new.jsonl"
    pl = PersistentLedger(path)

    # 【結果検証】: オープン直後は空 ledger で verify() True、ファイルは未作成
    assert pl.entries == ()  # 【確認内容】: 空チェーン
    assert pl.verify() is True  # 【確認内容】: 空でも検証成功 (GENESIS 起点)
    assert not path.exists()  # 【確認内容】: オープンのみではファイルを作らない (読み取りのみ)

    # 【実際の処理実行】: 初回 append でファイル新規作成
    pl.append("a", {})

    assert path.exists()  # 【確認内容】: 初回 append でファイルが作成される
    lines = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])  # 【確認内容】: 1 行目が json.loads 可能
    assert row["index"] == 0  # 【確認内容】: 初回エントリの index は 0
    assert row["prev_hash"] == GENESIS_HASH  # 【確認内容】: 初回 prev_hash は GENESIS


def test_jsonl_row_schema_matches_to_dict(tmp_path):
    # 【テスト目的】: JSONL 各行が LedgerEntry.to_dict() 準拠のスキーマであること (後続 TASK-0014 が依存)
    # 【テスト内容】: 1 件追記し、行のキー集合・値・hash 長・改行を検証
    # 【期待される動作】: 1 行 = 1 エントリの to_dict() 形式で永続化され json.loads で往復
    # 🔵 信頼性: 要件定義 §2.2/§6 / ledger.py LedgerEntry.to_dict

    # 【テストデータ準備】: ネスト dict を含む payload で行スキーマを固定
    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    pl.append("k", {"p": 1})

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    row = json.loads(lines[0])

    # 【結果検証】: キー集合・各値・hash 長・終端改行
    assert set(row) == {"index", "kind", "payload", "prev_hash", "hash"}
    # 【確認内容】: to_dict() と同一キー集合
    assert row["index"] == 0  # 【確認内容】: index
    assert row["kind"] == "k"  # 【確認内容】: kind
    assert row["payload"] == {"p": 1}  # 【確認内容】: payload がネスト dict のまま保存
    assert row["prev_hash"] == GENESIS_HASH  # 【確認内容】: 先頭 prev_hash は GENESIS
    assert len(row["hash"]) == 64  # 【確認内容】: sha256 hex 長 64
    assert text.endswith("\n")  # 【確認内容】: 1 行あたり改行 1 個で終端
    assert len(lines) == 1  # 【確認内容】: 1 件 = 1 行


def test_injectable_into_snapshot_store(tmp_path):
    # 【テスト目的】: SnapshotStore(ledger=pl) へ無改変注入し snapshot_save が JSONL へ追記 (REQ-012 スモーク)
    # 【テスト内容】: PersistentLedger を注入して save() し、再オープンで検証
    # 【期待される動作】: append(kind, payload) 契約が in-memory Ledger と一致し無改変注入できる
    # 🟡 信頼性: 要件定義 §3 REQ-012 / snapshot.py。SnapshotStore は in-memory のためスモーク

    # 【テストデータ準備】: 相 1 個を持つ最小スナップショット
    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    store = SnapshotStore(ledger=pl)

    # 【実際の処理実行】: SnapshotStore を無改変で使い save
    store.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="init")

    # 【結果検証】: snapshot_save が追記され、再オープンで検証できる
    assert pl.entries[-1].kind == "snapshot_save"  # 【確認内容】: 注入先が JSONL へ追記
    pl2 = PersistentLedger(path)
    assert pl2.verify() is True  # 【確認内容】: 再オープンで検証成功
    assert pl2.entries[-1].payload["snapshot_id"] == "snap-0000"
    # 【確認内容】: payload が正しく往復し snapshot_id を保持


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（破損検出・無修復、EDGE-003）
# ---------------------------------------------------------------------------


def test_tampered_hash_raises_integrity_error(tmp_path):
    # 【テスト目的】: 1 行の hash 改竄を再オープンで検出し LedgerIntegrityError を送出 (EDGE-003 / TC-106-04)
    # 【テスト内容】: 保存済み 2 行の 2 行目の hash を書き換えて再オープン
    # 【期待される動作】: 破損を沈黙せず LedgerIntegrityError を送出（True を返さない）
    # 🔵 信頼性: 要件定義 §2.1/4.4 / EDGE-003 / TC-106-04 / NFR-105

    # 【テストデータ準備】: 2 件追記後、2 行目の hash を全ゼロへ改竄
    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    pl.append("a", {"i": 0})
    pl.append("b", {"i": 1})

    lines = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[1])
    row["hash"] = "0" * 64
    lines[1] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 【結果検証】: 再オープンで LedgerIntegrityError を送出
    with pytest.raises(LedgerIntegrityError):  # 【確認内容】: 破損を沈黙せず明示エラー
        PersistentLedger(path)


def test_tampered_payload_raises_and_file_unchanged(tmp_path):
    # 【テスト目的】: payload 改竄を検出し、かつファイルを無変更に保つ (P2 無修復 / EDGE-003 / TC-106-04)
    # 【テスト内容】: 1 行の payload を書き換えた JSONL を再オープン
    # 【期待される動作】: LedgerIntegrityError 送出、ファイルのバイト列が無変更
    # 🔵 信頼性: 要件定義 §3 EDGE-003 / 4.4 無修復 / TC-106-04

    # 【テストデータ準備】: 保存済み 1 行の payload を改竄
    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    pl.append("a", {"i": 0})

    lines = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row["payload"] = {"i": 999}
    lines[0] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = path.read_bytes()  # 【初期条件設定】: 改竄後のバイト列を記録

    # 【実際の処理実行】: 破損ファイルを再オープン
    # 【結果検証】: 明示エラー + ファイル無変更
    with pytest.raises(LedgerIntegrityError):  # 【確認内容】: 破損を沈黙せず送出
        PersistentLedger(path)
    assert path.read_bytes() == before  # 【確認内容】: 修復・上書きしない (read のみ / P2)


def test_invalid_json_line_raises_integrity_error(tmp_path):
    # 【テスト目的】: 不正 JSON 行を LedgerIntegrityError に包む（明示エラー・無修復） (EDGE-003 の精神)
    # 【テスト内容】: json.loads 失敗する壊れた行を追記して再オープン
    # 【期待される動作】: JSONDecodeError を握り潰さず LedgerIntegrityError を送出、ファイル無変更
    # 🟡 信頼性: 要件定義 4.3/4.4。不正 JSON を包む方式は 🟡 具体化

    # 【テストデータ準備】: 正常 1 行の後に壊れた JSON 行を追記
    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    pl.append("a", {"i": 0})
    with open(path, "a", encoding="utf-8") as f:
        f.write("{ this is not valid json\n")
    before = path.read_bytes()

    # 【結果検証】: LedgerIntegrityError を送出し、ファイルは無変更
    with pytest.raises(LedgerIntegrityError):  # 【確認内容】: パース破損も明示エラー化
        PersistentLedger(path)
    assert path.read_bytes() == before  # 【確認内容】: 検出時に書き込まない (無修復)


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（API 不在・追記のみ・端点）
# ---------------------------------------------------------------------------


def test_no_destructive_methods(tmp_path):
    # 【テスト目的】: 削除・上書き・改変 API が存在しない（非破壊性を構造で保証） (P2 / TC-106-05)
    # 【テスト内容】: 破壊的メソッド名がいずれも hasattr False であることを確認
    # 【期待される動作】: append / entries / verify のみを持ち破壊的メソッドを持たない
    # 🔵 信頼性: 要件定義 §3 P2/REQ-401 / TC-106-05 / ledger.py Ledger

    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)

    # 【結果検証】: 破壊的属性の不在 + 追記のみの表面積
    for name in ("delete", "remove", "update", "overwrite", "clear", "pop", "truncate", "__delitem__"):
        assert not hasattr(pl, name), f"PersistentLedger must not expose {name} (P2)"
        # 【確認内容】: 破壊的 API を誤って足していないこと
    assert hasattr(pl, "append")  # 【確認内容】: 追記 API を持つ
    assert hasattr(pl, "entries")  # 【確認内容】: 読み取りプロパティを持つ
    assert hasattr(pl, "verify")  # 【確認内容】: 検証 API を持つ


def test_append_only_growth_prefix_unchanged(tmp_path):
    # 【テスト目的】: append 前後で先頭バイト列が不変（追記のみで成長） (NFR-203 / TC-106-07)
    # 【テスト内容】: 1 件追記後にバイト列を記録し、再追記後の先頭と比較
    # 【期待される動作】: after.startswith(before) かつ末尾のみ伸長
    # 🔵 信頼性: 要件定義 §3 NFR-203 / TC-106-07

    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    pl.append("a", {"i": 0})
    before = path.read_bytes()  # 【初期条件設定】: 追記前のバイト列

    pl.append("b", {"i": 1})  # 【実際の処理実行】: 追記モードで 1 行追加

    after = path.read_bytes()
    assert after.startswith(before)  # 【確認内容】: 既存バイト列が 1 バイトも変わらない
    assert len(after) > len(before)  # 【確認内容】: 末尾に 1 行増加
    added = after[len(before):]
    assert json.loads(added.decode("utf-8"))  # 【確認内容】: 追加分は json.loads 可能な 1 行


def test_empty_ledger_verify_true(tmp_path):
    # 【テスト目的】: エントリ 0 件（空 ledger）の verify() True（下限境界） (要件定義 4.3)
    # 【テスト内容】: append しない空 ledger を検証
    # 【期待される動作】: 空チェーン（GENESIS のみ）で矛盾なく verify() True
    # 🔵 信頼性: 要件定義 4.3 / ledger.py Ledger.verify 空リスト True

    path = tmp_path / "empty.jsonl"
    pl = PersistentLedger(path)

    # 【結果検証】: 空でも例外・False を出さない
    assert pl.entries == ()  # 【確認内容】: エントリ 0 件
    assert pl.verify() is True  # 【確認内容】: 空チェーンの検証は True


def test_single_entry_reopen_verify(tmp_path):
    # 【テスト目的】: エントリ 1 件の再オープン検証（最小の永続チェーン） (要件定義 §2.1/2.4)
    # 【テスト内容】: 1 件追記 → 再オープンして GENESIS 連結と一致を確認
    # 【期待される動作】: 1 件でも prev_hash==GENESIS かつ hash 整合で verify() True
    # 🔵 信頼性: 要件定義 §2.1/2.4 / ledger.py GENESIS_HASH

    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    pl.append("solo", {"v": 1})

    pl2 = PersistentLedger(path)

    # 【結果検証】: 単一エントリの GENESIS 連結が保持される
    assert pl2.entries[0].index == 0  # 【確認内容】: index は 0
    assert pl2.entries[0].prev_hash == GENESIS_HASH  # 【確認内容】: prev_hash は GENESIS
    assert pl2.verify() is True  # 【確認内容】: 1 件でも検証成功
    assert pl2.entries[0] == pl.entries[0]  # 【確認内容】: 再オープンでエントリが完全一致


def test_trailing_blank_line_skipped(tmp_path):
    # 【テスト目的】: 末尾の空行・改行のみの行はスキップし破損扱いにしない（正常系の頑健性） (要件定義 §2.1-4)
    # 【テスト内容】: 1 件追記後に余分な空行を足して再オープン
    # 【期待される動作】: 末尾空行を無視して verify() True・エントリ数が正しい
    # 🟡 信頼性: 要件定義 §2.1-4/4.3。空行スキップ方式は 🟡 具体化

    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    pl.append("a", {"i": 0})
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n")  # 【テストデータ準備】: 余分な空行（追記の副産物）

    pl2 = PersistentLedger(path)

    # 【結果検証】: 空行は無視され破損扱いにならない（E-03 の不正 JSON とは区別）
    assert pl2.verify() is True  # 【確認内容】: 末尾空行があっても検証成功
    assert len(pl2.entries) == 1  # 【確認内容】: 空行を除いたエントリ数が正しい


# ---------------------------------------------------------------------------
# TASK-0014: PersistentSnapshotStore (未実装) の TDD Red フェーズテスト（13 件）
#
# 対象実装（未実装）: tsumugin.store.persistent.PersistentSnapshotStore
#   SnapshotStore (store/snapshot.py) と同一契約 (save/load/revert/snapshots/current_id)
#   を持つ JSONL 永続版。phases は serialization.phase_to_dict/phase_from_dict で相互変換。
# 既存の PersistentLedger テスト 14 件は変更しない（本セクションは追記のみ）。
# PersistentSnapshotStore は未実装のため、各テストは関数内 import の ImportError で失敗する
# （モジュール収集は成立し、既存 14 件は pass のまま = Red フェーズの分離失敗）。
# 内訳: 正常系 N-01〜N-06 / 異常系 E-01〜E-02 / 境界値 B-01〜B-05。
# ---------------------------------------------------------------------------


def test_snapshot_save_reopen_load_roundtrip(tmp_path):
    # 【テスト目的】: save → 再オープン → load(id) で phases 等価復元を確認 (完了条件① / TC-106-03)
    # 【テスト内容】: 2 件 save し別インスタンスで同一パスを再オープンして load(id) を検証
    # 【期待される動作】: load(id).phases が保存時 phases と値等価・parent_id/label も復元
    # 🔵 信頼性レベル: 要件定義 §2.1/2.3 完了条件① / TC-106-03 / serialization roundtrip
    from tsumugin.store.persistent import PersistentSnapshotStore

    # 【テストデータ準備】: 逐次解析で確定する代表 phases（相 1 個 → 相 2 個へ変化）
    # 【初期条件設定】: 空の snapshot JSONL パスから開始
    path = tmp_path / "snapshots.jsonl"
    st = PersistentSnapshotStore(path)
    p0 = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0), scale=1.0),)
    p1 = (
        PhaseInstance("A", LatticeParams(5.1, 5.1, 5.1), scale=0.8),
        PhaseInstance("B", LatticeParams(6.0, 6.0, 6.0)),
    )
    st.save(p0, label="init")   # snap-0000
    st.save(p1, label="stage")  # snap-0001

    # 【実際の処理実行】: 同一パスを別インスタンスで再オープン（プロセス再起動相当）
    st2 = PersistentSnapshotStore(path)

    # 【結果検証】: load が保存時 phases・parent_id・label を等価復元
    assert st2.load("snap-0000").phases == p0  # 【確認内容】: 単相 phases 等価復元
    assert st2.load("snap-0001").phases == p1  # 【確認内容】: 複数相 phases も等価復元
    assert st2.load("snap-0001").label == "stage"  # 【確認内容】: label が復元される
    assert st2.load("snap-0001").parent_id == "snap-0000"  # 【確認内容】: parent_id 連結復元


def test_snapshot_reopen_revert_returns_phases_and_moves_current(tmp_path):
    # 【テスト目的】: 再オープン → revert(id) で phases tuple 等価復元・current_id 移動 (完了条件①)
    # 【テスト内容】: 2 件 save → 再オープン → 過去 snapshot へ非破壊 revert
    # 【期待される動作】: revert(id) が保存時 phases を返し current_id が移るが履歴は縮小しない
    # 🔵 信頼性レベル: 要件定義 §2.4 完了条件① / TC-106-03 / snapshot.py L53-61
    from tsumugin.store.persistent import PersistentSnapshotStore

    path = tmp_path / "snapshots.jsonl"
    st = PersistentSnapshotStore(path)
    p0 = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0)),)
    p1 = (PhaseInstance("A", LatticeParams(5.1, 5.1, 5.1)),)
    st.save(p0, label="init")
    st.save(p1, label="stage")

    # 【実際の処理実行】: 再オープンして過去状態へ revert
    st2 = PersistentSnapshotStore(path)
    reverted = st2.revert("snap-0000")

    assert reverted == p0  # 【確認内容】: revert が phases tuple を等価復元
    assert st2.current_id == "snap-0000"  # 【確認内容】: current_id が revert 先へ移動
    assert len(st2.snapshots) == 2  # 【確認内容】: revert は前方履歴を消さない


def test_snapshot_id_sequence_continues_across_reopen(tmp_path):
    # 【テスト目的】: snapshot ID 連番が再オープン跨ぎで継続する (完了条件②)
    # 【テスト内容】: save(snap-0000) → 再オープン → save(snap-0001) の連番継続を確認
    # 【期待される動作】: 復元数から連番継続・parent_id 連結・件数一貫
    # 🔵 信頼性レベル: 要件定義 §2.1/2.2 完了条件② / snapshot.py L31 snap-{len:04d}
    from tsumugin.store.persistent import PersistentSnapshotStore

    path = tmp_path / "snapshots.jsonl"
    st = PersistentSnapshotStore(path)
    st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="a")  # snap-0000

    # 【実際の処理実行】: 再オープン（既存 1 件）してさらに save
    st2 = PersistentSnapshotStore(path)
    s = st2.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="b")  # snap-0001

    assert s.id == "snap-0001"  # 【確認内容】: 連番が再オープン跨ぎで継続
    assert s.parent_id == "snap-0000"  # 【確認内容】: parent_id が直前 snapshot に連結
    assert len(st2.snapshots) == 2  # 【確認内容】: 復元 1 + 新規 1 = 2 件

    # 【追加検証】: 3 回目のオープンでも id 列が一貫して復元される
    st3 = PersistentSnapshotStore(path)
    assert [snap.id for snap in st3.snapshots] == ["snap-0000", "snap-0001"]
    # 【確認内容】: 永続化された id 列が復元される


def test_snapshot_save_records_ledger_snapshot_save(tmp_path):
    # 【テスト目的】: ledger 注入下の save で snapshot_save が記録される (完了条件⑤)
    # 【テスト内容】: PersistentLedger 注入で save → payload 一致と ledger 再オープン検証
    # 【期待される動作】: snapshot_save の payload が in-memory 版と一致・再オープンで verify True
    # 🔵 信頼性レベル: 要件定義 §2.2 完了条件⑤ / snapshot.py L38-48
    from tsumugin.store.persistent import PersistentSnapshotStore

    snap_path = tmp_path / "snapshots.jsonl"
    led_path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(led_path)
    st = PersistentSnapshotStore(snap_path, ledger=pl)
    st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="init")

    assert pl.entries[-1].kind == "snapshot_save"  # 【確認内容】: save が ledger へ記録
    assert pl.entries[-1].payload == {
        "snapshot_id": "snap-0000",
        "label": "init",
        "parent_id": None,
        "n_phases": 1,
    }  # 【確認内容】: payload が in-memory SnapshotStore と同一契約

    # 【追加検証】: 注入 ledger の再オープンで永続化と検証が成立
    pl2 = PersistentLedger(led_path)
    assert pl2.verify() is True  # 【確認内容】: 注入 ledger 再オープンで検証成功
    assert pl2.entries[-1].payload["snapshot_id"] == "snap-0000"  # 【確認内容】: payload 往復


def test_snapshot_revert_records_ledger_and_file_unchanged(tmp_path):
    # 【テスト目的】: revert で snapshot_revert が ledger に記録され snapshot ファイルは無変更 (完了条件⑤/P2)
    # 【テスト内容】: ledger 注入下で save → revert し ledger 記録とファイル無変更を確認
    # 【期待される動作】: ledger に snapshot_revert 追記、snapshot JSONL のバイト列は不変
    # 🔵 信頼性レベル: 要件定義 §2.4/§3 完了条件⑤ / snapshot.py L56-60
    from tsumugin.store.persistent import PersistentSnapshotStore

    pl = PersistentLedger(tmp_path / "ledger.jsonl")
    snap_path = tmp_path / "snapshots.jsonl"
    st = PersistentSnapshotStore(snap_path, ledger=pl)
    st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="init")  # snap-0000
    before = snap_path.read_bytes()

    # 【実際の処理実行】: 過去へ revert（状態遷移でありデータ追加ではない）
    st.revert("snap-0000")
    after = snap_path.read_bytes()

    assert pl.entries[-1].kind == "snapshot_revert"  # 【確認内容】: revert が ledger へ記録
    assert pl.entries[-1].payload == {"snapshot_id": "snap-0000", "label": "init"}
    # 【確認内容】: revert payload が in-memory SnapshotStore と同一
    assert after == before  # 【確認内容】: snapshot ファイルは追記されず無変更（非破壊 revert）


def test_persistent_snapshot_store_injectable_into_staged_engine(tmp_path):
    # 【テスト目的】: StagedRefinementEngine へ無改変注入で M0 経路が in-memory 版と等価 (TC-106-06/REQ-012)
    # 【テスト内容】: 同一入力で in-memory 版と永続版を run し RefinementReport を比較
    # 【期待される動作】: metrics/final_phases/escalated 等価・例外なく完走・snapshot 永続化
    # 🔵 信頼性レベル: 要件定義 §3 REQ-012 / TC-106-06 / staged.py L131,171,197
    import numpy as np

    from tsumugin.backends.simulated import SimulatedBackend
    from tsumugin.refinement.staged import StagedRefinementEngine
    from tsumugin.store.persistent import PersistentSnapshotStore

    backend = SimulatedBackend()
    phases = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0)),)
    tt = np.arange(15.0, 60.0, 0.05)
    y = backend.simulate(phases, tt)

    # 【基準】: in-memory SnapshotStore 版で run
    rep_mem = StagedRefinementEngine(backend, SnapshotStore(), Ledger()).run(phases, tt, y)

    # 【差し替え】: 永続版 PersistentSnapshotStore を無改変注入して run
    snap_path = tmp_path / "snapshots.jsonl"
    rep_pers = StagedRefinementEngine(
        backend, PersistentSnapshotStore(snap_path), Ledger()
    ).run(phases, tt, y)

    assert rep_pers.metrics == rep_mem.metrics  # 【確認内容】: メトリクス等価（決定論）
    assert rep_pers.final_phases == rep_mem.final_phases  # 【確認内容】: 最終 phases 等価
    assert rep_pers.escalated == rep_mem.escalated  # 【確認内容】: エスカレーション判定一致

    # 【追加検証】: snapshot が永続化され再オープンで復元できる
    assert snap_path.exists()  # 【確認内容】: run 実行で snapshot JSONL が生成される
    assert len(PersistentSnapshotStore(snap_path).snapshots) > 0  # 【確認内容】: 再オープンで非空復元


def test_load_and_revert_unknown_id_raises_keyerror(tmp_path):
    # 【テスト目的】: 未知 snapshot_id への load/revert が KeyError（in-memory と同一縮退）(E-01)
    # 【テスト内容】: 1 件のみ save 後、存在しない id を load/revert
    # 【期待される動作】: いずれも KeyError を送出し沈黙 None を返さない
    # 🔵 信頼性レベル: 要件定義 §2.3/2.4/§4.4 / snapshot.py L50-54 self._index[snapshot_id]
    from tsumugin.store.persistent import PersistentSnapshotStore

    st = PersistentSnapshotStore(tmp_path / "snapshots.jsonl")
    st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="init")  # snap-0000 のみ

    with pytest.raises(KeyError):  # 【確認内容】: 未知 id の load は KeyError
        st.load("snap-9999")
    with pytest.raises(KeyError):  # 【確認内容】: 未知 id の revert は KeyError
        st.revert("snap-9999")


def test_new_path_opens_empty_and_first_save_creates_file(tmp_path):
    # 【テスト目的】: 新規/空パスは空ストア・初回 save でファイル新規作成 (E-02)
    # 【テスト内容】: 不在パスで開き、オープン直後の状態と初回 save 後のファイルを確認
    # 【期待される動作】: オープンのみではファイルを作らず、初回 save で 1 行追記作成
    # 🟡 信頼性レベル: 要件定義 §4.3。新規ファイル生成タイミングは 🟡 具体化
    from tsumugin.store.persistent import PersistentSnapshotStore

    path = tmp_path / "new.jsonl"
    st = PersistentSnapshotStore(path)

    assert st.snapshots == ()  # 【確認内容】: オープン直後は空ストア
    assert st.current_id is None  # 【確認内容】: 未 save の current_id は None
    assert not path.exists()  # 【確認内容】: オープンのみではファイルを作らない（読み取りのみ）

    # 【実際の処理実行】: 初回 save でファイル新規作成
    st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="init")

    assert path.exists()  # 【確認内容】: 初回 save でファイルが作成される
    lines = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])  # 【確認内容】: 1 行目が json.loads 可能
    assert row["id"] == "snap-0000"  # 【確認内容】: 初回 snapshot id は snap-0000
    assert row["parent_id"] is None  # 【確認内容】: 初回 parent_id は None


def test_no_destructive_methods_and_same_surface_as_in_memory(tmp_path):
    # 【テスト目的】: 削除・上書き API 不在・in-memory と同一属性集合 (完了条件③ / TC-106-05)
    # 【テスト内容】: 破壊的メソッド名の hasattr 否定と公開メソッド集合の一致を確認
    # 【期待される動作】: save/load/revert/snapshots/current_id のみを持ち破壊的 API を持たない
    # 🔵 信頼性レベル: 要件定義 §3 P2/REQ-401 / TC-106-05 / snapshot.py SnapshotStore
    from tsumugin.store.persistent import PersistentSnapshotStore

    st = PersistentSnapshotStore(tmp_path / "snapshots.jsonl")

    destructive = (
        "delete", "remove", "update", "overwrite",
        "clear", "pop", "truncate", "__delitem__",
    )
    for name in destructive:
        assert not hasattr(st, name), f"PersistentSnapshotStore must not expose {name} (P2)"
        # 【確認内容】: 破壊的 API を誤って足していないこと
    for name in ("save", "load", "revert", "snapshots", "current_id"):
        assert hasattr(st, name)  # 【確認内容】: in-memory SnapshotStore と同一表面積


def test_snapshot_append_only_growth_prefix_unchanged(tmp_path):
    # 【テスト目的】: save 前後で先頭バイト列が不変（追記のみで成長）(NFR-203)
    # 【テスト内容】: 1 件 save 後にバイト列を記録し、再 save 後の先頭と比較
    # 【期待される動作】: after.startswith(before) かつ末尾に 1 行増加
    # 🔵 信頼性レベル: 要件定義 §3 NFR-203 / persistent.py PersistentLedger.append 追記パターン
    from tsumugin.store.persistent import PersistentSnapshotStore

    path = tmp_path / "snapshots.jsonl"
    st = PersistentSnapshotStore(path)
    st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="a")  # snap-0000
    before = path.read_bytes()

    st.save((PhaseInstance("B", LatticeParams(6, 6, 6)),), label="b")  # snap-0001（追記）
    after = path.read_bytes()

    assert after.startswith(before)  # 【確認内容】: 既存バイト列が 1 バイトも変わらない
    assert len(after) > len(before)  # 【確認内容】: 末尾に 1 行増加
    added = after[len(before):]
    assert json.loads(added.decode("utf-8"))  # 【確認内容】: 追加分は json.loads 可能な 1 行


def test_revert_is_non_destructive_and_keeps_forward_history(tmp_path):
    # 【テスト目的】: revert は snapshot JSONL に追記せず前方履歴を消さない (REQ-011 / P2)
    # 【テスト内容】: 2 件 save → revert → save し、ファイル無変更・件数・分岐連結を確認
    # 【期待される動作】: revert 後もファイル不変・件数不変、revert 後 save は新規 id を発番
    # 🔵 信頼性レベル: 要件定義 §2.4/§3 REQ-011/P2 / snapshot.py L53-61
    from tsumugin.store.persistent import PersistentSnapshotStore

    path = tmp_path / "snapshots.jsonl"
    st = PersistentSnapshotStore(path)  # ledger なし（ファイル観点に集中）
    st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="a")  # snap-0000
    st.save((PhaseInstance("B", LatticeParams(6, 6, 6)),), label="b")  # snap-0001
    before = path.read_bytes()

    st.revert("snap-0000")  # 【実際の処理実行】: 過去へ現在位置を移す
    after = path.read_bytes()

    assert after == before  # 【確認内容】: revert は snapshot ファイルへ追記しない
    assert st.current_id == "snap-0000"  # 【確認内容】: current_id が revert 先へ移動
    assert len(st.snapshots) == 2  # 【確認内容】: revert では履歴が消えない

    # 【追加検証】: revert 後の save は新規 id を発番し分岐を追記保持
    s2 = st.save((PhaseInstance("C", LatticeParams(7, 7, 7)),), label="c")
    assert s2.id == "snap-0002"  # 【確認内容】: 連番継続（revert で巻き戻らない）
    assert s2.parent_id == "snap-0000"  # 【確認内容】: revert 位置が親になる
    assert len(st.snapshots) == 3  # 【確認内容】: 分岐が追記で保持される


def test_empty_phases_snapshot_roundtrip(tmp_path):
    # 【テスト目的】: 空 phases（n_phases=0）の save/reopen/load/revert 成立 (B-04)
    # 【テスト内容】: save((), label=...) → 再オープンで空タプル復元・ledger n_phases=0
    # 【期待される動作】: 空 phases が [] として直列化され () へ復元される
    # 🟡 信頼性レベル: 要件定義 §4.3 空 phases。空配列 roundtrip は妥当な推測
    from tsumugin.store.persistent import PersistentSnapshotStore

    path = tmp_path / "snapshots.jsonl"
    pl = PersistentLedger(tmp_path / "ledger.jsonl")
    st = PersistentSnapshotStore(path, ledger=pl)
    s = st.save((), label="empty")  # phases 空タプル

    assert s.phases == ()  # 【確認内容】: 空 phases の Snapshot を構築
    assert pl.entries[-1].payload["n_phases"] == 0  # 【確認内容】: ledger の n_phases は 0

    # 【実際の処理実行】: 再オープンで空タプルが復元される
    st2 = PersistentSnapshotStore(path)
    assert st2.load("snap-0000").phases == ()  # 【確認内容】: load で空タプル復元
    assert st2.revert("snap-0000") == ()  # 【確認内容】: revert で空タプル復元


def test_current_id_initial_and_reopen_value(tmp_path):
    # 【テスト目的】: current_id の初期値(None)・save 後(最新)・再オープン後(最新) (B-05)
    # 【テスト内容】: 未 save/save 後/再オープン後の current_id と後続 save の parent_id 連結
    # 【期待される動作】: 未 save は None、以後は最新 save の id を指し parent_id 連結が成立
    # 🟡 信頼性レベル: 要件定義 §2.1/2.5。再オープン時 current_id を最新 save に設定は 🟡 設計判断
    from tsumugin.store.persistent import PersistentSnapshotStore

    path = tmp_path / "snapshots.jsonl"
    st = PersistentSnapshotStore(path)
    assert st.current_id is None  # 【確認内容】: 未 save の current_id は None

    st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="a")  # snap-0000
    st.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="b")  # snap-0001
    assert st.current_id == "snap-0001"  # 【確認内容】: save 後は最新 id を指す

    # 【実際の処理実行】: 再オープンで current_id が最新 save を指す
    st2 = PersistentSnapshotStore(path)
    assert st2.current_id == "snap-0001"  # 【確認内容】: 再オープン後も最新 save を指す
    s = st2.save((PhaseInstance("A", LatticeParams(5, 5, 5)),), label="c")  # snap-0002
    assert s.parent_id == "snap-0001"  # 【確認内容】: 後続 save が最新へ連結
