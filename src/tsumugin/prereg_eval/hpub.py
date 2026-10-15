"""P0 §3.2.1-2: `H-pub` の候補一覧の規則 (純関数)。

**読んでよいもの** (P0 v1.3): RRUFF のヘッダの ``NAMES``・``RRUFFID``・``IDEAL CHEMISTRY``・``STATUS``・``FILETYPE`` と 2θ の軸
(範囲・刻み・単調性) だけ。``CELL PARAMETERS`` (粉末から精密化したセル = そのパターンの答えの一部) と ``MEASURED CHEMISTRY`` は読まない。
強度は持たない (`RawHeader` に入れない)。COD はメタデータと、CIF をスクリプトで検査した結果 (esd の有無・温度圧力のタグ・空間群) だけ。

ここにあるのは規則そのもの。スナップショットを読んで候補を作る実行部は `docs/benchmark/fit-then-judge-hpub/` (凍結版に含める)。
"""

from __future__ import annotations

import hashlib
import re
import shlex
import statistics
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from .synth import composition_fractions

__all__ = [
    "STATUS_CONFIRMED",
    "atom_site_rows",
    "cif_tags",
    "cod_revision",
    "free_coordinate_count",
    "has_all_free_esds",
    "RawHeader",
    "decode_raw",
    "is_room_conditions",
    "normalize_mineral",
    "parse_raw_header",
    "profile_shape_ok",
    "publication_key",
    "rruff_fractions",
    "salted_hash",
]

#: 同定が確認済みを表す ``STATUS`` (完全一致。G1 の確認で見た値の分布から — P0 §3.2.1-2)
STATUS_CONFIRMED: tuple[str, ...] = (
    "The identification of this mineral has been confirmed by X-ray diffraction and chemical analysis",
    "The identification of this mineral has been confirmed by single-crystal X-ray diffraction",
    "The identification of this mineral is confirmed by single-crystal X-ray diffraction and chemical analysis",
    "The identification of this mineral has been confirmed only by single crystal X-ray diffraction",
    "The identification of this mineral has been confirmed by X-ray diffraction",
    "The identification of this mineral has been confirmed only by X-ray diffraction",
)

_ALLOWED = {"NAMES": "names", "RRUFFID": "rruff_id", "IDEAL CHEMISTRY": "ideal_chemistry", "STATUS": "status",
            "FILETYPE": "filetype"}


@dataclass(frozen=True)
class RawHeader:
    names: str
    rruff_id: str
    ideal_chemistry: str
    status: str
    filetype: str
    x_start: float | None
    x_end: float | None
    step: float | None
    monotonic: bool
    n_points: int


def decode_raw(data: bytes) -> str:
    """RRUFF のファイルは UTF-8 (``·`` などを含む)。UTF-8 で読めなければ latin-1。"""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def parse_raw_header(text: str) -> RawHeader:
    """許されたヘッダ項目と 2θ の軸の統計だけを返す (強度・他の項目は捨てる)。"""
    fields = dict.fromkeys(_ALLOWED.values(), "")
    xs: list[float] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            body = s.lstrip("#").strip()
            key, _, val = body.partition("=")
            attr = _ALLOWED.get(key.strip().upper())
            if attr:
                fields[attr] = val.strip()
            continue
        first = re.split(r"[,\s]+", s, maxsplit=1)[0]
        try:
            xs.append(float(first))
        except ValueError:
            continue
    diffs = [b - a for a, b in zip(xs, xs[1:])]
    return RawHeader(
        **fields,
        x_start=xs[0] if xs else None,
        x_end=xs[-1] if xs else None,
        step=statistics.median(diffs) if diffs else None,
        monotonic=bool(diffs) and all(d > 0 for d in diffs),
        n_points=len(xs),
    )


def profile_shape_ok(h: RawHeader) -> bool:
    """RRUFF の標準の測定条件: 単調増加・開始 4.5–10.5°・終了 79.5–90.5°・刻み 0.010 ± 0.002°。"""
    if h.x_start is None or h.x_end is None or h.step is None or not h.monotonic:
        return False
    return 4.5 <= h.x_start <= 10.5 and 79.5 <= h.x_end <= 90.5 and abs(h.step - 0.010) <= 0.002


def normalize_mineral(name: str) -> str:
    """NFKD で分解して結合文字を除き、小文字にし、空白・ハイフン・アポストロフィを除く。"""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    return re.sub(r"[\s\-'’`]", "", stripped)


