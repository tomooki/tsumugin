"""Materials Project REST 供給元の遅延 import 境界 (仕様 §5 FR-101)。

``MPClient`` Protocol を定義し、実実装 ``MPRestClient`` が mp-api ``MPRester`` を**呼び出し時に**
遅延 import して元素系クエリを実行する。返り値はコア値オブジェクト ``MPEntry`` に正規化し、
mp_api のオブジェクト形状を上位 (provider / 相同定コア) から隠蔽する。

【遅延 import 契約】: ``import tsumugin.mp.client`` はコア (numpy) のみで成功する。``MPRestClient``
  の構築も mp_api を import しない (キー検証のみ)。mp_api を要求するのは ``search`` の呼び出し時点
  のみで、未導入なら ``MPUnavailableError`` を送出する。API キーは環境変数 ``MATERIALS_PROJECT_AIP``。
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable

from ..errors import MPUnavailableError

__all__ = ["MPClient", "MPEntry", "MPRestClient"]

_API_KEY_ENV = "MATERIALS_PROJECT_AIP"


@dataclass(frozen=True)
class MPEntry:
    """Materials Project の 1 相 (供給元非依存のコア値オブジェクト)。🔵 FR-101

    ``structure`` は pymatgen ``Structure`` を不透明に保持する (コアは中身に触れない)。未取得は None。
    ``energy_above_hull`` が None の相は hull フィルタ (FR-103) で除外されない。
    """

    material_id: str  # MP ID (例 "mp-19017") 🔵
    formula: str  # 組成式 (例 "LiFePO4") 🔵
    element_system: tuple[str, ...]  # 構成元素 (昇順) 🔵
    structure: object | None  # pymatgen Structure (不透明) or None 🔵
    energy_above_hull: float | None = None  # hull 上エネルギー (eV/atom)。None=保持 🔵
    spacegroup: str | None = None  # 空間群記号。不明は None 🟡


@runtime_checkable
class MPClient(Protocol):
    """Materials Project 供給元。元素系 → ``MPEntry`` 群。🔵 FR-101"""

    def search(self, elements: Sequence[str]) -> Sequence[MPEntry]:
        """``elements`` を含む相を検索して返す。"""
        ...


class MPRestClient:
    """mp-api ``MPRester`` を遅延 import する実クライアント。🔵 FR-101

    Args:
        api_key: MP API キー。None なら環境変数 ``MATERIALS_PROJECT_AIP`` を読む。
        num_elements_only: True で指定元素**のみ**からなる相に限定する (探索元素系の閉包)。
        _env: 環境変数マッピング (テスト注入用, 既定は ``os.environ``)。

    Raises:
        ValueError: 明示キーも環境変数も無いとき (mp_api を import せずに失敗する)。
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        num_elements_only: bool = True,
        _env: Mapping[str, str] | None = None,
    ) -> None:
        env = os.environ if _env is None else _env
        key = api_key if api_key is not None else env.get(_API_KEY_ENV)
        if not key:
            raise ValueError(
                f"Materials Project API キーがありません。引数 api_key で渡すか、環境変数 "
                f"{_API_KEY_ENV} を設定してください。"
            )
        self.api_key: str = key.strip()
        self._num_elements_only = num_elements_only

    def search(self, elements: Sequence[str]) -> tuple[MPEntry, ...]:
        """MP から元素系クエリで相を取得し ``MPEntry`` へ正規化する。🔵 FR-101

        Raises:
            MPUnavailableError: optional extra ``mp`` (mp-api) 未導入のとき。
        """
        if importlib.util.find_spec("mp_api") is None:
            raise MPUnavailableError(
                "mp-api が見つかりません。Materials Project からの取得には optional extra "
                "'mp' が必要です: `uv sync --extra mp`。"
            )
        from mp_api.client import MPRester

        chemsys = "-".join(sorted(elements))
        fields = [
            "material_id",
            "formula_pretty",
            "elements",
            "structure",
            "energy_above_hull",
            "symmetry",
        ]
        with MPRester(self.api_key) as rester:
            # ``chemsys`` は「指定元素のみ」の閉包。部分系も要る場合は呼び出し側で複数系を渡す。
            docs = rester.materials.summary.search(chemsys=chemsys, fields=fields)
        return tuple(_doc_to_entry(doc) for doc in docs)


def _doc_to_entry(doc: object) -> MPEntry:
    """mp_api summary doc をコア ``MPEntry`` へ正規化する。🔵"""
    elements = tuple(sorted(str(e) for e in getattr(doc, "elements", ()) or ()))
    symmetry = getattr(doc, "symmetry", None)
    spacegroup = getattr(symmetry, "symbol", None) if symmetry is not None else None
    ehull = getattr(doc, "energy_above_hull", None)
    return MPEntry(
        material_id=str(getattr(doc, "material_id", "")),
        formula=str(getattr(doc, "formula_pretty", "")),
        element_system=elements,
        structure=getattr(doc, "structure", None),
        energy_above_hull=None if ehull is None else float(ehull),
        spacegroup=spacegroup,
    )
