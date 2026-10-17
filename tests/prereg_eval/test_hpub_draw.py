"""P0 §3.2.1-3/4/11: drand の round からの抽出順と、salt 付きハッシュだけの public manifest (合成の ID だけ)。"""

from __future__ import annotations

import hashlib

import numpy as np

from tsumugin.prereg_eval.hpub_draw import draw_order, k_noref, public_manifest, seed_from_round

IDS = [f"R{n:06d}" for n in (40, 7, 300, 12, 5)]


def test_seed_follows_the_registered_formula():
    r = "abc123"
    assert seed_from_round(r, "h-pub") == int(hashlib.sha256(b"abc123:h-pub").hexdigest()[:8], 16)
    assert seed_from_round(r, "h-pub") != seed_from_round(r, "h-pub-noref")


def test_draw_order_sorts_by_numeric_id_then_permutes_with_numpy():
    order = draw_order(IDS, "abc123", "h-pub")
    ascending = sorted(IDS, key=lambda s: int(s[1:]))
    perm = np.random.default_rng(seed_from_round("abc123", "h-pub")).permutation(len(IDS))
    assert order == [ascending[i] for i in perm]


def test_draw_order_does_not_depend_on_input_order():
    assert draw_order(IDS, "r", "h-pub") == draw_order(list(reversed(IDS)), "r", "h-pub")


def test_k_noref_fills_to_k_and_is_capped_by_a_third_of_the_candidates():
    assert k_noref(n_ref=14, n_noref_candidates=738) == 16
    assert k_noref(n_ref=14, n_noref_candidates=30) == 10
    assert k_noref(n_ref=30, n_noref_candidates=738) == 0


def test_public_manifest_carries_only_salted_hashes_in_registered_order_and_counts():
    m = public_manifest("s3cret", ref_ids=IDS[:2], noref_ids=IDS[2:], counts={"drop_status": 3})
    text = repr(m)
    assert all(i not in text for i in IDS) and "s3cret" not in text
    want = [hashlib.sha256(("s3cret" + i).encode()).hexdigest() for i in sorted(IDS[:2], key=lambda s: int(s[1:]))]
    assert m["ref"]["salted_ids"] == want
    assert m["ref"]["n"] == 2 and m["noref"]["n"] == 3
    assert m["k_ref"] == 2 and m["k_noref"] == 1
    assert m["exclusion_counts"] == {"drop_status": 3}
