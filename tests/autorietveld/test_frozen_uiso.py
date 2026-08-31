"""ADP (Uiso) 凍結の語彙 — `free_uiso_labels=None/()` の型分離と `frozen_uiso_labels` (Issue #189/#211)。

`free_uiso_labels` は「未指定 (= 全原子解放)」と「明示的に空 (= 凍結)」を **型で** 分ける:

- ``None``  … 未指定。uiso 段で全原子を解放する (従来の既定挙動)
- ``()``    … 明示的に凍結。uiso 段で 1 原子も解放しない
- 非空      … その原子だけ解放する

旧実装は既定が ``()`` で、engine が ``info.get("uiso_labels") or info["labels"]`` と書いていたため
**「凍結したつもりが全原子解放」** になっていた (#189)。座標側には `frozen_coord_labels` があるのに
ADP 側に凍結語彙が無い非対称も併せて解消する (#211 = `frozen_uiso_labels`)。

numpy-only (GSAS 非依存)。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _update_atom_flags
from tsumugin.autorietveld.model import PhaseSpec


def _info(uiso_labels: list[str] | None, frozen_uiso: set[str] | None = None) -> dict:
    return {
        "labels": ["Cu", "C1", "N1", "O2A"],
        "coord_atoms": [],
        "mixed": set(),
        "free_occ": set(),
        "equiv_occ": set(),
        "uiso_labels": uiso_labels,
        "frozen_uiso": frozen_uiso or set(),
    }


def _u_flagged(info: dict) -> set[str]:
    flags: dict[str, str] = {}
    _update_atom_flags(flags, info, {"uiso": True})
    return {lab for lab, ch in flags.items() if "U" in ch}


# --- 型による意味の分離 (#189) ---


def test_default_free_uiso_labels_is_none_not_empty_tuple():
    """既定は `None` (未指定)。``()`` が既定だと「明示的に空」を表現できない。"""
    assert PhaseSpec("s.cif", "P").free_uiso_labels is None


def test_none_frees_all_atoms():
    """未指定 (`None`) は従来どおり全原子解放 — 逆向きの沈黙誤りを作らないこと。"""
    assert _u_flagged(_info(None)) == {"Cu", "C1", "N1", "O2A"}


def test_empty_tuple_freezes_every_atom():
    """★#189 の本体: 明示的な空は「1 原子も解放しない」。旧実装は全原子を解放していた。"""
    assert _u_flagged(_info([])) == set()


def test_non_empty_restricts_to_listed_atoms():
    """非空はその原子だけ (従来どおり)。"""
    assert _u_flagged(_info(["Cu"])) == {"Cu"}


# --- frozen_uiso_labels: frozen_coord_labels との対称性 (#211) ---


def test_frozen_uiso_labels_defaults_to_empty():
    assert PhaseSpec("s.cif", "P").frozen_uiso_labels == ()


def test_frozen_uiso_labels_excluded_from_all_atom_release():
    """未指定 (全原子解放) から凍結ラベルだけを差し引く。"""
    assert _u_flagged(_info(None, {"C1", "N1"})) == {"Cu", "O2A"}


def test_frozen_uiso_labels_win_over_free_uiso_labels():
    """両方に現れた原子は凍結が勝つ (`frozen_coord_labels` と同じ規約 = 凍結は硬い指定)。"""
    assert _u_flagged(_info(["Cu", "C1"], {"C1"})) == {"Cu"}


# --- ② JSON 往復 (③ は JSON しか送れない) ---


def test_roundtrip_distinguishes_none_from_empty():
    """★`to_dict`/`from_dict` が「未指定」と「明示的に空」を潰さないこと。

    旧 `from_dict` は ``d.get(...) or ()`` で **null も [] も同じ ()** にしていた。
    ここが潰れると ② 経由の呼び手 (③) は凍結を表現できない。
    """
    assert PhaseSpec.from_dict(PhaseSpec("s.cif", "P").to_dict()).free_uiso_labels is None
    frozen = PhaseSpec("s.cif", "P", free_uiso_labels=())
    assert PhaseSpec.from_dict(frozen.to_dict()).free_uiso_labels == ()
    listed = PhaseSpec("s.cif", "P", free_uiso_labels=("Cu",))
    assert PhaseSpec.from_dict(listed.to_dict()).free_uiso_labels == ("Cu",)


def test_roundtrip_carries_frozen_uiso_labels():
    spec = PhaseSpec("s.cif", "P", frozen_uiso_labels=("D1", "H1"))
    assert PhaseSpec.from_dict(spec.to_dict()).frozen_uiso_labels == ("D1", "H1")


def test_missing_key_means_unspecified_not_frozen():
    """キーが無い JSON (旧クライアント) は「未指定」= 全原子解放に倒す (後方互換)。"""
    d = {"structure_path": "s.cif", "phase_name": "P"}
    assert PhaseSpec.from_dict(d).free_uiso_labels is None
    assert PhaseSpec.from_dict(d).frozen_uiso_labels == ()
