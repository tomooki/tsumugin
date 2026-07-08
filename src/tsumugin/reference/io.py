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

__all__ = [
    "load_fxye",
    "load_gsas_powder",
    "load_pattern",
    "load_xrdml",
    "load_xy",
    "parse_fxye",
    "parse_gsas_powder",
    "parse_xrdml",
    "parse_xy",
]

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


def parse_xy(text: str) -> tuple[np.ndarray, np.ndarray]:
    """2〜3 列 XY テキスト (``2θ intensity [esd]``) を ``(two_theta, intensity)`` へ変換する。🔵

    ``#`` で始まる行と空行は読み飛ばす (Jana2020 / Topas / 汎用 .xy)。3 列目 (esd) は無視する。

    Raises:
        ValueError: 有効なデータ行が 1 つも無いとき。
    """
    two_theta: list[float] = []
    intensity: list[float] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        two_theta.append(float(parts[0]))
        intensity.append(float(parts[1]))
    if not two_theta:
        raise ValueError("有効な XY データ行が見つかりません (2θ intensity の列が必要)。")
    return np.asarray(two_theta, dtype=float), np.asarray(intensity, dtype=float)


def load_xy(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """2〜3 列 XY ファイルを読み ``(two_theta, intensity)`` を返す (``parse_xy`` 参照)。🔵"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_xy(text)


def parse_fxye(text: str) -> tuple[np.ndarray, np.ndarray]:
    """GSAS FXYE テキスト (``X Y ESD`` 3 列) を ``(two_theta[deg], intensity)`` へ変換する。🔵

    FXYE (例 APS 11BM の ``.fxye``) は X をセンチ度 (2θ×100) で持つ。タイトル行 (先頭)・``#``
    コメント行・空行を読み飛ばし、数値 3 列の行のみを採る。ESD (第 3 列) は相同定では無視する。
    GSAS-II の add_powder_histogram が読むのと同じ X=センチ度 規約に従う。

    Raises:
        ValueError: 有効な数値データ行が 1 つも無いとき。
    """
    two_theta: list[float] = []
    intensity: list[float] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            # タイトル行など非数値行は読み飛ばす
            continue
        two_theta.append(x * _CENTIDEG_TO_DEG)
        intensity.append(y)
    if not two_theta:
        raise ValueError("有効な FXYE データ行が見つかりません (X Y [ESD] の数値列が必要)。")
    return np.asarray(two_theta, dtype=float), np.asarray(intensity, dtype=float)


def load_fxye(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """GSAS FXYE ファイルを読み ``(two_theta[deg], intensity)`` を返す (``parse_fxye`` 参照)。🔵"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_fxye(text)


def _xrdml_localname(tag: str) -> str:
    """XML タグから名前空間 (``{uri}local``) を剥がしローカル名だけ返す。"""
    return tag.rsplit("}", 1)[-1]


def parse_xrdml(text: str) -> tuple[np.ndarray, np.ndarray]:
    """Panalytical XRDML (X'Pert/Empyrean) を ``(two_theta[deg], intensity)`` へ変換する。🔵

    XRDML は名前空間付き XML で、``<dataPoints>`` 内に走査軸 (``<positions axis="2Theta">``
    の ``startPosition``/``endPosition``) と ``<intensities>`` (空白区切りの計数列) を持つ。
    2θ 軸は start→end を計数点数 N で等分した線形軸として復元する (CaTeO3 cyclic 等の実験室 X 線
    高温 in situ データの供給に用いる)。Omega など他軸の positions は無視し 2Theta のみを採る。

    **対応範囲 (v1)**: 単一走査・線形 2Theta 軸 (start/end)・第 1 ``<intensities>`` ブロック。
    複数走査/バッチや非線形 (``<listPositions>`` 列挙軸)・可変 ``commonCountingTime`` は先頭優先で
    最初の 1 件のみを採る (X'Pert/Empyrean の単一走査を想定)。将来拡張点。

    Args:
        text: XRDML の全文。

    Returns:
        ``(two_theta, intensity)`` の float 配列 (長さ N, two_theta は度・昇順)。

    Raises:
        ValueError: 2Theta の positions か intensities が見つからない / 計数点が 0 のとき。
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"XRDML の XML 解析に失敗しました: {exc}") from exc

    # intensities (空白区切りの計数列) を最初の 1 個採る。
    intensity_vals: list[float] | None = None
    start_2t: float | None = None
    end_2t: float | None = None
    for elem in root.iter():
        name = _xrdml_localname(elem.tag)
        if name == "intensities" and intensity_vals is None and elem.text:
            intensity_vals = [float(tok) for tok in elem.text.split()]
        elif name == "positions" and elem.get("axis") == "2Theta" and start_2t is None:
            for child in elem:
                cname = _xrdml_localname(child.tag)
                if cname == "startPosition" and child.text is not None:
                    start_2t = float(child.text)
                elif cname == "endPosition" and child.text is not None:
                    end_2t = float(child.text)

    if intensity_vals is None or not intensity_vals:
        raise ValueError("XRDML に intensities (計数列) が見つかりません。")
    if start_2t is None or end_2t is None:
        raise ValueError('XRDML に 2Theta の positions (startPosition/endPosition) が見つかりません。')

    n = len(intensity_vals)
    intensity = np.asarray(intensity_vals, dtype=float)
    # 【2θ 軸】: N=1 は縮退のため start のみ。N>=2 は start→end の等分 (endを含む線形) 🔵
    if n == 1:
        two_theta = np.asarray([start_2t], dtype=float)
    else:
        two_theta = np.linspace(start_2t, end_2t, n, dtype=float)
    return two_theta, intensity


def load_xrdml(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Panalytical XRDML ファイルを読み ``(two_theta[deg], intensity)`` を返す (``parse_xrdml`` 参照)。🔵"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_xrdml(text)


def _load_rietan_int(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """RIETAN-FP .int を読む (interop.rietan への一方向委譲)。"""
    from tsumugin.interop.rietan import load_rietan_int

    return load_rietan_int(path)


def _load_igor_tof_xy(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Z-Code Igor TOF を ``(tof[μs], intensity)`` として読む (esd は捨てる; interop へ委譲)。"""
    from tsumugin.interop.zrietveld import load_igor_tof

    tof, intensity, _esd = load_igor_tof(path)
    return tof, intensity


# データ形式名 → ローダー (M9 逐次解析の相同定入力を形式非依存に読むディスパッチャ)。
# INT/IGOR は interop への一方向委譲 (interop は reference.io を import しない = 循環回避)。
_LOADERS = {
    "XRDML": load_xrdml,
    "FXYE": load_fxye,
    "GSAS": load_gsas_powder,
    "XYE": load_xy,
    "XY": load_xy,
    "INT": _load_rietan_int,
    "IGOR": _load_igor_tof_xy,
}


def load_pattern(path: str | Path, data_format: str) -> tuple[np.ndarray, np.ndarray]:
    """データ形式名に応じてローダーを選び ``(two_theta[deg], intensity)`` を返す。🔵

    ``data_format`` は ``FrameSpec.data_format`` / ``HistogramSpec.data_format`` と同じ語彙
    ("XRDML"/"FXYE"/"GSAS"/"XYE"/"XY", 大文字小文字非依存)。相同定 (numpy) への観測パターン供給に用いる。

    Raises:
        ValueError: 未対応の data_format のとき。
    """
    loader = _LOADERS.get(data_format.upper())
    if loader is None:
        raise ValueError(
            f"未対応のデータ形式です: {data_format!r} (対応: {sorted(_LOADERS)})"
        )
    return loader(path)
