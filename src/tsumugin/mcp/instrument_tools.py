"""薄い MCP ツール — 装置パラメータファイル (``.instprm``) の作成・検査。🔵 FR-502

**なぜ必要か (§4.5 到達可能性)**: ``auto_rietveld`` / ``sequential_rietveld`` /
``anchored_sequential`` はいずれも ``instrument_path`` を要求するが、その値が「どの ② ツールの
出力から来るのか」は Z-Code ``.zDiffractometer`` を持つ利用者 (``write_instrument_params``)
以外に答えが無かった。③ の手順書もすべて装置ファイルを**所与**として書かれており、
持っていない利用者は最初の一歩で詰まっていた。

本モジュールが埋める往復:

1. ``read_pattern_metadata(data_path)`` — 観測データ自身が持つ測定条件を読む
   (XRDML は波長・Kα2 の扱い・反射/透過を持っている)。
2. ``list_instrument_presets()`` — GSAS-II 同梱の既定装置パラメータを列挙する
   (**この 1 つだけ GSAS-II 導入が必要**)。
3. ``create_instrument_params(out_path, ...)`` — instprm を書き出す。返り値の ``path`` を
   ``histograms[].instrument_path`` / ``instrument`` spec の ``path`` へそのまま渡せる。
4. ``inspect_instrument_params(path, ...)`` — **精密化を始める前に**、持っているファイルの
   誤りを告げる (放射源の取り違え・Kα2 整合・必須キー欠落)。
5. ``calibrate_instrument(...)`` — 標準試料 (CeO2/Si) の実測から装置分解能を焼き込む。
   **GSAS-II で実際に精密化を回す重いツール**。

**SDK 非依存**: 素の型 dict のみ。1–4 は numpy/stdlib (GSAS 非依存、プリセットを除く)。
例外は送出せず ``{"error", "error_type"}`` へ縮退する。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from tsumugin.errors import GSASUnavailableError

__all__ = [
    "INSTRUMENT_TOOLS",
    "calibrate_instrument",
    "create_instrument_params",
    "inspect_instrument_params",
    "list_instrument_presets",
    "read_pattern_metadata",
]

#: ``create_instrument_params`` がデータメタから引き継ぐキー (明示引数が常に優先)。
_FROM_DATA_KEYS = ("radiation", "geometry", "wavelength", "wavelength_ka2", "ka2_ratio")


def _error(exc: Exception) -> dict:
    return {"error": str(exc), "error_type": type(exc).__name__}


def read_pattern_metadata(data_path: str, data_format: str | None = None) -> dict:
    """観測データファイルが持つ測定条件を読む (装置ファイルを作るための材料)。

    装置パラメータファイルを持っていない利用者の**出発点**。実際に情報を持つのは現状
    Panalytical XRDML のみで、FXYE/GSAS/XYE/INT/IGOR は波長を構造的に持たない
    (それを外部ファイルに置くのが装置パラメータファイルの役目)。**判らない項目は返さない** —
    Cu Kα と決め打つと放射光データを黙って壊すため。

    :param data_path: 観測データファイル
    :param data_format: 形式名 (``"XRDML"``/``"FXYE"``/``"GSAS"``/``"XYE"``/``"XY"``/``"INT"``/
        ``"IGOR"``)。省略時は拡張子から推定
    :returns: ``{source_format, wavelength?, wavelength_ka2?, ka2_ratio?, kalpha2_stripped?,
        geometry?, radiation?, anode?}``。これらは ``create_instrument_params`` の同名引数へ
        そのまま渡せる。不正形式・ファイル不在は ``{"error", "error_type"}``
    """
    from tsumugin.reference.io import read_pattern_metadata as _read

    try:
        return dict(_read(data_path, data_format))
    except (OSError, ValueError) as exc:
        return _error(exc)


def list_instrument_presets() -> dict:
    """GSAS-II 同梱の既定装置パラメータを列挙する (**GSAS-II 導入が必要**)。

    ``label`` を ``create_instrument_params(preset=...)`` へ渡すと、その内容をそのまま
    instprm として書き出す。``radiation``/``geometry`` は GSAS-II 自身の規則に従って対応づく
    (ラベルに ``lab data`` を含めば Bragg-Brentano)。

    :returns: ``{presets: [{label, radiation, geometry, summary}]}``。GSAS-II 未導入なら
        ``{"error", "error_type"}`` (明示パラメータでの ``create_instrument_params`` は使える)
    """
    from tsumugin.instprm import list_instrument_presets as _list

    try:
        return {"presets": [p.to_dict() for p in _list()]}
    except GSASUnavailableError as exc:
        return _error(exc)


def create_instrument_params(
    out_path: str,
    *,
    preset: str | None = None,
    from_data_path: str | None = None,
    radiation: str | None = None,
    geometry: str | None = None,
    wavelength: float | None = None,
    wavelength_ka2: float | None = None,
    ka2_ratio: float = 0.5,
    zero: float = 0.0,
    polarization: float | None = None,
    profile: Mapping[str, float] | None = None,
    tof: Mapping[str, float] | None = None,
    reason: str = "",
) -> dict:
    """GSAS-II ``.instprm`` を作って書き出す (装置ファイルを持っていない人の入口)。

    3 通りの与え方があり、**明示引数が常に優先**する:

    - ``from_data_path`` — 観測データから測定条件を読んで埋める (XRDML なら 1 回で済む)。
      データが Kα2 除去済みと宣言していれば**二重線にしない** (M9 CaTeO3 で判った最大の
      系統残差を構造的に避ける)。
    - ``preset`` — GSAS-II 同梱の既定をそのまま使う (``list_instrument_presets`` の ``label``)。
      指定時は他のビルド引数を無視し内容を verbatim に書く。
    - 明示指定 — ``radiation`` + ``wavelength`` (TOF は ``radiation`` + ``tof={"difC": ...}``)。

    プロファイル (U,V,W,X,Y,SH/L) は精密化で解放して求めるものなので既定値を置く。標準試料の
    実測値を焼き込みたい場合は ``calibrate_instrument`` を使う。

    :param out_path: 出力 ``.instprm`` パス
    :param preset: プリセット名 (``list_instrument_presets`` の出力)
    :param from_data_path: 測定条件を読む観測データ (``read_pattern_metadata`` と同じ解釈)
    :param radiation: ``"xray_lab"``/``"xray_synchrotron"``/``"neutron_cw"``/``"neutron_tof"``
    :param geometry: ``"bragg_brentano"``/``"debye_scherrer"`` (検査にのみ使う。instprm 自体には
        書かれない — GSAS-II は ``Lam1`` の有無で推定し、tsumugin は宣言側へ矯正する)
    :param wavelength: CW の波長 [Å] (Kα 二重線では Kα1)
    :param wavelength_ka2: Kα2 波長 [Å]。**Kα2 除去済みデータには与えないこと**
    :param tof: TOF の変換係数 (``{"difC":..., "difA":..., "Zero":..., "two_theta":...}``)
    :returns: ``{path, type, radiation, geometry, wavelength, kalpha2_stripped, source,
        ok, findings}``。``path`` は ``histograms[].instrument_path`` / ``instrument`` spec の
        ``path`` へそのまま渡せる。失敗は ``{"error", "error_type"}``
    """
    from tsumugin.instprm import build_instprm_text, inspect_instprm, preset_instprm_text

    meta: dict[str, object] = {}
    if from_data_path is not None:
        loaded = read_pattern_metadata(from_data_path)
        if "error" in loaded:
            return loaded
        meta = loaded

    explicit = {
        "radiation": radiation,
        "geometry": geometry,
        "wavelength": wavelength,
        "wavelength_ka2": wavelength_ka2,
    }
    resolved = {k: explicit.get(k) for k in _FROM_DATA_KEYS}
    resolved["ka2_ratio"] = ka2_ratio
    for key in _FROM_DATA_KEYS:
        if resolved.get(key) is None and key in meta:
            resolved[key] = meta[key]
    stripped = bool(meta.get("kalpha2_stripped", False))
    if stripped and wavelength_ka2 is None:
        # データが「Kα2 は除去済み」と宣言している → 二重線 instprm を作らない。
        resolved["wavelength_ka2"] = None

    try:
        if preset is not None:
            text = preset_instprm_text(preset)
            source = f"preset:{preset}"
            for p in _preset_entry(preset):
                resolved["radiation"] = radiation or p["radiation"]
                resolved["geometry"] = geometry or p["geometry"]
        else:
            if resolved.get("radiation") is None:
                raise ValueError(
                    "radiation が決まりません。radiation を明示するか、preset か "
                    "from_data_path (XRDML 等) を与えてください "
                    "(xray_lab / xray_synchrotron / neutron_cw / neutron_tof)。"
                )
            text = build_instprm_text(
                radiation=resolved["radiation"],
                wavelength=resolved.get("wavelength"),
                wavelength_ka2=resolved.get("wavelength_ka2"),
                ka2_ratio=float(resolved.get("ka2_ratio") or 0.5),
                zero=zero,
                polarization=polarization,
                profile=profile,
                tof=tof,
            )
            source = "data" if from_data_path is not None else "explicit"
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    except (GSASUnavailableError, KeyError, OSError, ValueError) as exc:
        return _error(exc)

    report = inspect_instprm(out, radiation=resolved.get("radiation"), geometry=resolved.get("geometry"))
    values = report.values
    lam = values.get("Lam") or values.get("Lam1")
    return {
        "path": str(out),
        "type": values.get("Type"),
        "radiation": resolved.get("radiation"),
        "geometry": resolved.get("geometry"),
        "wavelength": float(lam) if lam is not None else None,
        "kalpha2_stripped": stripped,
        "source": source,
        "ok": report.ok,
        "findings": [f.to_dict() for f in report.findings],
        "reason": reason,
    }


def _preset_entry(label: str) -> list[dict[str, str]]:
    """プリセット 1 件のメタ (放射源/幾何)。見つからなければ空 (呼び出し側で verbatim 扱い)。"""
    from tsumugin.instprm import list_instrument_presets as _list

    return [p.to_dict() for p in _list() if p.label == label]


def inspect_instrument_params(
    path: str, *, radiation: str | None = None, geometry: str | None = None, reason: str = ""
) -> dict:
    """装置パラメータファイルを**精密化の前に**検査する (持っているファイルが正しいか)。

    実測で判っている失敗形を狙って見る — 放射源の取り違え、Kα1 単色 instprm と反射光学系の
    組み合わせ (データが Kα2 除去済みか要確認)、CW の波長欠落・TOF の difC 欠落、
    ピーク幅ゼロの非物理プロファイル。

    **``severity`` の意味**: ``error`` はこのままでは解析が壊れる / ``question`` はファイル
    だけでは決められず利用者に確認が要る (Kα2 の有無等) / ``warning`` / ``info``。

    :param path: 検査する ``.instprm`` / ``.PRM``
    :param radiation: 解析で宣言する放射源 (``auto_rietveld`` へ渡すのと同じ値)
    :param geometry: 解析で宣言する測定幾何 (同上)
    :returns: ``{path, ok, type, findings: [{code, severity, message, hint}]}``。
        **ファイル不在も error dict ではなく finding として返す** (指摘の方が情報量が多い)
    """
    from tsumugin.instprm import inspect_instprm

    report = inspect_instprm(path, radiation=radiation, geometry=geometry)
    out = report.to_dict()
    out["reason"] = reason
    return out


def calibrate_instrument(
    data_path: str,
    out_path: str,
    *,
    wavelength_init: float,
    standard: str = "CeO2",
    radiation: str = "xray_synchrotron",
    geometry: str = "debye_scherrer",
    cell_a: float | None = None,
    two_theta_limits: tuple[float, float] | None = None,
    background_coeffs: int = 12,
    constrain_nonneg: bool = True,
    reason: str = "",
) -> dict:
    """**GSAS-II で標準試料 (CeO2/Si) を精密化**し装置分解能を instprm へ焼き込む (重いツール)。

    ⚠ 実際に Rietveld 精密化を回すため数十秒〜数分かかる。``create_instrument_params`` が
    「とりあえず動く既定値」を作るのに対し、本ツールは**その装置の実測分解能**を得る。

    格子は認証値に固定し、ゼロ点・試料変位・装置プロファイル (U,V,W,X,Y) を標準に合わせる。
    ⚠ **波長は精密化しない** — 強反射が低角に偏ると波長は試料変位と縮退して分離できない
    (CeO2 実測: 変位固定 +67 ppm・変位解放 +1172 ppm で同 Rwp)。公称波長を信頼して固定する。
    ``constrain_nonneg`` は U,W,X,Y≥0 を課す — **転写可能な分解能には非負拘束が必須**
    (無拘束の解は当該標準にしか合わず、他試料に移すと総 FWHM が負になる)。

    :param data_path: 標準試料の生 2 列 (2θ, 強度) データ (.dat/.xy)
    :param out_path: 出力 ``.instprm`` パス (``histograms[].instrument_path`` へ渡せる)
    :param wavelength_init: 公称波長 [Å] (モノクロメータのエネルギー較正値)
    :param standard: ``"CeO2"`` / ``"Si"`` (立方標準のみ)
    :param two_theta_limits: 精密化レンジ (直接ビーム/低角ノイズの除外に推奨)
    :returns: ``{path, wavelength, zero, profile, source_rwp, ok, findings}``。
        ``source_rwp`` は較正精密化の Rwp (出典の質)。失敗は ``{"error", "error_type"}``
    """
    from tsumugin.autorietveld.model import Geometry, Radiation
    from tsumugin.autorietveld.resolution import calibrate_instrument_from_standard
    from tsumugin.instprm import inspect_instprm, instprm_from_profile

    try:
        limits = tuple(two_theta_limits) if two_theta_limits is not None else None
        result = calibrate_instrument_from_standard(
            data_path,
            wavelength_init=float(wavelength_init),
            standard=standard,
            cell_a=cell_a,
            two_theta_limits=limits,  # type: ignore[arg-type]
            radiation=Radiation(radiation),
            geometry=Geometry(geometry),
            background_coeffs=int(background_coeffs),
            constrain_nonneg=bool(constrain_nonneg),
        )
        text = instprm_from_profile(result, radiation=radiation)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    except (GSASUnavailableError, KeyError, OSError, ValueError) as exc:
        return _error(exc)

    report = inspect_instprm(out, radiation=radiation, geometry=geometry)
    return {
        "path": str(out),
        "wavelength": result.wavelength,
        "zero": result.zero,
        "profile": {str(k): float(v) for k, v in result.profile.items()},
        "source_rwp": result.source_rwp,
        "reference_cell": list(result.reference_cell),
        "ok": report.ok,
        "findings": [f.to_dict() for f in report.findings],
        "reason": reason,
    }


#: MCP_TOOLS へマージする装置パラメータツール (FR-502)。
INSTRUMENT_TOOLS: dict[str, object] = {
    "list_instrument_presets": list_instrument_presets,
    "read_pattern_metadata": read_pattern_metadata,
    "create_instrument_params": create_instrument_params,
    "inspect_instrument_params": inspect_instrument_params,
    "calibrate_instrument": calibrate_instrument,
}
