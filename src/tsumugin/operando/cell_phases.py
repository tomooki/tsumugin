"""operando セル固定相プリセット (FR-312 / REQ-009)。

operando 電池計測では活物質の回折ピークに、セルを構成する不活性材料 (Be 窓・Al 集電体・
グラファイト等) の固定ピークが常に重畳する。本モジュールはこれらを「構造固定・scale のみ
解放で探索に常駐する固定相」として供給するプリセット層を提供する。

提供シンボル (契約は ``docs/design/m3-operando/interfaces.py`` L232-244):

- :class:`FixedPhaseSpec` — セル固定相の指定を表す frozen 値オブジェクト。
- :data:`CELL_PHASE_PRESETS` — キー ``"Be"`` / ``"Al"`` / ``"graphite"`` の 3 プリセット。
- :func:`fixed_free_suffixes` — 固定相の解放パラメータ suffix (常に ``("scale",)``)。

--------------------------------------------------------------------------
格子定数の直方 (orthorhombic) 近似についての注意
--------------------------------------------------------------------------
:class:`~tsumugin.backends.simulated.SimulatedBackend` の面間隔計算 ``_d_spacing`` は
90° 直方系 ``1/d² = h²/a² + k²/b² + l²/c²`` を用いる。六方晶 (Be / graphite) を
``a = b`` のまま入れると b 方向反射が a と縮退し実回折と乖離するため、本プリセットでは
六方晶を **orthohexagonal 直方近似** ``a' = a, b' = a·√3, c' = c`` で格納する。

**この近似のため、プリセットのピーク位置は実回折のピーク位置とずれうる**
(特に六方晶由来の反射)。定量精度が要る用途では別途構造モデルを用いること。

文献格子定数 (出典: 標準的な結晶学データ) → 直方近似:

- **Be (hcp)**   : a=2.2858 Å, c=3.5843 Å → a'=2.2858, b'=a·√3≈3.9591, c'=3.5843
- **Al (fcc)**   : a=4.0495 Å            → 立方晶のため a=b=c=4.0495 (直方近似の歪みなし)
- **graphite**   : a=2.464 Å, c=6.711 Å  → a'=2.464, b'=a·√3≈4.2678, c'=6.711

🔵 提供 API・固定相方針は REQ-009 / interfaces.py L236-244 に依拠。🟡 格子値そのもの (文献値) と
直方近似方針・固定粒度 (scale のみ) は設計裁量 (要件へ遡及可能)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..model import LatticeParams, PhaseInstance

# 【近似係数】: 六方晶を orthohexagonal 直方近似する際の b 軸倍率 √3 (a' = a, b' = a·√3)。
# SimulatedBackend の直方 _d_spacing に整合させ、a=b 縮退による b 方向反射消失を回避する。🟡
_SQRT3 = math.sqrt(3.0)


@dataclass(frozen=True)
class FixedPhaseSpec:
    """セル固定相の指定 (構造固定・scale のみ解放・探索常駐) を表す不変値オブジェクト。

    【機能概要】: operando セルの不活性材料 (窓・集電体等) を、構造 (格子・占有率) を固定し
                  scale のみ解放して探索に常駐させる固定相として指定する値オブジェクト。
    【実装方針】: interfaces.py L236-241 の契約どおり ``phase`` / ``label`` の 2 フィールドを持つ
                  frozen dataclass とする (探索メタ ``delta_u`` は持たない = ``PhaseCandidate`` との差分)。
    【テスト対応】: TC-N01/N04/N05/A01 (取得・等価・フィールド実体性・frozen 不変性) を通す。
    🔵 信頼性レベル: interfaces.py L236-241 / REQ-009 に直接依拠。

    :param phase: 固定相の相インスタンス (格子・scale を保持)。
    :param label: 固定相ラベル (必須。``None`` 不可。例 "Be window" / "Al collector")。
    """

    phase: PhaseInstance  # 【相インスタンス】: 直方近似格子と scale を保持する固定相本体 🔵
    label: str  # 【ラベル】: 固定相の人間可読名 (必須・非空を想定) 🔵


def fixed_free_suffixes(spec: FixedPhaseSpec) -> tuple[str, ...]:
    """固定相の解放パラメータ suffix を返す。常に ``("scale",)`` (構造固定・scale のみ解放)。

    【機能概要】: 固定相を精密化へ組む際に解放するパラメータの suffix 集合を返す単一の真実源。
    【実装方針】: REQ-009「固定相は構造固定・scale のみ解放」の字義どおり、lattice/occupancy を
                  解放せず常に ``("scale",)`` を返す。呼び側 (TASK-0032/0033) は
                  ``param_name(i, "scale")`` (backends.base) で ``free_params`` を構成する。
    【テスト対応】: TC-N03 (scale のみ解放) / TC-BV03 (精密化後 lattice 不変) を通す。
    🟡 信頼性レベル: TC-203-02 / REQ-009 / interfaces.py L238 に依拠 (戻り形は妥当推測)。

    :param spec: 固定相の指定。将来の粒度拡張余地のため受けるが、本タスクでは spec 非依存。
    :returns: 解放パラメータ suffix のタプル (常に ``("scale",)``)。
    """
    # 【scale のみ解放】: 構造 (lattice/occupancy) は解放しない。spec に依存せず常に固定を返す 🟡
    return ("scale",)


def _orthohexagonal(phase_ref: str, a: float, c: float) -> PhaseInstance:
    """六方晶を orthohexagonal 直方近似した固定相 PhaseInstance を組む。

    【機能概要】: 六方晶 (Be / graphite) の (a, c) から直方近似格子 ``a' = a, b' = a·√3, c' = c``
                  を作り、scale=1.0 の固定相相インスタンスを返す内部ヘルパ。
    【実装方針】: SimulatedBackend の直方 _d_spacing に整合させ、a=b 縮退による b 方向反射消失を回避。
    【テスト対応】: TC-N02 (格子値) / TC-BV01 (b == a·√3) を通す。
    🟡 信頼性レベル: 要件定義 §2.2 (orthohexagonal b=a·√3) に依拠 (近似方針は 🟡)。

    :param phase_ref: 相参照名 (非空)。
    :param a: 文献 a 軸長 (Å)。
    :param c: 文献 c 軸長 (Å)。
    :returns: 直方近似格子を持つ scale=1.0 の PhaseInstance。
    """
    # 【b 軸の直方近似】: b' = a·√3。TC-BV01 が同式 (a * math.sqrt(3.0)) で照合するためビット一致する 🟡
    lattice = LatticeParams(a=a, b=a * _SQRT3, c=c)
    return PhaseInstance(phase_ref=phase_ref, lattice=lattice)


def _cubic(phase_ref: str, a: float) -> PhaseInstance:
    """立方晶を等方格子 ``a = b = c`` として固定相 PhaseInstance を組む内部ヘルパ。

    【機能概要】: 立方晶 (fcc Al) の a から等方格子を作り scale=1.0 の固定相を返す。
    【実装方針】: 立方晶は直方系の特殊ケース (三軸等長)。六方近似の軸変換は適用しない。
    【テスト対応】: TC-N02 / TC-BV02 (a==b==c・角 90°) を通す。
    🟡 信頼性レベル: 要件定義 §2.2 (Al fcc a=b=c) / 文献値に依拠 (格子値は 🟡)。

    :param phase_ref: 相参照名 (非空)。
    :param a: 文献 a 軸長 (Å)。
    :returns: 等方格子を持つ scale=1.0 の PhaseInstance。
    """
    # 【等方格子】: 立方晶は a=b=c。異方近似を誤適用しない (角は LatticeParams 既定 90°) 🟡
    lattice = LatticeParams(a=a, b=a, c=a)
    return PhaseInstance(phase_ref=phase_ref, lattice=lattice)


# 【プリセットテーブル】: Be/Al/graphite の 3 固定相。モジュールロード時に確定する不変定数 (NFR-102)。
# 読み取り専用 Mapping (MappingProxyType) として公開し、未定義キーは標準 Mapping の KeyError とする。
# 🔵 キー集合は interfaces.py L244 に依拠。🟡 格子値は文献値 (docstring 出典参照)。
CELL_PHASE_PRESETS: Mapping[str, FixedPhaseSpec] = MappingProxyType(
    {
        # 【Be 窓 (hcp → 直方近似)】: a=2.2858, b=a·√3≈3.9591, c=3.5843 🟡
        "Be": FixedPhaseSpec(
            phase=_orthohexagonal("Be", a=2.2858, c=3.5843),
            label="Be window",
        ),
        # 【Al 集電体 (fcc → 等方)】: a=b=c=4.0495 (直方近似の歪みなし) 🟡
        "Al": FixedPhaseSpec(
            phase=_cubic("Al", a=4.0495),
            label="Al collector",
        ),
        # 【graphite (hex → 直方近似)】: a=2.464, b=a·√3≈4.2678, c=6.711 🟡
        "graphite": FixedPhaseSpec(
            phase=_orthohexagonal("graphite", a=2.464, c=6.711),
            label="graphite",
        ),
    }
)


__all__ = [
    "CELL_PHASE_PRESETS",
    "FixedPhaseSpec",
    "fixed_free_suffixes",
]
