"""GSAS 原子行の読み取りテンプレート — **唯一の実装** (GSAS 非依存)。

原子行を読む処理は本リポジトリに 3 箇所あり (`engine._atom_result_maps` /
`engine._phase_atom_info` / `workbench.atoms.extract_sites`)、互いの docstring は「同じ抽出
テンプレート」と称しながら各自が書き直していた。`AtomPtrs` の意味と対称性の解釈が独立に
3 通り存在する状態で、`mem/gsas.py:484` は `cx=3` を決め打ちしている。本モジュールに集約する。

GSAS 原子行は**素の Python list** なので import は不要。`GetCSxinel` だけ**関数注入**にして
あるため、本モジュール全体が `-m "not gsas"` で回る (呼び出し側は既に `GSASIIspc` を遅延
import している)。

**座標 esd の出所** (取り違えやすいので明記する): GSAS は座標を**シフト** ``dAx/dAy/dAz`` として
精密化し、精密化のたびに 0 へ再初期化する (`GSASIIstrIO.py:1732`) ので**値は使えない**。しかし
その ``sig`` が x の esd である — GSAS 自身が `GSASIIstrIO.py:2603-2606` の
``names[ind].replace('A','dA')`` でそう決めている。``Ax`` を引いてはならない。

信頼性: 🔵 `GSASIIspc.py:2528-2557` (CSxinel 実テーブル) + `GSASIIstrIO.py:1743-1765`
(xId の消費) + `GSASIIstrMain.py:562-582` (depSigDict) を実ソースで確認。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .._json import finite_or_none

__all__ = [
    "AtomRow",
    "atom_row",
    "coord_esd_states",
    "free_index_from_site_symmetry",
    "lock_from_free_index",
]

#: 軸ごとの自由度指標 (`GetCSxinel(sytsym)[0]`)。**3 状態**である:
#:
#: - ``0``            : 対称拘束で厳密に固定。GSAS は `StoreHold(..., 'Fixed by symmetry')` にし
#:                      **変数にしない** (`GSASIIstrIO.py:1756-1759`)
#: - 正値・三つ組内で一意 : 独立変数
#: - 正値・他軸と一致    : その軸どうしが**結束**される (`StoreEquivalence`, 同 :1759-1765)。
#:                      従属側は最終 varyList に載らないが ``depSigDict`` には載る
#:
#: bool へ潰すと結束軸が独立に見えるため、生の整数三つ組で運ぶ。
FreeIndex = tuple[int, int, int]


@dataclass(frozen=True)
class AtomRow:
    """GSAS 原子行 1 行から読める値 (`AtomPtrs` レイアウト解決済み)。

    :param uiso: ``row[cia] == "I"`` のときだけ float。異方性原子は ``None``
        (0.0 を捏造しない — 既存 `atom_uiso` の規律と同じ)
    """

    label: str
    element: str
    coords: tuple[float, float, float]
    occupancy: float
    site_symmetry: str
    multiplicity: float
    uiso: "float | None"


def atom_row(row: Sequence[object], ptrs: Sequence[int]) -> AtomRow:
    """原子行 + ``AtomPtrs`` → `AtomRow`。

    :param ptrs: ``ph.data["General"]["AtomPtrs"]`` = ``(cx, ct, cs, cia)``。
        座標は ``row[cx..cx+2]``・占有率 ``row[cx+3]``・ラベル ``row[ct-1]``・元素 ``row[ct]``・
        site symmetry ``row[cs]``・多重度 ``row[cs+1]``・熱振動型 ``row[cia]``・Uiso ``row[cia+1]``
    """
    cx, ct, cs, cia = (int(p) for p in ptrs)
    uiso = float(row[cia + 1]) if row[cia] == "I" else None
    return AtomRow(
        label=str(row[ct - 1]),
        element=str(row[ct]),
        coords=(float(row[cx]), float(row[cx + 1]), float(row[cx + 2])),
        occupancy=float(row[cx + 3]),
        site_symmetry=str(row[cs]),
        multiplicity=float(row[cs + 1]),
        uiso=uiso,
    )


def free_index_from_site_symmetry(
    getcsxinel: Callable[[str], Sequence[Sequence[object]]], site_symmetry: object
) -> FreeIndex:
    """site symmetry → `FreeIndex`。判定できなければ**保守的に**縮退する。

    ``GetCSxinel`` は sytsym 名の変更で ``KeyError`` を出すことがあり、GSAS 自身がその場で
    パッチしている (`GSASIIstrIO.py:1745-1749`)。ここで例外を上げると呼び出し側の
    「相ごと skip」に巻き込まれて**別の情報 (Uiso 等) まで落ちる**ので、一般位置かどうかの
    保守的判定 (``"1"`` なら全独立・それ以外は全固定扱い) へ縮退する。

    :param getcsxinel: `GSASIIspc.GetCSxinel` (テスト/numpy 経路のための関数注入シーム)
    """
    sym = str(site_symmetry).strip()
    try:
        raw = getcsxinel(sym)[0]
        return (int(raw[0]), int(raw[1]), int(raw[2]))
    except Exception:  # noqa: BLE001 — 未知 sytsym は一般位置判定へ縮退 (相を落とさない)
        return (1, 2, 3) if sym == "1" else (0, 0, 0)


def lock_from_free_index(free_index: FreeIndex) -> dict[str, bool]:
    """`FreeIndex` → GUI のロック表示 (``{"x": bool, "y": bool, "z": bool}``)。

    ロックは「対称拘束で固定 (``0``)」のみ。**結束軸はロックではない** — 動くので、
    GUI 上は編集可能として扱うのが正しい (esd の状態とは別問題)。
    """
    return {axis: free_index[i] == 0 for i, axis in enumerate("xyz")}


def coord_esd_states(
    free_index: FreeIndex,
    *,
    pid: int,
    index: int,
    esd_lookup: Callable[[str], "float | None"],
) -> tuple["float | None", "float | None", "float | None"]:
    """軸ごとの座標 esd を **3 状態**で返す (`CellEsd` と同型の規律)。

    | 状態 | 表現 | 意味 |
    |---|---|---|
    | 精密化した | ``>0.0`` | ``dA{axis}`` の sig。結束軸も `depSigDict` 経由で入る |
    | 対称拘束で固定 | ``0.0`` | 厳密に固定 = **真の陳述** ("この原子は厳密に 0 0 Z") |
    | 決まっていない | ``None`` | 座標段未解放・段 revert・共分散なし |

    **``0.0`` を捏造しない**のが要点。自由軸で lookup が ``0.0`` を返すのは
    `G2mv.ComputeDepESD` の作る偽ゼロ (`GSASIImapvars.py:1410-1423`: 独立変数が varyList に
    無いと ``vcov`` が全 0 のまま ``sqrt(0)`` を返す) なので ``None`` に落とす。

    :param esd_lookup: 変数名 → esd (無ければ ``None``)。``dict.get`` を渡せばよい
    """
    out: list[float | None] = []
    for axis_i, axis in enumerate("xyz"):
        raw = esd_lookup(f"{pid}::dA{axis}:{index}")
        value = finite_or_none(raw) if raw is not None else None
        if value is not None and value > 0.0:
            out.append(value)
        elif free_index[axis_i] == 0:
            # 対称拘束で固定。lookup は空 (変数ですらない) のが正常。
            out.append(0.0)
        else:
            # 自由 (または結束) なのに esd が無い/非正 = このデータからは決まっていない。
            out.append(None)
    return (out[0], out[1], out[2])
