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


_STD_FIELD_WIDTH = 8
_STD_COUNT_WIDTH = 2


def _parse_std_fixed_columns(
    data_lines: "list[str]", npts: int
) -> "list[float] | None":
    """GSAS STD の固定桁 ``(I2 検出器数, I6 強度)`` として読む。読めなければ ``None``。

    ``None`` を返した場合、呼び出し側は従来の空白分割へフォールバックする。**桁数を
    決め打ちしない**のは、6 桁詰めなど非標準な書き方の既存データを壊さないため。
    """
    values: list[float] = []
    for raw in data_lines:
        line = raw.rstrip("\r\n").rstrip()
        if not line:
            continue
        if len(line) % _STD_FIELD_WIDTH != 0:
            return None
        for start in range(0, len(line), _STD_FIELD_WIDTH):
            field = line[start:start + _STD_FIELD_WIDTH]
            count_text = field[:_STD_COUNT_WIDTH].strip()
            value_text = field[_STD_COUNT_WIDTH:].strip()
            # 検出器数欄は空白 (=1 とみなす) か整数でなければ固定桁ではない。
            if count_text and not count_text.lstrip("+-").isdigit():
                return None
            if not value_text:
                return None
            try:
                values.append(float(value_text))
            except ValueError:
                return None
    # 点数が合わないなら固定桁の読み方ではない (末尾パディングは許容)。
    return values if len(values) >= npts else None


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

    # 【強度読み込み】: GSAS STD は **(I2, I6) の 8 桁パック**を 1 行 10 点並べる形式で、
    #   先頭 I2 は「合算した検出器数」であって強度ではない。空白で割ると検出器数と強度が
    #   交互に並び**半分の点が 1 になる** (実データ garnet.raw で発覚)。検出器数欄が空白の
    #   書き方 (実質 I8) も同じ規則で読める。
    #   ただし 6 桁詰め等の非標準な書き方もあるため、**固定桁で読めたときだけ**それを採り、
    #   駄目なら従来の空白分割へ落ちる (桁数を決め打ちしない)。
    data_lines = lines[bank_idx + 1:]
    values = _parse_std_fixed_columns(data_lines, npts)
    if values is None:
        values = []
        for ln in data_lines:
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


#: TOF を意味する ``BANK`` 行の binning モード (対数ビン / RALF 可変ビン)。
_TOF_BINNING_MODES = ("SLOG", "RALF")


def _fxye_is_tof(text: str) -> bool:
    """``BANK`` 行の binning モードが TOF を示すか。BANK 行が無ければ False (従来どおり)。"""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith("BANK"):
            continue
        return any(mode in stripped.upper() for mode in _TOF_BINNING_MODES)
    return False


def parse_fxye(text: str) -> tuple[np.ndarray, np.ndarray]:
    """GSAS FXYE テキスト (``X Y ESD`` 3 列) を ``(x, intensity)`` へ変換する。🔵

    **``x`` の単位は入力依存**: 2θ データなら度、TOF データなら µs (下記 BANK 行の判定)。

    2θ の FXYE (例 APS 11BM の ``.fxye``) は X をセンチ度 (2θ×100) で持つので度へ直す
    (GSAS-II の add_powder_histogram と同じ規約)。タイトル行 (先頭)・``#`` コメント行・空行を
    読み飛ばし、数値 3 列の行のみを採る。ESD (第 3 列) は相同定では無視する。

    **TOF の FXYE は X が µs** でありセンチ度ではないので、そのまま返す。``BANK`` 行の
    binning モードで見分ける — ``CONS`` (等間隔) は 2θ センチ度、``SLOG``/``RALF``
    (対数・可変ビン) は TOF。÷100 してしまうと飛行時間が 2 桁縮んで**まったく別の d 範囲**に
    なるが、ピークはどこかに立つので静かに間違う (実 POWGEN の ``.gsa`` は SLOG)。

    Raises:
        ValueError: 有効な数値データ行が 1 つも無いとき。
    """
    scale = _CENTIDEG_TO_DEG if not _fxye_is_tof(text) else 1.0
    # 【名前は ``axis``】: TOF では 2θ ではなく飛行時間なので ``two_theta`` と呼ばない。
    axis: list[float] = []
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
        axis.append(x * scale)
        intensity.append(y)
    if not axis:
        raise ValueError("有効な FXYE データ行が見つかりません (X Y [ESD] の数値列が必要)。")
    return np.asarray(axis, dtype=float), np.asarray(intensity, dtype=float)


