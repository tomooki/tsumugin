"""GSAS-II 装置パラメータファイル (``.instprm``) の生成・解析・検査。🔵 FR-502

**なぜこのモジュールがあるか**: 装置パラメータファイルは粉末回折解析の最初の関門であり、
初学者が最もつまずく入力である。本リポジトリにも writer は存在したが、いずれも到達経路が
狭かった — ``interop.instrument.write_gsas_instprm`` は Z-Code ``.zDiffractometer`` を持つ
利用者専用、``autorietveld.resolution.pxc_instprm_text`` は X 線単色専用かつ ①内部限定、
``backends.gsasii._write_instprm`` は private。結果として ②MCP から instprm を作れるのは
Z-Code 経路だけで、③ の手順書はすべて ``instrument_path`` を**所与**として扱っていた。

本モジュールは **stdlib のみ**に依存する leaf として、上記 3 経路の共通実装を担う:

- :func:`build_instprm_text` — 放射源・波長 (または TOF 変換係数) から instprm を組む。
  **PXC 単色 / PXC Kα1+Kα2 / PNC (CW 中性子) / PNT (TOF)** を網羅する。
- :func:`parse_instprm` — 1 行 1 キー形式と GSAS 同梱 ``defaultIparms`` の ``;`` 区切り
  ブロック形式の双方を読む。
- :func:`instprm_from_profile` — 標準試料較正 (``autorietveld.resolution``) の結果を
  ファイルへ書き戻す。これが無かったため「生データ → instprm」の経路が閉じていなかった。
- :func:`inspect_instprm` — **精密化を始める前に**、持っているファイルの誤りを告げる。
- :func:`list_instrument_presets` — GSAS-II 同梱の既定装置パラメータ (CuKa ラボ / APS 11BM /
  放射光 0.7 Å / CW 中性子 / TOF 各種) を遅延 import で読む。**この経路のみ GSAS-II を要する**。

放射源・ジオメトリは :class:`~tsumugin.autorietveld.model.Radiation` /
:class:`~tsumugin.autorietveld.model.Geometry` の enum でも、その ``value`` 文字列でも受ける
(① は enum を、②MCP は JSON 文字列を渡すため)。enum 型そのものは import しない —
本モジュールを依存の無い leaf に保ち、``autorietveld`` / ``interop`` / ``backends`` の
いずれからも循環なく import できるようにするため。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tsumugin.errors import GSASUnavailableError

__all__ = [
    "InstprmFinding",
    "InstprmReport",
    "InstrumentPreset",
    "build_instprm_text",
    "inspect_instprm",
    "instprm_from_profile",
    "list_instrument_presets",
    "parse_instprm",
    "preset_instprm_text",
    "write_instprm",
]

#: GSAS difC[μs/Å] = 2·252.816·L[m]·sin(θ)。``fltPath`` の逆算に使う。
_DIFC_CONST = 252.816

#: 放射源 (``Radiation`` の値) → GSAS instprm の ``Type``。
_TYPE_BY_RADIATION: dict[str, str] = {
    "xray_lab": "PXC",
    "xray_synchrotron": "PXC",
    "neutron_cw": "PNC",
    "neutron_tof": "PNT",
}

#: ``Type`` → 放射源候補 (検査で宣言値と突き合わせる)。PXC はラボ/放射光を区別できない。
_RADIATIONS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "PXC": ("xray_lab", "xray_synchrotron"),
    "PNC": ("neutron_cw",),
    "PNT": ("neutron_tof",),
}

#: X 線偏光係数の既定。放射光は水平偏光でほぼ完全偏光、実験室は単色器由来で低い。
_DEFAULT_POLARIZATION: dict[str, float] = {
    "xray_lab": 0.7,
    "xray_synchrotron": 0.95,
    "neutron_cw": 0.0,
}

#: CW プロファイル既定値。X 線と CW 中性子ではピーク幅が桁違いなので分ける
#: (中性子側は GSAS-II 同梱 PNC 既定と同値)。実測値は精密化 (recipe) で解放して求める。
_DEFAULT_PROFILE: dict[str, dict[str, float]] = {
    "PXC": {"U": 2.0, "V": -2.0, "W": 5.0, "X": 0.0, "Y": 0.0, "Z": 0.0, "SH/L": 0.002},
    "PNC": {
        "U": 257.182710995,
        "V": -640.525145369,
        "W": 569.378664828,
        "X": 0.0,
        "Y": 0.0,
        "Z": 0.0,
        "SH/L": 0.002,
    },
}

#: TOF (PNT) の既定。位置を決める difC/difA/Zero は入力必須で、形状既定は概略でよい
#: (残差は recipe の size/mustrain と背景が吸収する — M7 T4 の教訓)。
_DEFAULT_TOF: dict[str, float] = {
    "difA": 0.0,
    "difB": 0.0,
    "Zero": 0.0,
    "alpha": 0.5,
    "beta-0": 0.02,
    "beta-1": 0.0,
    "beta-q": 0.0,
    "sig-0": 0.0,
    "sig-1": 0.0,
    "sig-2": 0.0,
    "sig-q": 0.0,
    "X": 0.0,
    "Y": 0.0,
    "Z": 0.0,
}

#: CW プロファイルのうち「ピーク幅」を担うキー (全て 0 は非物理)。
_WIDTH_KEYS = ("U", "V", "W", "X", "Y")

#: TOF instprm に無いと GSAS が読めない/位置が決まらないキー。
_REQUIRED_TOF_KEYS = ("difC", "fltPath", "2-theta", "Zero")


# =====================================================================
# 数値の書式 (既存 3 writer と互換の桁で出す)
# =====================================================================


def _fmt6(value: float) -> str:
    """小数 6 桁で表す。6 桁で値が変わる場合のみ完全精度へ落ちる。

    波長は ppm 単位の議論をする量なので、丸めで値が変わるときは黙って桁を落とさない
    (0.79958 → ``0.799580`` だが、6 桁で表せない値は ``repr`` で完全精度を保つ)。
    """
    v = float(value)
    s = f"{v:.6f}"
    return s if float(s) == v else repr(v)


def _fmt4(value: float) -> str:
    return f"{float(value):.4f}"


def _fmtr(value: float) -> str:
    """既定値・プロファイル項の書式 (``2.0`` / ``-2.0`` / ``0.002``)。"""
    return repr(float(value))


def _enum_value(value: object) -> str:
    """``Radiation``/``Geometry`` enum でも文字列でも受ける (① と ② の両対応)。"""
    return str(getattr(value, "value", value))


def _require_mapping(value: object, name: str) -> None:
    """``None`` か写像でなければ ``ValueError`` (``AttributeError`` にしない)。"""
    if value is not None and not isinstance(value, Mapping):
        raise ValueError(
            f"{name} は {{キー: 値}} の写像である必要があります "
            f"(受け取ったのは {type(value).__name__})。"
        )


# =====================================================================
# 解析
# =====================================================================


def parse_instprm(text: str) -> dict[str, str]:
    """instprm テキストを ``{キー: 値}`` に読む。

    2 つの書式を受ける:

    - 1 行 1 キー (``Type:PXC``) — 本モジュールと既存 writer の出力
    - 1 行に ``;`` 区切りで複数 (``Type:PXC;Bank:1``) — GSAS-II 同梱 ``defaultIparms``

    キー自身が ``/`` を含む (``SH/L`` · ``I(L2)/I(L1)``) ため、**最初の ``:`` でのみ分割**する。
    ``#`` 始まりの行と空行は無視する。後勝ちで上書きする (GSAS-II のリーダと同じ)。
    """
    out: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for chunk in line.split(";"):
            item = chunk.strip()
            if not item or ":" not in item:
                continue
            key, _, val = item.partition(":")
            out[key.strip()] = val.strip()
    return out


# =====================================================================
# 生成
# =====================================================================


def build_instprm_text(
    *,
    radiation: object,
    wavelength: float | None = None,
    wavelength_ka2: float | None = None,
    ka2_ratio: float = 0.5,
    zero: float = 0.0,
    polarization: float | None = None,
    azimuth: float = 0.0,
    bank: float = 1.0,
    profile: Mapping[str, float] | None = None,
    tof: Mapping[str, float] | None = None,
    creator: str = "tsumugin",
) -> str:
    """放射源と最小限の測定条件から GSAS-II ``.instprm`` テキストを組む。

    **初心者の最小入力は「放射源 + 波長」** (TOF は「放射源 + difC」)。プロファイル
    (U,V,W,X,Y,SH/L) は精密化で解放して求めるものなので、ここでは妥当な既定を置く。
    実測の装置分解能を焼き込みたい場合は :func:`instprm_from_profile` を使う。

    :param radiation: ``Radiation`` enum またはその値 (``"xray_lab"`` 等)
    :param wavelength: CW の波長 [Å]。Kα 二重線では Kα1 を渡す。TOF では無視
    :param wavelength_ka2: Kα2 波長 [Å]。指定すると ``Lam1``/``Lam2``/``I(L2)/I(L1)`` 形式で書く
        (**Kα2 除去済みデータには指定しないこと** — 除去済みに二重線を当てるのが
        実験室 X 線で最大の系統残差になる)
    :param ka2_ratio: Kα2/Kα1 強度比 (既定 0.5)
    :param zero: ゼロ点 [°2θ] (TOF では ``tof["Zero"]`` を使う)
    :param polarization: X 線偏光係数。既定は放射光 0.95 / 実験室 0.7 / 中性子 0.0
    :param profile: プロファイル項の上書き (``U``/``V``/``W``/``X``/``Y``/``Z``/``SH/L`` の部分集合)
    :param tof: TOF の変換係数と形状 (``difC`` 必須。``fltPath`` 省略時は ``2-theta`` から逆算)
    :param creator: 先頭コメント行に残す作成者タグ
    :returns: ``.instprm`` テキスト (末尾改行つき)

    Raises:
        ValueError: 放射源が未知、または放射源に必要な値 (波長 / difC) が欠けるとき。
    """
    rad = _enum_value(radiation)
    gsas_type = _TYPE_BY_RADIATION.get(rad)
    if gsas_type is None:
        known = ", ".join(sorted(_TYPE_BY_RADIATION))
        raise ValueError(f"未知の radiation: {rad!r} (対応: {known})")
    # 写像でない tof/profile は ValueError にする。JSON 由来だと配列や文字列で届きうるが、
    # そのまま `.items()` に触れると AttributeError になり ② の縮退 (ValueError/OSError 等)
    # をすり抜けて例外が境界を越える。
    _require_mapping(tof, "tof")
    _require_mapping(profile, "profile")

    header = f"#GSAS-II instrument parameter file; created by {creator}"
    if gsas_type == "PNT":
        lines = _pnt_lines(tof or {}, azimuth=azimuth, bank=bank, profile=profile)
    else:
        lines = _cw_lines(
            gsas_type,
            radiation=rad,
            wavelength=wavelength,
            wavelength_ka2=wavelength_ka2,
            ka2_ratio=ka2_ratio,
            zero=zero,
            polarization=polarization,
            azimuth=azimuth,
            bank=bank,
            profile=profile,
        )
    return "\n".join([header, *lines]) + "\n"


def _cw_lines(
    gsas_type: str,
    *,
    radiation: str,
    wavelength: float | None,
    wavelength_ka2: float | None,
    ka2_ratio: float,
    zero: float,
    polarization: float | None,
    azimuth: float,
    bank: float,
    profile: Mapping[str, float] | None,
) -> list[str]:
    """CW (PXC / PNC) の instprm 行を組む。"""
    if wavelength is None:
        raise ValueError(
            f"{gsas_type} ({radiation}) の instprm には波長 [Å] が必要です "
            "(wavelength を渡すか、TOF なら radiation='neutron_tof' を使ってください)。"
        )
    polar = polarization if polarization is not None else _DEFAULT_POLARIZATION.get(radiation, 0.0)
    prof = dict(_DEFAULT_PROFILE[gsas_type])
    prof.update({str(k): float(v) for k, v in (profile or {}).items()})

    lines = [f"Type:{gsas_type}", f"Bank:{_fmtr(bank)}"]
    if wavelength_ka2 is not None:
        # 二重線: GSAS-II は Lam1 の存在で Bragg-Brentano を推定する (defaultIparms の規則)。
        lines += [
            f"Lam1:{_fmt6(wavelength)}",
            f"Lam2:{_fmt6(wavelength_ka2)}",
            f"I(L2)/I(L1):{_fmt4(ka2_ratio)}",
        ]
    else:
        lines.append(f"Lam:{_fmt6(wavelength)}")
    lines += [
        f"Zero:{_fmt6(zero)}",
        f"Polariz.:{_fmt4(polar)}",
        f"Azimuth:{_fmtr(azimuth)}",
    ]
    lines += [f"{key}:{_fmtr(prof[key])}" for key in ("U", "V", "W", "X", "Y", "Z", "SH/L")]
    return lines


def _pnt_lines(
    tof: Mapping[str, float],
    *,
    azimuth: float,
    bank: float,
    profile: Mapping[str, float] | None,
) -> list[str]:
    """TOF 中性子 (PNT) の instprm 行を組む。"""
    values = dict(_DEFAULT_TOF)
    values.update({str(k): float(v) for k, v in tof.items()})
    values.update({str(k): float(v) for k, v in (profile or {}).items()})

    if "difC" not in values:
        raise ValueError(
            "TOF (PNT) の instprm には difC が必要です "
            "(tof={'difC': ..., 'difA': ..., 'Zero': ...}。ベンダー較正ファイルの変換係数)。"
        )
    two_theta = float(values.pop("two_theta", values.get("2-theta", 90.0)))
    values["2-theta"] = two_theta
    if "fltPath" not in values:
        # difC = 2·252.816·L·sinθ → L[m]。sinθ≈0 の縮退は既定飛行距離。
        sin_t = math.sin(math.radians(two_theta / 2.0))
        values["fltPath"] = (
            values["difC"] / (2.0 * _DIFC_CONST * sin_t) if sin_t > 1.0e-6 else 20.0
        )

    lines = [
        "Type:PNT",
        f"Bank:{_fmtr(bank)}",
        f"fltPath:{_fmt4(values['fltPath'])}",
        f"2-theta:{_fmt4(two_theta)}",
        f"Azimuth:{_fmtr(azimuth)}",
        f"Zero:{_fmt6(values['Zero'])}",
        f"difC:{_fmt6(values['difC'])}",
        f"difA:{_fmt6(values['difA'])}",
        f"difB:{_fmtr(values['difB'])}",
        f"alpha:{_fmtr(values['alpha'])}",
    ]
    lines += [f"{key}:{_fmtr(values[key])}" for key in ("beta-0", "beta-1", "beta-q")]
    lines += [f"{key}:{_fmt6(values[key])}" for key in ("sig-0", "sig-1", "sig-2")]
    lines += [f"sig-q:{_fmtr(values['sig-q'])}"]
    lines += [f"{key}:{_fmtr(values[key])}" for key in ("X", "Y", "Z")]
    return lines


def write_instprm(path: str | Path, **kwargs: object) -> Path:
    """:func:`build_instprm_text` の結果をファイルへ書く (親ディレクトリは自動作成)。

    :param path: 出力 ``.instprm`` パス
    :param kwargs: :func:`build_instprm_text` へそのまま渡す
    :returns: 書き出した :class:`~pathlib.Path`
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_instprm_text(**kwargs), encoding="utf-8")  # type: ignore[arg-type]
    return out


