"""粉末回折パターンの読み込み (仕様 §5 相同定の入力)。

GSAS 標準粉末データ形式 (``.xra`` / ``.gsas`` / ``.raw``) のうち、CONST ステップ + STD (強度のみ)
バンクを ``(two_theta, intensity)`` へ読む純関数を提供する。相同定 (``identify_phases`` /
``identify_phase_mixtures``) へ渡す観測パターンの供給に使う。numpy のみに依存し決定論的。

対応範囲 (v1): 単一バンク・CONST ステップ・STD フォーマット (整数強度)。ESD/FXYE や複数バンク・
TOF は未対応で、明示的な ``ValueError`` を送出する (将来拡張点)。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

__all__ = ["load_gsas_powder", "parse_gsas_powder"]

# GSAS CONST の start/step はセンチ度 (×100 度) 単位。
_CENTIDEG_TO_DEG = 0.01


def parse_gsas_powder(text: str) -> tuple[np.ndarray, np.ndarray]:
    """GSAS 粉末データテキストを ``(two_theta[deg], intensity)`` へ変換する。🔵

    Args:
        text: GSAS 形式の全文 (タイトル行 + BANK レコード + データ行)。

    Returns:
        ``(two_theta, intensity)`` の float 配列 (共に長さ npts)。two_theta は度・昇順。

    Raises:
        ValueError: BANK レコードが無い / CONST・STD 以外 / データ数が npts 未満のとき。
    """
    lines = text.splitlines()
    bank_idx = next((i for i, ln in enumerate(lines) if ln.strip().startswith("BANK")), None)
    if bank_idx is None:
        raise ValueError("GSAS BANK レコードが見つかりません (対応形式は CONST/STD の単一バンク)。")

    tokens = lines[bank_idx].split()
    # 例: ["BANK","1","6001","601","CONST","1000","2.5","0","0","STD"]
    try:
        npts = int(tokens[2])
        mode = tokens[4].upper()
        start_cd = float(tokens[5])
        step_cd = float(tokens[6])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"BANK レコードの解釈に失敗しました: {lines[bank_idx]!r}") from exc

    if mode != "CONST":
        raise ValueError(f"未対応の軸モードです (CONST のみ対応): {mode}")
    fmt = next((t.upper() for t in tokens[7:] if t.upper() in {"STD", "ESD", "FXYE"}), "STD")
    if fmt != "STD":
        raise ValueError(f"未対応のデータフォーマットです (STD のみ対応): {fmt}")

    # 【強度読み込み】: BANK 以降の全トークンを float 化し先頭 npts を強度とする (末尾パディング無視) 🔵
    values: list[float] = []
    for ln in lines[bank_idx + 1:]:
        for tok in ln.split():
            values.append(float(tok))
    if len(values) < npts:
        raise ValueError(f"データ点が不足しています: 期待 {npts}, 実際 {len(values)}。")

    intensity = np.asarray(values[:npts], dtype=float)
    # 【2θ 軸】: CONST は start + i*step (センチ度→度) 🔵
    two_theta = (start_cd + np.arange(npts, dtype=float) * step_cd) * _CENTIDEG_TO_DEG
    return two_theta, intensity


def load_gsas_powder(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """GSAS 粉末データファイルを読み ``(two_theta, intensity)`` を返す。🔵

    Raises:
        ValueError: 対応外フォーマット / データ不足のとき (``parse_gsas_powder`` 参照)。
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_gsas_powder(text)
