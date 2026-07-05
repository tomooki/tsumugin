"""相ライブラリのパターン/ピークリスト永続キャッシュ (仕様 §5 FR-105)。

``CachedReferenceProvider`` は任意の ``ReferenceProvider`` をラップし、``fetch(elements)`` の
結果 (``ReferencePhase`` 群 = 生成済みピークリスト) を JSON でディスクへ永続化する。同一元素系の
再取得ではネットワーク往復や XRD 再生成を回避する。X線/中性子は散乱長が異なるため ``namespace``
で別キャッシュに分離する (FR-105)。

キャッシュは再生成可能な派生物であり、キー (namespace + 正規化元素系) が決定論的なので同一入力は
同一ファイルへ写る。書き込みは一時ファイル + ``os.replace`` でアトミックに行う。
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from .model import ReferencePhase
from .provider import ReferenceProvider
from .serialization import reference_phase_from_dict, reference_phase_to_dict

__all__ = ["CachedReferenceProvider"]


def _cache_key(namespace: str, elements: Sequence[str]) -> str:
    """namespace + 正規化元素系から決定論的なファイル名 (拡張子なし) を作る。🔵

    元素は昇順・重複排除し順序非依存にする。元素記号は英数字のみで安全なファイル名になる。
    """
    normalized = "-".join(sorted(set(elements)))
    return f"{namespace}__{normalized}"


class CachedReferenceProvider:
    """``ReferenceProvider`` をラップしディスクへ永続キャッシュする供給元。🔵 FR-105

    Args:
        inner: 実際の供給元 (MP / CIF など)。キャッシュミス時のみ ``fetch`` される。
        cache_dir: キャッシュ JSON を置くディレクトリ (無ければ生成)。
        namespace: 散乱長/線源等の識別子 (既定 "default")。X線/中性子で分ける。
    """

    def __init__(
        self,
        inner: ReferenceProvider,
        cache_dir: str | Path,
        *,
        namespace: str = "default",
    ) -> None:
        self._inner = inner
        self._cache_dir = Path(cache_dir)
        self._namespace = namespace

    def fetch(self, elements: Sequence[str]) -> tuple[ReferencePhase, ...]:
        """キャッシュがあれば読み、無ければ ``inner.fetch`` して永続化する。🔵 FR-105"""
        path = self._cache_dir / f"{_cache_key(self._namespace, elements)}.json"
        cached = self._load(path)
        if cached is not None:
            return cached
        refs = tuple(self._inner.fetch(elements))
        self._store(path, elements, refs)
        return refs

    def _load(self, path: Path) -> tuple[ReferencePhase, ...] | None:
        """キャッシュファイルを読む。無ければ None。🔵"""
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return tuple(reference_phase_from_dict(d) for d in data["phases"])

    def _store(
        self, path: Path, elements: Sequence[str], refs: Sequence[ReferencePhase]
    ) -> None:
        """キャッシュファイルをアトミックに書く (一時ファイル + os.replace)。🔵"""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "namespace": self._namespace,
            "elements": sorted(set(elements)),
            "phases": [reference_phase_to_dict(r) for r in refs],
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
        os.replace(tmp, path)  # 同一ディレクトリ内アトミック置換 🔵
