"""Z-Rietveld (Z-Code) 形式の読み取りと GSAS-II 形式への変換 (interop.zrietveld)。

KEK/J-PARC の Z-Rietveld / Z-Code エコシステム (iMATERIA TOF 中性子を含む) の 2 形式を扱う:

- **Igor テキスト TOF ヒストグラム** (``.histogramIgor``): iMATERIA データ整約の出力。
  ``IGOR`` / ``WAVES tof, yint, yerr, nc`` / ``BEGIN`` .. ``END`` の 4 列。
  :func:`parse_igor_tof` / :func:`load_igor_tof` で ``(tof[μs], intensity, esd)`` へ読み、
  :func:`convert_igor_tof` で GSAS-II が取り込める **TOF FXYE** ファイルへ変換する。
- **回折計設定** (``.zDiffractometer`` / ``.zDiffractoMeter``): ``[key] value`` / ``[Section] .. [End]``
  階層のテキスト。:func:`parse_zdiffractometer` で :class:`ZDiffractometer` へ読む。X 線 (v1) と
  TOF 中性子 (v2) の双方に対応し、instprm 生成 (:mod:`tsumugin.interop.instrument`) の入力になる。

GSAS-II TOF FXYE の X 列規約: GSAS-II の FXYE リーダは第 1 列を常に ``/100`` する (CW のセンチ度由来)。
そのため TOF (μs) は ``TOF × 100`` で書き出す。放射源が TOF かどうかは instprm の ``Type:PNT`` が決める。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import numpy as np

__all__ = [
    "ZDiffractometer",
    "convert_igor_tof",
    "load_igor_tof",
    "parse_igor_tof",
    "parse_zdiffractometer",
]


# --------------------------------------------------------------------------------------
# Igor TOF ヒストグラム
# --------------------------------------------------------------------------------------
def parse_igor_tof(text: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-Code Igor テキスト TOF を ``(tof[μs], intensity, esd)`` へ変換する。🔵

    ``BEGIN`` と ``END`` の間の数値 4 列 (``tof yint yerr nc``) を読む。第 4 列 (nc) は無視する。
    TOF ステップは可変でよい (先頭 2μs → 末尾 4μs 等)。

    Raises:
        ValueError: ``BEGIN``/``END`` ブロックが無い / 有効データ行が 0 のとき。
    """
    lines = text.splitlines()
    begin = next((i for i, ln in enumerate(lines) if ln.strip().upper() == "BEGIN"), None)
    if begin is None:
        raise ValueError("Igor TOF に BEGIN 行が見つかりません。")

    tof: list[float] = []
    yint: list[float] = []
    yerr: list[float] = []
    for ln in lines[begin + 1:]:
        stripped = ln.strip()
        if stripped.upper() == "END":
            break
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) < 3:
            continue
        try:
            t = float(parts[0])
            y = float(parts[1])
            e = float(parts[2])
        except ValueError:
            continue
        tof.append(t)
        yint.append(y)
        yerr.append(e)

    if not tof:
        raise ValueError("Igor TOF に有効なデータ行が見つかりません (tof yint yerr の数値列が必要)。")
    return (
        np.asarray(tof, dtype=float),
        np.asarray(yint, dtype=float),
        np.asarray(yerr, dtype=float),
    )


