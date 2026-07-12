"""Materials Project REST 供給元の遅延 import 境界 (仕様 §5 FR-101)。

``MPClient`` Protocol を定義し、実実装 ``MPRestClient`` が mp-api ``MPRester`` を**呼び出し時に**
遅延 import して元素系クエリを実行する。返り値はコア値オブジェクト ``MPEntry`` に正規化し、
mp_api のオブジェクト形状を上位 (provider / 相同定コア) から隠蔽する。

【遅延 import 契約】: ``import tsumugin.mp.client`` はコア (numpy) のみで成功する。``MPRestClient``
  の構築も mp_api を import しない (キー検証のみ)。mp_api を要求するのは ``search`` の呼び出し時点
  のみで、未導入なら ``MPUnavailableError`` を送出する。API キーは環境変数 ``MATERIALS_PROJECT_API``。
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

from ..errors import MPUnavailableError

__all__ = ["MPClient", "MPEntry", "MPRestClient"]

_API_KEY_ENV = "MATERIALS_PROJECT_API"
_DOTENV_FILENAME = ".env"


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
        api_key: MP API キー。None なら環境変数 ``MATERIALS_PROJECT_API`` を読む。
        include_subsystems: True で全部分系 (単体相・下位系を含む) をクエリする。相同定では
            試料が純金属や下位酸化物を含み得るため既定 True。False で完全系のみに限定する。
        _env: 環境変数マッピング (テスト注入用, 既定は ``os.environ``)。
        _dotenv_path: ``.env`` ファイルの明示パス (テスト注入用)。None かつ ``_env`` が
            未注入 (実運用) の場合のみ、cwd から親方向へ ``.env`` を自動探索する。

    Raises:
        ValueError: 明示キーも環境変数も (該当時) .env にも無いとき (mp_api を import せずに失敗する)。
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        include_subsystems: bool = True,
        _env: Mapping[str, str] | None = None,
        _dotenv_path: str | Path | None = None,
    ) -> None:
        env = os.environ if _env is None else _env
        raw = api_key if api_key is not None else env.get(_API_KEY_ENV)
        # .env autoload (Issue #51): 実運用 (_env 未注入) か、テストが明示的に _dotenv_path を
        # 指定したときのみ読む。_env={} だけのテスト注入 (キー欠落を検証したい既存テスト) は
        # このゲートを通らないため、リポジトリの実 .env に汚染されない。
        if raw is None and (_env is None or _dotenv_path is not None):
            raw = _read_dotenv_key(_API_KEY_ENV, _dotenv_path)
        # .env は "MATERIALS_PROJECT_API = key" 形式で前後空白が入り得るため strip 後に検証する。
        # 空白のみのキーを空文字で通過させず、構築時点で分かりやすく失敗させる。
        key = raw.strip() if raw is not None else None
        if not key:
            raise ValueError(
                f"Materials Project API キーがありません。引数 api_key で渡すか、環境変数 "
                f"{_API_KEY_ENV} を設定するか、.env に {_API_KEY_ENV} を記載してください。"
            )
        self.api_key: str = key
        self._include_subsystems = include_subsystems

    def search(self, elements: Sequence[str]) -> tuple[MPEntry, ...]:
        """MP から元素系クエリで相を取得し ``MPEntry`` へ正規化する。🔵 FR-101

        ``include_subsystems=True`` (既定) では全部分系 (単体相・下位系を含む) を 1 コールで
        クエリする。相同定では試料が純金属や下位酸化物を含み得るため、完全系のみでは
        候補を取りこぼす (FR-100 相ライブラリの網羅性)。

        Raises:
            MPUnavailableError: optional extra ``mp`` (mp-api) 未導入のとき。
        """
        if importlib.util.find_spec("mp_api") is None:
            raise MPUnavailableError(
                "mp-api が見つかりません。Materials Project からの取得には optional extra "
                "'mp' が必要です: `uv sync --extra mp`。"
            )
        from mp_api.client import MPRester

        chemsys = self._chemsys_query(elements)
        fields = [
            "material_id",
            "formula_pretty",
            "elements",
            "structure",
            "energy_above_hull",
            "symmetry",
        ]
        with MPRester(self.api_key) as rester:
            docs = rester.materials.summary.search(chemsys=chemsys, fields=fields)
        return tuple(_doc_to_entry(doc) for doc in docs)

    def _chemsys_query(self, elements: Sequence[str]) -> str | list[str]:
        """クエリ対象の chemsys を組む。🔵

        ``include_subsystems`` が True なら全非空部分集合の chemsys 文字列リスト (単体〜完全系)、
        False なら完全系 1 本を返す。要素は昇順・重複排除で決定論的に生成する。
        """
        elems = sorted(set(elements))
        if not self._include_subsystems:
            return "-".join(elems)
        systems: list[str] = []
        for r in range(1, len(elems) + 1):
            for combo in combinations(elems, r):
                systems.append("-".join(combo))
        return systems


def _read_dotenv_key(key: str, path: str | Path | None = None) -> str | None:
    """``.env`` ファイルから ``key`` の値を読む (Issue #51)。🟡

    ``path`` 指定時はそのファイルのみを読む (テスト決定論用)。未指定なら ``Path.cwd()`` から
    親方向へ ``.env`` を探索し、最初に見つかったものを読む。ファイル欠落/読取失敗/キー欠落は
    例外を投げず None を返す (認証情報の欠落は呼び出し側の ValueError に委ねる)。値は
    決してログ出力しない (シークレットのため)。
    """
    target = Path(path) if path is not None else _find_dotenv()
    if target is None:
        return None
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):].lstrip()
        if "=" not in stripped:
            continue
        line_key, _, line_value = stripped.partition("=")
        line_key = line_key.strip()
        if line_key != key:
            continue
        value = line_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        return value.strip()
    return None


def _find_dotenv() -> Path | None:
    """``Path.cwd()`` から親方向へ ``.env`` を探索する。見つからなければ None。🟡"""
    for directory in (Path.cwd(), *Path.cwd().parents):
        candidate = directory / _DOTENV_FILENAME
        if candidate.is_file():
            return candidate
    return None


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