_HYDRATE = re.compile(r"[·•]\s*(\d*\.?\d*)\s*(.+)$")


def rruff_fractions(ideal: str) -> dict[str, float] | None:
    """RRUFF の ``IDEAL CHEMISTRY`` を H を除いた原子数の割合に。一意な量に直せなければ None。

    電荷 ``^2+^`` は捨て、下付き ``_4_`` は数に戻す。水和 ``·5H_2_O`` は係数を掛けて足す (係数が文字なら None)。
    席の混合 (コンマ)・変数・空孔 (□)・REE などの総称は `synth.composition_fractions` が None にする。
    """
    s = re.sub(r"\^[^^]*\^", "", ideal).replace("_", "").strip()
    s = s.translate(str.maketrans("[]{}", "()()"))  # 角括弧・波括弧は丸括弧と同じ (群のまとまり)
    m = _HYDRATE.search(s)
    parts = [s]
    if m:
        coef, body = m.group(1), m.group(2)
        if not re.fullmatch(r"[A-Za-z0-9.()]+", body):  # 係数が文字 (n·H2O) なら body 側が元素でなくなり None
            return None
        parts = [s[: m.start()], f"({body}){coef or 1}"]
    if re.search(r"[·•]", parts[0]):
        return None
    return composition_fractions(" ".join(parts))


_ROOM_T = (273.0, 313.0)
_MAX_P_KPA = 1000.0
_TITLE_WORDS = ("gpa", "high-pressure", "high pressure", "high-temperature", "high temperature",
                "low-temperature", "low temperature", "°c")


def _num(text: object) -> float | None:
    if text is None:
        return None
    t = re.sub(r"\(.*?\)", "", str(text)).strip()
    try:
        return float(t)
    except ValueError:
        return None


def is_room_conditions(meta: Mapping[str, object], cif_tags: Mapping[str, object], title: str) -> bool:
    """常温常圧か。どこにも記録が無ければ常温常圧とみなす (P0 §3.2.1-2 の限界として記録済み)。"""
    for key in ("celltemp", "diffrtemp"):
        t = _num(meta.get(key))
        if t is not None and not (_ROOM_T[0] <= t <= _ROOM_T[1]):
            return False
    for key in ("cellpressure", "diffrpressure"):
        p = _num(meta.get(key))
        if p is not None and p > _MAX_P_KPA:
            return False
    for key in ("_cell_measurement_temperature", "_diffrn_ambient_temperature"):
        t = _num(cif_tags.get(key))
        if t is not None and not (_ROOM_T[0] <= t <= _ROOM_T[1]):
            return False
    for key in ("_cell_measurement_pressure", "_diffrn_ambient_pressure"):
        p = _num(cif_tags.get(key))
        if p is not None and p > _MAX_P_KPA:
            return False
    low = (title or "").lower()
    return not any(w in low for w in _TITLE_WORDS)


def publication_key(meta: Mapping[str, object]) -> str | None:
    """別出版物の判定の鍵: DOI (小文字) → 表題 (小文字・英数字だけ) → (雑誌名・年・巻・最初のページ)。決まらなければ None。"""
    doi = str(meta.get("doi") or "").strip()
    if doi:
        return "doi:" + doi.lower()
    title = re.sub(r"[^a-z0-9]", "", str(meta.get("title") or "").lower())
    if title:
        return "title:" + title
    cite = [str(meta.get(k) or "").strip() for k in ("journal", "year", "volume", "firstpage")]
    if all(cite):
        return "cite:" + "|".join(cite)
    return None


#: P0 §3.2.1-1 で固定したスナップショット (リポジトリの外。`S-eval` の母集団も COD の同じスナップショット — §6.3)
SNAPSHOT_SHA256 = {
    "rruff_dl/XY_RAW.zip": "948a133482bb3c99da80194cc2848933aee668129beb209150f7f850cd4b0587",
    "cod_dl/cod_all.csv": "95f08e5dc85aaef0b0f020e148b46b4ba85977074c8c34d1987db9cc7ab9ecac",
}


def salted_hash(salt: str, entry_id: str) -> str:
    """public の抽出 manifest に置く ID のハッシュ ``sha256(salt ‖ ID)``。"""
    return hashlib.sha256((salt + entry_id).encode("utf-8")).hexdigest()


