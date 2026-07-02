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