def instprm_from_profile(
    profile: object,
    *,
    radiation: object,
    wavelength: float | None = None,
    zero: float | None = None,
    creator: str = "tsumugin (standard calibration)",
    **kwargs: object,
) -> str:
    """標準試料較正で得た装置プロファイルを instprm テキストへ書き戻す。

    ``autorietveld.resolution`` の :func:`~tsumugin.autorietveld.resolution.extract_instrument_profile_from_standard`
    (:class:`~tsumugin.autorietveld.model.InstrumentProfile`) と
    :func:`~tsumugin.autorietveld.resolution.calibrate_instrument_from_standard`
    (:class:`~tsumugin.autorietveld.model.CalibrationResult`) の**どちらの出力でも受ける**。
    これまで両者は in-memory の値を返すだけで、ファイルとして次の解析に渡せなかった。

    :param profile: ``InstrumentProfile`` / ``CalibrationResult`` / ``{GSAS キー: 値}`` の写像
    :param radiation: ``Radiation`` enum またはその値
    :param wavelength: 波長 [Å]。省略時は ``profile.wavelength`` を採る (較正後の実効波長)
    :param zero: ゼロ点。省略時は ``profile`` 内の ``Zero`` → ``profile.zero`` の順に採る
    :returns: ``.instprm`` テキスト

    Raises:
        ValueError: CW で波長が判らないとき (``profile`` にも引数にも無い)。
    """
    # ⚠ **素の写像を先に判定する** — `getattr(profile, "values")` は dict に対して
    # 束縛メソッド `dict.values` を返すので、dataclass 想定の duck typing がそのまま
    # 素の dict を壊す (docstring が明示する 3 番目の入力形が TypeError になっていた)。
    if isinstance(profile, Mapping):
        values: Mapping[str, float] = dict(profile)
    else:
        raw = getattr(profile, "values", None)  # InstrumentProfile
        if raw is None:
            raw = getattr(profile, "profile", None)  # CalibrationResult
        if not isinstance(raw, Mapping):
            raise ValueError(
                "profile は InstrumentProfile / CalibrationResult / {GSAS キー: 値} の写像の"
                f"いずれかである必要があります (受け取ったのは {type(profile).__name__})。"
            )
        values = dict(raw)

    lam = wavelength if wavelength is not None else getattr(profile, "wavelength", None)
    if zero is None:
        zero = values.get("Zero", getattr(profile, "zero", None))

    prof = {k: float(v) for k, v in values.items() if k != "Zero"}
    return build_instprm_text(
        radiation=radiation,
        wavelength=lam,
        zero=float(zero) if zero is not None else 0.0,
        profile=prof,
        creator=creator,
        **kwargs,  # type: ignore[arg-type]
    )