# --- CIF の検査 (値は表示しない — 有無と件数だけを返す) ----------------------------------------


def _loops(text: str) -> list[tuple[list[str], list[str]]]:
    """CIF の loop_ を (見出しの列, 値のトークン列) で返す (; で始まる複数行の文字列は扱わない)。"""
    loops: list[tuple[list[str], list[str]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip().lower() != "loop_":
            i += 1
            continue
        i += 1
        heads: list[str] = []
        while i < len(lines) and lines[i].strip().startswith("_"):
            heads.append(lines[i].strip().split()[0].lower())
            i += 1
        values: list[str] = []
        while i < len(lines):
            t = lines[i].strip()
            if t.lower() == "loop_" or t.startswith(("_", "data_")) or t.startswith(";"):
                break
            if t and not t.startswith("#"):
                try:
                    values.extend(shlex.split(t, posix=True))
                except ValueError:
                    values.extend(t.split())
            i += 1
        loops.append((heads, values))
    return loops


def atom_site_rows(text: str) -> list[dict[str, str]]:
    """``_atom_site_*`` のループの行 (値は生の文字列。esd の括弧を残す)。"""
    for heads, values in _loops(text):
        if "_atom_site_fract_x" in heads:
            n = len(heads)
            return [dict(zip(heads, values[k:k + n])) for k in range(0, len(values) - n + 1, n)]
    return []


def cif_tags(text: str) -> dict[str, str]:
    """ループの外の 1 値のタグ (小文字のタグ名 → 生の値)。"""
    out: dict[str, str] = {}
    in_loop = False
    for line in text.splitlines():
        t = line.strip()
        if t.lower() == "loop_":
            in_loop = True
            continue
        if not t.startswith("_"):
            if t and not t.startswith("#"):
                in_loop = in_loop and not t.startswith("data_")
            continue
        parts = t.split(None, 1)
        if len(parts) == 2 and not in_loop:
            out[parts[0].lower()] = parts[1].strip().strip("'\"")
        elif len(parts) == 2:
            in_loop = False
            out[parts[0].lower()] = parts[1].strip().strip("'\"")
    return out


def cod_revision(text: str) -> str | None:
    m = re.search(r"#\$Revision:\s*(\d+)\s*\$", text)
    return m.group(1) if m else None


def _symops(text: str) -> tuple[str, ...]:
    for heads, values in _loops(text):
        for tag in ("_symmetry_equiv_pos_as_xyz", "_space_group_symop_operation_xyz"):
            if tag in heads:
                n = len(heads)
                k = heads.index(tag)
                return tuple(values[j + k] for j in range(0, len(values) - n + 1, n))
    return ()


def _strip(token: str) -> float | None:
    try:
        return float(re.sub(r"\(.*?\)", "", token))
    except ValueError:
        return None


def _is_hydrogen(row: dict[str, str]) -> bool:
    sym = row.get("_atom_site_type_symbol") or row.get("_atom_site_label") or ""
    el = re.match(r"[A-Za-z]{1,2}", sym)
    return bool(el) and el.group(0).capitalize() in ("H", "D")


def _free_axes(text: str) -> list[tuple[dict[str, str], tuple[str, ...]]] | None:
    from ..topas.symmetry import free_coord_axes

    ops = _symops(text)
    if not ops:
        return None
    out = []
    for row in atom_site_rows(text):
        if _is_hydrogen(row):
            continue
        xyz = [_strip(row.get(f"_atom_site_fract_{a}", "")) for a in "xyz"]
        if any(v is None for v in xyz):
            return None
        out.append((row, free_coord_axes(ops, tuple(xyz))))  # type: ignore[arg-type]
    return out


def free_coordinate_count(text: str) -> int | None:
    """H 以外の原子の自由座標の数 (サイト対称で決まる自由軸)。対称操作が無ければ None。"""
    axes = _free_axes(text)
    return None if axes is None else sum(len(a) for _, a in axes)


def has_all_free_esds(text: str) -> bool:
    """H 以外の全原子の自由座標すべてに 0 でない esd が括弧で付いているか。決められなければ False。"""
    axes = _free_axes(text)
    if not axes:
        return False
    for row, free in axes:
        for a in free:
            m = re.search(r"\((\d+)\)", row.get(f"_atom_site_fract_{a}", ""))
            if m is None or int(m.group(1)) == 0:
                return False
    return True