def load_fxye(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """GSAS FXYE ファイルを読み ``(x, intensity)`` を返す (``parse_fxye`` 参照)。🔵

    ``x`` は 2θ[度] または TOF[µs] — **どちらかは BANK 行の binning モードで決まる**。
    """
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


#: 拡張子 → データ形式名 (``read_pattern_metadata`` の ``data_format`` 推定)。
_SUFFIX_FORMAT = {
    ".xrdml": "XRDML",
    ".xye": "XYE",
    ".xy": "XY",
    ".dat": "XY",
    ".fxye": "FXYE",
    ".gsa": "GSAS",
    ".gss": "GSAS",
    ".raw": "GSAS",
    ".int": "INT",
    ".histogramigor": "IGOR",
}


def parse_xrdml_metadata(text: str) -> dict[str, object]:
    """XRDML が持つ**測定条件**を読む (強度データではなく装置メタ情報)。🔵 FR-502

    Panalytical XRDML は波長・Kα2 の扱い・反射/透過をファイル自身に書いているのに、
    ``parse_xrdml`` は強度と 2θ しか見ておらず捨てていた。装置パラメータファイルを持たない
    利用者にとって、これは**手元の観測データから得られる唯一の装置情報**である。

    読む項目:

    - ``<kAlpha1>`` / ``<kAlpha2>`` / ``<ratioKAlpha2KAlpha1>`` — 波長と二重線比
    - ``<usedWavelength intended="...">`` — ``"K-Alpha 1"`` なら **Kα2 除去済み**。
      除去済みデータに二重線 instprm を当てるのが実験室 X 線で最大の系統残差になる (M9 CaTeO3)
    - ``sampleMode`` — ``Reflection`` は Bragg-Brentano、``Transmission`` は Debye-Scherrer
    - ``<anodeMaterial>`` — 管球 (記録用)

    :param text: XRDML の全文
    :returns: 判った項目だけを含む dict (**判らない項目はキーごと入れない** — 捏造しない)
    """
    import xml.etree.ElementTree as ET

    meta: dict[str, object] = {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return meta  # 壊れたファイルは「読めなかった」= 何も主張しない

    for elem in root.iter():
        name = _xrdml_localname(elem.tag)
        body = (elem.text or "").strip()
        if name == "usedWavelength":
            intended = (elem.get("intended") or "").strip()
            if intended:
                # "K-Alpha 1" = Kα1 のみ (Kα2 除去済み) / "K-Alpha" = 二重線のまま
                meta["kalpha2_stripped"] = intended.lower().replace("-", "").replace(
                    " ", ""
                ) == "kalpha1"
        elif name == "kAlpha1" and body and "wavelength" not in meta:
            meta["wavelength"] = float(body)
        elif name == "kAlpha2" and body and "wavelength_ka2" not in meta:
            meta["wavelength_ka2"] = float(body)
        elif name == "ratioKAlpha2KAlpha1" and body and "ka2_ratio" not in meta:
            meta["ka2_ratio"] = float(body)
        elif name == "anodeMaterial" and body and "anode" not in meta:
            meta["anode"] = body
        elif name == "xrdMeasurement" and "geometry" not in meta:
            mode = (elem.get("sampleMode") or "").strip().lower()
            if mode == "reflection":
                meta["geometry"] = "bragg_brentano"
            elif mode == "transmission":
                meta["geometry"] = "debye_scherrer"
    if "wavelength" in meta:
        # XRDML は実験室回折計の形式 (放射光/中性子は別形式)。
        meta["radiation"] = "xray_lab"
    return meta


def read_pattern_metadata(
    path: str | Path, data_format: str | None = None
) -> dict[str, object]:
    """観測データファイルが持つ装置メタ情報を読む。🔵 FR-502

    装置パラメータファイル (``.instprm``) を持っていない利用者が、**手元のデータだけから**
    instprm を組めるようにするための入口 (``instprm.build_instprm_text`` の引数を埋める)。

    現時点で意味のある情報を持つのは **XRDML のみ**。FXYE/GSAS/XYE/INT/IGOR は波長を
    構造的に持たない (それを外に置くのが装置パラメータファイルの役目) ため
    ``source_format`` だけを返す。**判らないものを既定値で埋めない** — Cu Kα と決め打つと
    放射光データを黙って壊す。

    :param path: 観測データファイル
    :param data_format: 形式名 (``load_pattern`` と同じ語彙)。省略時は拡張子から推定
    :returns: ``source_format`` と、判った範囲の ``wavelength`` / ``wavelength_ka2`` /
        ``ka2_ratio`` / ``kalpha2_stripped`` / ``geometry`` / ``radiation`` / ``anode``

    Raises:
        ValueError: 形式を推定できない / 未対応の ``data_format`` のとき。
    """
    p = Path(path)
    fmt = (data_format or _SUFFIX_FORMAT.get(p.suffix.lower()) or "").upper()
    if fmt not in _LOADERS:
        raise ValueError(
            f"data_format を判別できません (拡張子={p.suffix!r})。"
            f"明示指定してください (対応: {sorted(_LOADERS)})"
        )
    meta: dict[str, object] = {"source_format": fmt}
    if fmt == "XRDML":
        meta.update(parse_xrdml_metadata(p.read_text(encoding="utf-8", errors="replace")))
    return meta


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