# =====================================================================
# 検査 (精密化を始める前に、持っているファイルの誤りを告げる)
# =====================================================================


@dataclass(frozen=True)
class InstprmFinding:
    """装置ファイル検査の指摘 1 件 (不変)。

    :param code: 機械可読な識別子 (③ の分岐と恒久ガードが参照する)
    :param severity: ``"error"`` (このままでは解析が壊れる) / ``"warning"`` /
        ``"question"`` (ファイルだけでは決められず利用者への確認が要る) / ``"info"``
    :param message: 何が起きているか
    :param hint: **次に何をすればよいか** (③ は LLM なので処方まで書く)
    """

    code: str
    severity: str
    message: str
    hint: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "hint": self.hint,
        }


@dataclass(frozen=True)
class InstprmReport:
    """:func:`inspect_instprm` の結果 (不変)。

    :param path: 検査した装置ファイル
    :param values: 読み取れたキー/値 (読めなければ空)
    :param findings: 指摘 (重大な順ではなく検査順)
    """

    path: str
    values: Mapping[str, str] = field(default_factory=dict)
    findings: tuple[InstprmFinding, ...] = ()

    @property
    def ok(self) -> bool:
        """``error`` が 1 件も無いか。``question``/``warning`` は ``ok`` を落とさない。"""
        return not any(f.severity == "error" for f in self.findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "ok": self.ok,
            "type": self.values.get("Type"),
            "findings": [f.to_dict() for f in self.findings],
        }


