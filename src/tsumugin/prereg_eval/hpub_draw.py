"""P0 §3.2.1-3/4/11: `H-pub` の抽出順 (drand の round を種に) と、凍結時に commit する public の候補 manifest。

manifest に置くのは salt 付きの ID のハッシュ (``sha256(salt ‖ ID)``) と件数・除外理由の種類だけ。平文の ID と salt は
リポジトリの外の私的 ledger に置く。抽出の**順**は ID の数字部分の昇順 → ``default_rng(seed).permutation`` で決まり、
ハッシュの並びもその昇順で書く (抽出の後で第三者が順を再計算できるように)。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence

import numpy as np

from .hpub import salted_hash

#: 抽出数 K の既定 (P0 U8a)。
K_TOTAL = 30
#: 候補が抽出数の何倍以上なら抽出するか (P0 §3.2.1-2)。
CANDIDATE_FACTOR = 3


def seed_from_round(round_value: str, label: str) -> int:
    """``int(sha256("<r>:<label>")[:8], 16)`` (label は ``h-pub`` / ``h-pub-noref``)。"""
    return int(hashlib.sha256(f"{round_value}:{label}".encode("utf-8")).hexdigest()[:8], 16)


def _id_number(entry_id: str) -> int:
    m = re.search(r"(\d+)", entry_id)
    if m is None:
        raise ValueError(f"ID に数字部分がありません: {entry_id!r}")
    return int(m.group(1))


def ascending(ids: Sequence[str]) -> list[str]:
    """ID の数字部分の昇順 (同じ数字なら文字列順)。"""
    return sorted(ids, key=lambda s: (_id_number(s), s))


def draw_order(ids: Sequence[str], round_value: str, label: str) -> list[str]:
    """置換の順 (先頭から採り、使えない事例は次へ)。入力の並びに依らない。"""
    base = ascending(ids)
    perm = np.random.default_rng(seed_from_round(round_value, label)).permutation(len(base))
    return [base[int(i)] for i in perm]


def k_ref(n_ref: int, k: int = K_TOTAL) -> int:
    """参照ありの採用数: 候補が 3K に届かなければ全部、届けば K (§3.2.1-11)。"""
    return n_ref if n_ref < CANDIDATE_FACTOR * k else k


def k_noref(n_ref: int, n_noref_candidates: int, k: int = K_TOTAL) -> int:
    """参照なしの採用数: ``K − |H-pub-ref|`` を候補数の 1/3 で頭打ち (§3.2.1-11)。参照ありが足りれば 0。"""
    want = max(0, k - k_ref(n_ref, k))
    return min(want, n_noref_candidates // CANDIDATE_FACTOR)


def public_manifest(
    salt: str, ref_ids: Sequence[str], noref_ids: Sequence[str], counts: Mapping[str, int], k: int = K_TOTAL
) -> dict:
    """凍結時に commit する候補 manifest (平文の ID と salt を含まない)。"""
    return {
        "k_total": k,
        "k_ref": k_ref(len(ref_ids), k),
        "k_noref": k_noref(len(ref_ids), len(noref_ids), k),
        "ref": {"n": len(ref_ids), "salted_ids": [salted_hash(salt, i) for i in ascending(ref_ids)]},
        "noref": {"n": len(noref_ids), "salted_ids": [salted_hash(salt, i) for i in ascending(noref_ids)]},
        "exclusion_counts": dict(sorted(counts.items())),
        "order": "ID の数字部分の昇順。抽出は default_rng(int(sha256('<r>:h-pub' | '<r>:h-pub-noref')[:8], 16)).permutation",
    }
