"""RIETAN-FP 形式の読み取りと GSAS-II 形式への変換 (interop.rietan)。

RIETAN-FP の "GENERAL" 強度データ (``.int``) を ``(two_theta[deg], intensity)`` へ読む純関数と、
GSAS-II が取り込める ``.xye`` (``X Y ESD`` 3 列) へ変換する writer を提供する。numpy-only で決定論的。

GENERAL 形式:
    行 1: ``GENERAL`` (モード識別子)
    行 2: データ点数 N
    行 3..: ``2theta intensity`` の対 (空白区切り、度・昇順)
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

__all__ = [
    "convert_rietan_int",
    "load_rietan_int",
    "parse_rietan_int",
]


def parse_rietan_int(text: str) -> tuple[np.ndarray, np.ndarray]:
    """RIETAN-FP GENERAL テキストを ``(two_theta[deg], intensity)`` へ変換する。🔵

    Args:
        text: ``.int`` の全文 (``GENERAL`` 行 + 点数行 + ``2θ intensity`` の対)。

    Returns:
        ``(two_theta, intensity)`` の float 配列 (共に長さ N)。two_theta は度。

    Raises:
        ValueError: ``GENERAL`` ヘッダが無い / 点数行が整数でない / データ点が宣言数未満のとき。
    """
    lines = [ln.strip() for ln in text.splitlines()]
    # 先頭の空行を除いた最初の非空行が GENERAL ヘッダ。
    idx = next((i for i, ln in enumerate(lines) if ln), None)
    if idx is None or lines[idx].upper() != "GENERAL":
        raise ValueError("RIETAN .int の先頭に GENERAL ヘッダが見つかりません。")

    count_line = next((ln for ln in lines[idx + 1:] if ln), None)
    if count_line is None:
        raise ValueError("RIETAN .int にデータ点数行が見つかりません。")
    try:
        declared = int(float(count_line.split()[0]))
    except (IndexError, ValueError) as exc:
        raise ValueError(f"RIETAN .int の点数行を整数として解釈できません: {count_line!r}") from exc

    # 点数行の次の行以降を (2θ, I) の対として読む。
    count_idx = lines.index(count_line, idx + 1)
    two_theta: list[float] = []
    intensity: list[float] = []
    for ln in lines[count_idx + 1:]:
        if not ln:
            continue
        parts = ln.split()
        if len(parts) < 2:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            continue
        two_theta.append(x)
        intensity.append(y)

    if len(two_theta) < declared:
        raise ValueError(
            f"RIETAN .int のデータ点が不足しています: 宣言 {declared}, 実際 {len(two_theta)}。"
        )
    return (
        np.asarray(two_theta[:declared], dtype=float),
        np.asarray(intensity[:declared], dtype=float),
    )


def load_rietan_int(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """RIETAN-FP ``.int`` を読み ``(two_theta[deg], intensity)`` を返す (``parse_rietan_int`` 参照)。🔵"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_rietan_int(text)


def convert_rietan_int(int_path: str | Path, out_xye_path: str | Path) -> Path:
    """RIETAN-FP ``.int`` を GSAS-II が読める ``.xye`` (``X Y ESD``) へ変換して書き出す。🔵

    ESD は Poisson 統計より ``sqrt(max(I, 1))`` を採る (I<=0 の点で 0 割を避ける)。X 列は 2θ[deg]。
    出力は ``HistogramSpec(data_format="XYE")`` として ``run_auto_rietveld`` に渡せる。

    Returns:
        書き出した ``.xye`` の :class:`~pathlib.Path`。
    """
    two_theta, intensity = load_rietan_int(int_path)
    out = Path(out_xye_path)
    lines = [
        f"{x:.6f} {y:.6f} {math.sqrt(max(y, 1.0)):.6f}"
        for x, y in zip(two_theta.tolist(), intensity.tolist())
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