def inspect_instprm(
    path: str | Path,
    *,
    radiation: object | None = None,
    geometry: object | None = None,
) -> InstprmReport:
    """装置パラメータファイルを**精密化の前に**検査する。

    実測で判っている失敗形を狙って見る:

    - 宣言 ``radiation`` と ``Type:`` の取り違え (中性子ファイルを X 線として渡す等)
    - **Kα1 単色 instprm × 反射光学系** — GSAS-II は ``Lam1`` の有無で試料 ``Type`` を推定するため、
      この組み合わせでは Debye-Scherrer 扱いになる。``autorietveld.engine._apply_sample_geometry``
      が宣言ジオメトリへ矯正するので精密化自体は走るが、**データが Kα2 除去済みでない**場合は
      最大の系統残差になる (M9 CaTeO3)。
    - Kα1+Kα2 instprm — データが Kα2 除去済みかどうかはファイルからは判らないので、
      断定せず ``question`` として利用者に確認を促す。
    - 必須キー欠落 (CW の波長 / TOF の difC 等) と、ピーク幅ゼロの非物理なプロファイル。

    **例外を送出しない** — 読めないファイルも ``error`` の finding として返す
    (② 境界を跨ぐため。存在しないパスで ``FileNotFoundError`` を投げない)。

    :param path: 検査する ``.instprm`` / ``.PRM``
    :param radiation: 解析で宣言する放射源 (``Radiation`` enum またはその値)。省略可
    :param geometry: 解析で宣言する測定幾何 (``Geometry`` enum またはその値)。省略可
    :returns: :class:`InstprmReport`
    """
    p = Path(path)
    findings: list[InstprmFinding] = []
    if not p.is_file():
        return InstprmReport(
            path=str(p),
            findings=(
                InstprmFinding(
                    code="file_not_found",
                    severity="error",
                    message=f"装置パラメータファイルが見つかりません: {p}",
                    hint=(
                        "パスを確認するか、装置ファイルを持っていない場合は "
                        "create_instrument_params / list_instrument_presets で作成してください。"
                    ),
                ),
            ),
        )
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - 権限等の環境依存
        return InstprmReport(
            path=str(p),
            findings=(
                InstprmFinding(
                    code="unreadable",
                    severity="error",
                    message=f"装置パラメータファイルを読めません: {exc}",
                    hint="ファイルの権限とエンコーディング (UTF-8) を確認してください。",
                ),
            ),
        )

    values = parse_instprm(text)
    if "Type" not in values:
        # 旧 GSAS `.PRM` (固定桁 `INS ` 行)。GSAS-II は問題なく読むので「装置ファイルではない」
        # と断じてはならない (README の例も M7 チュートリアルもこの形式)。
        values = {**_parse_legacy_prm(text), **values}
    gsas_type = values.get("Type")
    if gsas_type is None:
        findings.append(
            InstprmFinding(
                code="no_type_key",
                severity="error",
                message="instprm に Type: キーがありません (装置パラメータファイルではない可能性)。",
                hint=(
                    "GSAS-II の .instprm か旧 .PRM を指しているか確認してください。"
                    "観測データファイルを誤って渡していることが多いです。"
                ),
            )
        )
        return InstprmReport(path=str(p), values=values, findings=tuple(findings))

    findings += _check_type(gsas_type, radiation)
    if gsas_type == "PNT":
        findings += _check_tof(values)
    else:
        findings += _check_cw(values, geometry)
    return InstprmReport(path=str(p), values=values, findings=tuple(findings))


