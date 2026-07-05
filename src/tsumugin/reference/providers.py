"""CIF ベースの相ライブラリ供給元 (仕様 §5 FR-101)。

- ``UserCIFProvider``: ユーザー提供 CIF (テキスト / ファイル) を ``ReferencePhase`` へ変換する
  完全実装の ``ReferenceProvider``。
- ``CODProvider`` / ``ICSDProvider``: COD / ICSD (API) からの CIF 取得は **導線のみ確保**する。
  ``downloader`` シーム (元素系 → CIF テキスト列) を注入すれば共有 CIF パースで動作し、未注入なら
  ``NotImplementedError`` で「導線のみ (ネットワーク未配線)」を明示する。ICSD はライセンス要。

CIF パース (``cif_to_reference_phases``) は pymatgen を遅延 import するため、各 provider は ``parse``
を差し替え可能にしている (テストはフェイク parse を注入して pymatgen 非依存に検証する)。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from .cif import cif_to_reference_phases
from .model import ReferencePhase

__all__ = ["CODProvider", "ICSDProvider", "UserCIFProvider"]

# 型エイリアス: CIF テキスト → 参照相列 / 元素系 → CIF テキスト列。
ParseFn = Callable[..., Sequence[ReferencePhase]]
DownloadFn = Callable[[Sequence[str]], Sequence[str]]


def _phases_from_texts(
    texts: Sequence[str],
    parse: ParseFn,
    *,
    id_prefix: str,
    wavelength_angstrom: float,
    two_theta_range: tuple[float, float],
) -> tuple[ReferencePhase, ...]:
    """CIF テキスト列を parse で ``ReferencePhase`` へ変換し連結する (共有ヘルパ)。🔵"""
    refs: list[ReferencePhase] = []
    for i, text in enumerate(texts):
        refs.extend(
            parse(
                text,
                source_id=f"{id_prefix}-{i}",
                wavelength_angstrom=wavelength_angstrom,
                two_theta_range=two_theta_range,
            )
        )
    return tuple(refs)


class UserCIFProvider:
    """ユーザー提供 CIF を候補相として供給する ``ReferenceProvider`` (完全実装)。🔵 FR-101

    Args:
        cif_texts: CIF テキスト列。
        wavelength_angstrom: XRD 生成の線源波長 (Å)。
        two_theta_range: XRD 生成の 2θ 範囲 (度)。
        parse: CIF テキスト → 参照相 (テスト注入用, 既定 ``cif_to_reference_phases``)。
    """

    def __init__(
        self,
        cif_texts: Sequence[str],
        *,
        wavelength_angstrom: float = 1.5406,
        two_theta_range: tuple[float, float] = (10.0, 90.0),
        parse: ParseFn = cif_to_reference_phases,
    ) -> None:
        self._texts = tuple(cif_texts)
        self._wavelength = wavelength_angstrom
        self._two_theta_range = two_theta_range
        self._parse = parse
        self._cache: tuple[ReferencePhase, ...] | None = None

    @classmethod
    def from_files(cls, paths: Sequence[str | Path], **kwargs) -> "UserCIFProvider":
        """CIF ファイル群を読み込んで ``UserCIFProvider`` を構築する。🔵"""
        texts = [Path(p).read_text(encoding="utf-8") for p in paths]
        return cls(texts, **kwargs)

    def fetch(self, elements: Sequence[str]) -> tuple[ReferencePhase, ...]:
        """全 CIF テキストをパースして候補相を返す (初回のみパースしキャッシュ)。🔵

        元素系フィルタは相同定エンジン側で適用されるため、本メソッドは全相を返す。
        """
        if self._cache is None:
            self._cache = _phases_from_texts(
                self._texts,
                self._parse,
                id_prefix="usercif",
                wavelength_angstrom=self._wavelength,
                two_theta_range=self._two_theta_range,
            )
        return self._cache


class _NetworkCIFProvider:
    """COD / ICSD 共通の導線基底。``downloader`` 注入で有効化する (未注入は未配線エラー)。🔵

    ネットワーク取得 (``downloader``) は本 PoC では**導線のみ**確保し、実配線は将来タスク。
    注入された ``downloader(elements) -> CIF テキスト列`` を共有 CIF パースへ流す。
    """

    _SOURCE_NAME = "network"
    _ID_PREFIX = "net"

    def __init__(
        self,
        *,
        downloader: DownloadFn | None = None,
        wavelength_angstrom: float = 1.5406,
        two_theta_range: tuple[float, float] = (10.0, 90.0),
        parse: ParseFn = cif_to_reference_phases,
    ) -> None:
        self._downloader = downloader
        self._wavelength = wavelength_angstrom
        self._two_theta_range = two_theta_range
        self._parse = parse

    def fetch(self, elements: Sequence[str]) -> tuple[ReferencePhase, ...]:
        """``downloader`` で CIF を取得しパースする。未注入なら未配線を明示する。🔵"""
        if self._downloader is None:
            raise NotImplementedError(
                f"{self._SOURCE_NAME} からのネットワーク取得は未配線です (導線のみ確保)。"
                f" downloader (元素系 → CIF テキスト列) を注入してください。"
            )
        texts = self._downloader(elements)
        return _phases_from_texts(
            texts,
            self._parse,
            id_prefix=self._ID_PREFIX,
            wavelength_angstrom=self._wavelength,
            two_theta_range=self._two_theta_range,
        )


class CODProvider(_NetworkCIFProvider):
    """Crystallography Open Database (COD) 供給元 — 導線のみ確保。🔵 FR-101

    COD REST からの CIF 取得は ``downloader`` シームで差し替える。無償 DB のため将来は既定
    downloader を実装予定 (本 PoC では未配線)。
    """

    _SOURCE_NAME = "COD"
    _ID_PREFIX = "cod"


class ICSDProvider(_NetworkCIFProvider):
    """Inorganic Crystal Structure Database (ICSD) 供給元 — 導線のみ確保。🔵 FR-101

    ICSD は商用ライセンス + 認証付き API を要するため、``downloader`` シーム (認証・取得を担う)
    を注入して利用する。既定は未配線 (``NotImplementedError``)。
    """

    _SOURCE_NAME = "ICSD"
    _ID_PREFIX = "icsd"

    def __init__(self, *, api_key: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_key = api_key  # ライセンス認証キー (downloader 実装が参照する想定) 🟡
