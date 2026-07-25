from __future__ import annotations


from tsumugin.store.ledger import GENESIS_HASH, Ledger


def test_append_returns_entry_with_sequential_index():
    ledger = Ledger()
    e0 = ledger.append("refine", {"stage": "scale_bg"})
    e1 = ledger.append("guard", {"kind": "ok"})
    assert e0.index == 0
    assert e1.index == 1
    assert ledger.entries[-1] is e1


def test_hash_chain_links():
    ledger = Ledger()
    e0 = ledger.append("a", {"x": 1})
    e1 = ledger.append("b", {"y": 2})
    assert e0.prev_hash == GENESIS_HASH
    assert e1.prev_hash == e0.hash


def test_verify_true_for_valid_chain():
    ledger = Ledger()
    for i in range(5):
        ledger.append("k", {"i": i})
    assert ledger.verify() is True


def test_deterministic_hashes():
    def build():
        led = Ledger()
        led.append("refine", {"b": 2, "a": 1})
        led.append("guard", {"kind": "chi2_divergence"})
        return [e.hash for e in led.entries]

    assert build() == build()


def test_payload_order_independent_but_value_sensitive():
    l1 = Ledger()
    h1 = l1.append("k", {"a": 1, "b": 2}).hash
    l2 = Ledger()
    h2 = l2.append("k", {"b": 2, "a": 1}).hash  # same content, different key order
    assert h1 == h2  # canonical JSON sorts keys

    l3 = Ledger()
    h3 = l3.append("k", {"a": 1, "b": 3}).hash  # different value
    assert h3 != h1


def test_no_destructive_methods():
    ledger = Ledger()
    for name in ("delete", "clear", "pop", "remove", "update", "__delitem__"):
        assert not hasattr(ledger, name), f"Ledger must not expose {name} (P2)"


def test_entries_is_immutable_snapshot():
    ledger = Ledger()
    ledger.append("k", {"i": 0})
    snapshot = ledger.entries
    assert isinstance(snapshot, tuple)
    ledger.append("k", {"i": 1})
    # previously-returned tuple is unaffected by later appends
    assert len(snapshot) == 1


class TestConcurrentAppend:
    """NFR-105: 並行 append でもハッシュチェーンが壊れないこと (スレッド安全性)。

    【背景】: workbench の実 refine バックグラウンドジョブ (threading) と FastAPI
    threadpool の HTTP ハンドラが同一 Ledger へ並行 append し、ロック無し実装では
    index 重複 / prev_hash 断裂で verify()=False が実際に再現された (PR #138 レビュー)。
    本テストはロックを外すと確実に fail する (= 変異実証を兼ねる回帰ガード)。
    """

    def test_concurrent_appends_keep_chain_valid(self) -> None:
        import sys
        import threading

        # GIL の切替間隔を極小化して「index 読取 → 構築 → 追記」列の途中プリエンプションを
        # 確実に発生させる (既定 5ms では競合窓を踏まないことがあり、ガードが空振りする)
        prev_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        ledger = Ledger()
        n_threads, n_each = 32, 200
        barrier = threading.Barrier(n_threads)

        def worker(tid: int) -> None:
            barrier.wait()
            for i in range(n_each):
                ledger.append("concurrent", {"tid": tid, "i": i})

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        try:
            for th in threads:
                th.start()
            for th in threads:
                th.join()
        finally:
            sys.setswitchinterval(prev_interval)

        entries = ledger.entries
        assert len(entries) == n_threads * n_each
        assert [e.index for e in entries] == list(range(n_threads * n_each))
        assert ledger.verify() is True

    def test_persistent_concurrent_appends_keep_chain_valid(self, tmp_path) -> None:
        import threading

        from tsumugin.store.persistent import PersistentLedger

        import sys

        prev_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        ledger = PersistentLedger(tmp_path / "ledger.jsonl")
        n_threads, n_each = 8, 40
        barrier = threading.Barrier(n_threads)

        def worker(tid: int) -> None:
            barrier.wait()
            for i in range(n_each):
                ledger.append("concurrent", {"tid": tid, "i": i})

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        try:
            for th in threads:
                th.start()
            for th in threads:
                th.join()
        finally:
            sys.setswitchinterval(prev_interval)

        assert ledger.verify() is True
        # 再オープンでもチェーンが有効 (ファイル追記も直列化されている)
        reopened = PersistentLedger(tmp_path / "ledger.jsonl")
        assert reopened.verify() is True
        assert len(reopened.entries) == n_threads * n_each