def _check_type(gsas_type: str, radiation: object | None) -> list[InstprmFinding]:
    """``Type:`` の妥当性と宣言 ``radiation`` との整合。"""
    if gsas_type not in _RADIATIONS_BY_TYPE:
        return [
            InstprmFinding(
                code="unknown_type",
                severity="warning",
                message=f"未対応の Type です: {gsas_type} (対応: PXC / PNC / PNT)。",
                hint=(
                    "エネルギー分散 (PXE) 等は tsumugin の Radiation に対応がありません。"
                    "CW か TOF のファイルを用意してください。"
                ),
            )
        ]
    if radiation is None:
        return []
    rad = _enum_value(radiation)
    if rad in _RADIATIONS_BY_TYPE[gsas_type]:
        return []
    expected = _TYPE_BY_RADIATION.get(rad, "?")
    return [
        InstprmFinding(
            code="radiation_type_mismatch",
            severity="error",
            message=(
                f"instprm の Type:{gsas_type} は宣言した radiation={rad} "
                f"(期待する Type:{expected}) と食い違います。"
            ),
            hint=(
                "別の測定の装置ファイルを渡していないか確認してください。"
                f"radiation={rad} の装置ファイルが無ければ create_instrument_params で作れます。"
            ),
        )
    ]


def _check_cw(values: Mapping[str, str], geometry: object | None) -> list[InstprmFinding]:
    """CW (PXC/PNC) の必須キー・Kα2 整合・ピーク幅。"""
    out: list[InstprmFinding] = []
    has_lam1 = "Lam1" in values
    if not has_lam1 and "Lam" not in values:
        out.append(
            InstprmFinding(
                code="missing_wavelength",
                severity="error",
                message="CW の instprm に波長 (Lam または Lam1) がありません。",
                hint=(
                    "波長を確認して create_instrument_params(wavelength=...) で作り直すか、"
                    "read_pattern_metadata でデータファイルから波長を読めるか確かめてください。"
                ),
            )
        )
    geom = _enum_value(geometry) if geometry is not None else None
    if has_lam1:
        out.append(
            InstprmFinding(
                code="kalpha2_consistency_question",
                severity="question",
                message=(
                    "この instprm は Kα1+Kα2 の二重線モデルです (Lam1/Lam2)。"
                    "観測データが Kα2 除去済み (単色化済み) の場合、Kα2 の phantom ピークが"
                    "最大の系統残差になります。"
                ),
                hint=(
                    "データが Kα2 除去済みかを確認してください。除去済みなら "
                    "create_instrument_params(wavelength=Kα1 のみ) で単色 instprm を作り直します。"
                ),
            )
        )
    elif geom == "bragg_brentano":
        out.append(
            InstprmFinding(
                code="kalpha1_only_bragg_brentano",
                severity="info",
                message=(
                    "Kα1 単色 instprm を Bragg-Brentano (反射光学系) と宣言しています。"
                    "GSAS-II は Lam1 の有無で試料 Type を推定するため、この instprm 単体では "
                    "Debye-Scherrer と見なされます (tsumugin は宣言ジオメトリ側へ矯正します)。"
                ),
                hint=(
                    "データが Kα2 除去済みならこのままで正しい組み合わせです。"
                    "未除去なら wavelength_ka2 を与えて二重線 instprm を作り直してください。"
                ),
            )
        )
    widths = [float(values[k]) for k in _WIDTH_KEYS if k in values and _is_float(values[k])]
    if widths and all(abs(w) < 1.0e-12 for w in widths):
        out.append(
            InstprmFinding(
                code="zero_peak_width",
                severity="error",
                message="プロファイル U,V,W,X,Y がすべて 0 です (ピーク幅ゼロ = 非物理)。",
                hint=(
                    "装置分解能の初期値を入れてください。標準試料 (CeO2/Si) を測っていれば "
                    "calibrate_instrument で実測値を焼き込めます。"
                ),
            )
        )
    return out