def load_igor_tof(path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-Code Igor TOF ファイルを読み ``(tof[μs], intensity, esd)`` を返す (``parse_igor_tof`` 参照)。🔵"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_igor_tof(text)


def convert_igor_tof(igor_path: str | Path, out_path: str | Path, *, title: str = "") -> Path:
    """Z-Code Igor TOF を GSAS-II TOF FXYE (``BANK .. FXYE``) へ変換して書き出す。🔵

    X 列は TOF[μs] をそのまま書く (GSAS-II の GSAS 粉末リーダは TOF FXYE の X を μs としてそのまま採り、
    ``Type:PNT`` instprm の difC/difA/Zero で d 変換する。実 GSAS-II で検証済 → T5 gated test)。
    出力は ``HistogramSpec(data_format="GSAS")`` として ``run_auto_rietveld`` に渡せる。放射源が TOF で
    あることは instprm の ``Type:PNT`` が決める (このファイル自体には放射源情報を持たせない)。

    Returns:
        書き出した FXYE の :class:`~pathlib.Path`。
    """
    tof, yint, yerr = load_igor_tof(igor_path)
    n = int(tof.size)
    header = title or Path(igor_path).stem
    out = Path(out_path)
    body = [
        f"{t:.4f} {y:.6f} {max(e, 1.0e-6):.6f}"
        for t, y, e in zip(tof.tolist(), yint.tolist(), yerr.tolist())
    ]
    text = f"{header}\nBANK 1 {n} {n} FXYE\n" + "\n".join(body) + "\n"
    out.write_text(text, encoding="utf-8")
    return out


# --------------------------------------------------------------------------------------
# 回折計設定 (.zDiffractometer / .zDiffractoMeter)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ZDiffractometer:
    """Z-Code 回折計設定の必要部分 (instprm 生成の入力)。🔵

    :param beam_type: ``"Neutron"`` / ``"X-Ray"``
    :param method: ``"Time Of Flight"`` / ``"Synchrotron Radiation"`` など
    :param wavelength: X 線波長 [Å] (X 線のみ、無ければ None)
    :param zero: ゼロシフト (X 線: 2θ ゼロ ``[Z]``; TOF: 変換係数 ``c0``)
    :param conversion_params: TOF 変換係数 ``(c0, c1, c2)`` (``TOF = c0 + c1·d + c2·d²``)。X 線では空
    :param background: 背景係数列 (Z-Code 多項式)。参考情報 (GSAS 背景は別途 recipe で解放)
    :param scale: スケール係数初期値 (無ければ None)
    :param profile: 既定プロファイル関数の係数 (``{param: value}``)。参考情報
    :param default_profile: 既定プロファイル関数識別子 (例 ``"Type0m"``)
    :param fitting_range: ``[Peak position]`` の ``(min, max)`` (X 線は 2θ[deg]、TOF は μs)
    """

    beam_type: str
    method: str
    wavelength: float | None = None
    zero: float | None = None
    conversion_params: tuple[float, ...] = ()
    background: tuple[float, ...] = ()
    scale: float | None = None
    profile: Mapping[str, float] = field(default_factory=dict)
    default_profile: str | None = None
    fitting_range: tuple[float, float] | None = None
    bank_two_theta: float | None = None

    @property
    def is_tof(self) -> bool:
        """TOF 測定かどうか (method に "Time Of Flight" を含む)。🔵"""
        return "time of flight" in self.method.lower()

    @property
    def is_neutron(self) -> bool:
        """中性子かどうか (beam_type が Neutron)。🔵"""
        return "neutron" in self.beam_type.lower()


def _tag_and_rest(line: str) -> tuple[str, str] | None:
    """``[Tag] rest`` 行を ``(tag, rest)`` へ分解する。``#`` コメント/非タグ行は None。"""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or not stripped.startswith("["):
        return None
    end = stripped.find("]")
    if end < 0:
        return None
    return stripped[1:end].strip(), stripped[end + 1:].strip()


def _first_float(s: str) -> float | None:
    """文字列先頭トークンを float 化 (失敗時 None)。"""
    try:
        return float(s.split()[0])
    except (IndexError, ValueError):
        return None


def parse_zdiffractometer(text: str) -> ZDiffractometer:
    """Z-Code ``.zDiffractometer`` テキストを :class:`ZDiffractometer` へ変換する。🔵

    ``[Section] value`` のインラインスカラと、``[Name]`` の直後に ``[Value] x`` を持つ有値ブロックを
    対象に、instprm 生成に必要な項目を抽出する (プロファイル初期値テンプレート群は既定関数のみ採る)。
    X 線 (v1) と TOF 中性子 (v2) の双方に対応。

    Raises:
        ValueError: ``[Beam type]`` / ``[Measurement method]`` が読めないとき。
    """
    parsed = [pair for ln in text.splitlines() if (pair := _tag_and_rest(ln)) is not None]

    scalars: dict[str, str] = {}
    for tag, rest in parsed:
        if rest and not rest.startswith("["):
            scalars.setdefault(tag, rest)

    beam_type = scalars.get("Beam type")
    method = scalars.get("Measurement method")
    if beam_type is None or method is None:
        raise ValueError("zDiffractometer に [Beam type] / [Measurement method] が見つかりません。")

    # 直後に [Value] を持つブロックを名前ごとに収集 (Conversion/Background は複数)。
    def _values_after(target: str) -> list[float]:
        out: list[float] = []
        for i, (tag, _rest) in enumerate(parsed):
            if tag != target:
                continue
            for tag2, rest2 in parsed[i + 1: i + 4]:
                if tag2 == "Value":
                    v = _first_float(rest2)
                    if v is not None:
                        out.append(v)
                    break
        return out

    conversion = tuple(_values_after("Conversion parameters"))
    background = tuple(_values_after("Background parameters"))
    scale_vals = _values_after("Scale factor")
    scale = scale_vals[0] if scale_vals else None

    wavelength: float | None = None
    zero: float | None = None
    if "Time Of Flight" in method:
        # TOF: c0 をゼロシフトとして採る (TOF = c0 + c1·d + c2·d²)。
        zero = conversion[0] if conversion else None
    else:
        wl = _values_after("Wave length")
        wavelength = wl[0] if wl else None
        z = _values_after("Z")
        zero = z[0] if z else None

    # 既定プロファイル関数の係数を抽出。
    default_profile = scalars.get("Default profile model function identifier")
    profile = _extract_profile(parsed, default_profile)

    # フィッティング範囲 ([Peak position] 内の [Min]/[Max])。
    fitting_range = _extract_range(parsed)

    # TOF バンク角 ([Intensity correction parameters] 内の [Diffraction angle])。
    bank_two_theta = _first_float(scalars.get("Diffraction angle", ""))

    return ZDiffractometer(
        beam_type=beam_type,
        method=method,
        wavelength=wavelength,
        zero=zero,
        conversion_params=conversion,
        background=background,
        scale=scale,
        profile=profile,
        default_profile=default_profile,
        fitting_range=fitting_range,
        bank_two_theta=bank_two_theta,
    )


def _extract_profile(
    parsed: list[tuple[str, str]], default_profile: str | None
) -> dict[str, float]:
    """``[Profile function]`` (既定・稼働中) ブロックから ``{param: value}`` を抽出する。

    ``[Profile function initial value]`` テンプレート群は対象外 (稼働中の ``[Profile function]`` のみ)。
    サブブロック (``[Name]`` → ``[Value] x`` → ``[End]``) とインラインスカラ (``[h] 1`` 等) を採る。
    """
    start = next((i for i, (tag, _r) in enumerate(parsed) if tag == "Profile function"), None)
    if start is None:
        return {}
    # 稼働中ブロックの終端: 次の "Profile function initial value" 開始、または末尾。
    end = next(
        (
            i
            for i in range(start + 1, len(parsed))
            if parsed[i][0] == "Profile function initial value"
        ),
        len(parsed),
    )
    region = parsed[start + 1: end]
    profile: dict[str, float] = {}
    pending: str | None = None
    for tag, rest in region:
        if tag in {"End", "Identifier", "ID"}:
            pending = None
            continue
        if tag == "Value":
            if pending is not None:
                v = _first_float(rest)
                if v is not None:
                    profile[pending] = v
            pending = None
            continue
        v_inline = _first_float(rest) if rest else None
        if v_inline is not None:
            profile[tag] = v_inline  # インラインスカラ (例 [h] 1)
            pending = None
        else:
            pending = tag  # 次の [Value] を待つサブブロック名
    return profile


def _extract_range(parsed: list[tuple[str, str]]) -> tuple[float, float] | None:
    """``[Peak position]`` ブロック内の ``[Min]``/``[Max]`` を ``(min, max)`` として返す。"""
    idx = next((i for i, (tag, _r) in enumerate(parsed) if tag == "Peak position"), None)
    if idx is None:
        return None
    lo: float | None = None
    hi: float | None = None
    for tag, rest in parsed[idx + 1: idx + 6]:
        if tag == "Min":
            lo = _first_float(rest)
        elif tag == "Max":
            hi = _first_float(rest)
        elif tag == "End":
            break
    if lo is None or hi is None:
        return None
    return lo, hi