def _check_tof(values: Mapping[str, str]) -> list[InstprmFinding]:
    """TOF (PNT) の必須キー。"""
    missing = [k for k in _REQUIRED_TOF_KEYS if k not in values]
    if not missing:
        return []
    return [
        InstprmFinding(
            code="missing_tof_keys",
            severity="error",
            message=f"TOF の instprm に必須キーがありません: {', '.join(missing)}。",
            hint=(
                "ベンダー較正ファイルから変換係数を取り込んでください "
                "(Z-Code なら write_instrument_params、手入力なら "
                "create_instrument_params(tof={'difC': ...}))。"
            ),
        )
    ]


def _parse_legacy_prm(text: str) -> dict[str, str]:
    """旧 GSAS ``.PRM`` (固定桁 ``INS `` 行) を検査用のキー空間へ正規化する。

    検査に要る最小限だけ読む — ``HTYPE`` (放射源) と ``ICONS`` (波長・ゼロ点)。
    ``HTYPE PXCR`` の先頭 3 文字が ``Type``、``ICONS`` は ``<λ1> <λ2> <Zero> …`` で
    **λ2 が正なら Kα 二重線** (``.instprm`` の ``Lam1``/``Lam2`` に対応する)。

    ⚠ **``ICONS`` の意味は放射源で変わる**。CW は ``<λ1> <λ2> <Zero> …``、TOF は
    ``<difC> <difA> <Zero>``。よって ``HTYPE`` を**先に**確定させてから解釈する
    (順序に依存すると、TOF の difC を波長として読み「必須キーが無い」と誤診する)。
    TOF の飛行距離とバンク角は ``BNKPAR`` 行 (``<fltPath> <2-theta>``) から採る。

    ⚠ プロファイル係数 (``PRCF1x``) はここでは読まない。型によって意味が変わり
    (``topas.instrument._read_prm`` 参照)、誤読するとローレンツ幅を捏造することになる。
    幅ゼロ検査は ``U``/``V``/``W`` が無ければ静かに飛ぶ (検査しないだけで嘘は言わない)。
    """
    ins_lines = [raw[4:] for raw in text.splitlines() if raw.startswith("INS ")]
    values: dict[str, str] = {}
    for body in ins_lines:
        if "HTYPE" in body:
            token = body.split("HTYPE", 1)[1].strip().split()
            if token and token[0][:3].upper() in _RADIATIONS_BY_TYPE:
                values["Type"] = token[0][:3].upper()
                break
    is_tof = values.get("Type") == "PNT"

    for body in ins_lines:
        if "ICONS" in body:
            numbers = _numbers_after(body, "ICONS")
            if not numbers:
                continue
            if is_tof:
                # TOF: difC difA Zero (difB は旧形式に無いので 0 のまま既定に任せる)
                values["difC"] = repr(numbers[0])
                if len(numbers) >= 2:
                    values["difA"] = repr(numbers[1])
                if len(numbers) >= 3:
                    values["Zero"] = repr(numbers[2])
                continue
            lam2 = numbers[1] if len(numbers) >= 2 else 0.0
            if lam2 > 0.0:
                values["Lam1"] = repr(numbers[0])
                values["Lam2"] = repr(lam2)
            else:
                values["Lam"] = repr(numbers[0])
            if len(numbers) >= 3:
                values["Zero"] = repr(numbers[2])
        elif is_tof and "BNKPAR" in body:
            numbers = _numbers_after(body, "BNKPAR")
            if numbers:
                values["fltPath"] = repr(numbers[0])
            if len(numbers) >= 2:
                values["2-theta"] = repr(numbers[1])
    return values


def _numbers_after(body: str, marker: str) -> list[float]:
    """``INS`` 行の ``<marker>`` 以降の数値トークンを順に拾う。"""
    return [float(t) for t in body.split(marker, 1)[1].split() if _is_float(t)]


def _is_float(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


# =====================================================================
# プリセット (GSAS-II 同梱 defaultIparms の遅延 import)
# =====================================================================


@dataclass(frozen=True)
class InstrumentPreset:
    """GSAS-II 同梱の既定装置パラメータ 1 件 (不変)。

    :param label: GSAS-II の ``defaultIparm_lbl`` の表示名 (``preset_instprm_text`` の引数)
    :param radiation: 対応する ``Radiation`` の値
    :param geometry: 対応する ``Geometry`` の値
    :param text: instprm テキストそのもの
    :param summary: 波長 / difC 等の要約 (③ が選ぶための材料)
    """

    label: str
    radiation: str
    geometry: str
    text: str
    summary: str

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "radiation": self.radiation,
            "geometry": self.geometry,
            "summary": self.summary,
        }


def _load_default_iparms() -> Sequence[tuple[str, str]]:
    """GSAS-II 同梱の既定装置パラメータを ``(ラベル, テキスト)`` で返す (遅延 import)。"""
    try:
        from GSASII.defaultIparms import defaultIparm_lbl, defaultIparms
    except ImportError as exc:
        raise GSASUnavailableError(
            "装置パラメータのプリセットは GSAS-II 同梱の defaultIparms を読みます。"
            "GSAS-II 未導入の環境では create_instrument_params に radiation と wavelength を"
            "明示指定してください (プリセット無しでも instprm は作れます)。"
        ) from exc
    return [(lbl, "".join(lines)) for lbl, lines in zip(defaultIparm_lbl, defaultIparms)]


def list_instrument_presets() -> tuple[InstrumentPreset, ...]:
    """GSAS-II 同梱の既定装置パラメータを列挙する。**GSAS-II 導入が必要**。

    ``Radiation`` に対応の無い形式 (エネルギー分散 ``PXE`` 等) は除外する。
    ``Geometry`` は GSAS-II 自身の規則 — **ラベルに ``lab data`` を含めば Bragg-Brentano、
    それ以外は Debye-Scherrer** (``GSASII/defaultIparms.py`` のコメント) — をそのまま写す。

    Raises:
        GSASUnavailableError: GSAS-II が未導入のとき。
    """
    presets: list[InstrumentPreset] = []
    for label, text in _load_default_iparms():
        values = parse_instprm(text)
        gsas_type = values.get("Type", "")
        if gsas_type not in _RADIATIONS_BY_TYPE:
            continue
        is_lab = "lab data" in label.lower()
        if gsas_type == "PXC":
            radiation = "xray_lab" if is_lab else "xray_synchrotron"
        else:
            radiation = _RADIATIONS_BY_TYPE[gsas_type][0]
        presets.append(
            InstrumentPreset(
                label=label,
                radiation=radiation,
                geometry="bragg_brentano" if is_lab else "debye_scherrer",
                text=text,
                summary=_preset_summary(values),
            )
        )
    return tuple(presets)


def _preset_summary(values: Mapping[str, str]) -> str:
    """プリセットを選ぶ材料になる 1 行 (波長 / TOF 変換係数)。"""
    if "Lam1" in values:
        return f"Kα1={values['Lam1']} Å / Kα2={values.get('Lam2', '?')} Å (二重線)"
    if "Lam" in values:
        return f"λ={values['Lam']} Å (単色)"
    if "difC" in values:
        return f"TOF difC={values['difC']} / 2θ={values.get('2-theta', '?')}°"
    return ""


def preset_instprm_text(label: str) -> str:
    """プリセット名から instprm テキストを取り出す。**GSAS-II 導入が必要**。

    Raises:
        GSASUnavailableError: GSAS-II が未導入のとき。
        KeyError: ラベルが未登録のとき。
    """
    presets = list_instrument_presets()
    for preset in presets:
        if preset.label == label:
            return preset.text
    known = ", ".join(p.label for p in presets)
    raise KeyError(f"未登録のプリセット: {label!r} (登録済: {known})")
