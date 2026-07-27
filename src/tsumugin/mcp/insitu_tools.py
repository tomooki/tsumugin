"""薄い MCP 3 ツール (M9 要素3) — 高温 in situ 逐次 Rietveld の計器+アクチュエータ。

M8 の `rietveld_tools` と同じ設計 (二重反転回避): 閉ループ丸ごとは出さず、③ (Claude Code) が
以下を反復駆動して系列解析を進める。

- ``sequential_rietveld``: frames + initial_phases spec (JSON) を run_sequential_rietveld で実行 →
  フレーム別 Rwp/格子/相分率・変化点・自動出現相を構造化して返す。実運用の装置設定 (放射源/
  ジオメトリ/instprm/背景項数) は ``instrument`` spec (JSON) でサーバ側の runner 組み立てに渡す
  (Issue #93: ``runner`` callable は JSON 境界を越えられないため、③ の実データ解析には instrument が必須)。
- ``identify_and_add_phase``: 残差/生パターン + elements → MP で新相を同定・CIF 物質化し PhaseSpec を返す
  (相追加の候補提示; 実際の採否・再精密化は ③ が sequential_rietveld/refine で行う)。
- ``parametric_fit``: 系列結果 (JSON) + parameter/axis → 熱膨張多項式係数・転移 onset/midpoint±σ。
  転移は **既定で重量分率基準** (``basis="weight"`` = 出版値)。Scale 基準は明示要求時のみで、
  結果は常に ``fraction_basis`` にどちらで出したかを明示する (Scale 由来の転移値は出版不可)。

**SDK 非依存**: 素の型 dict のみ (json.dumps allow_nan=False 安全)。GSAS/MP は runner/finder 内で
遅延 import。runner/finder/provider/materializer は注入可能 (テストは決定論スタブ)。

信頼性: 🔵 architecture.md §6 の M9 3 ツール表と 1:1。
"""

from __future__ import annotations

import csv
from typing import Callable, Mapping, Sequence

from .._json import finite_or_none
from ..autorietveld import PhaseSpec
from ._degrade import degrade_oserror
import dataclasses

from ..insitu.model import (
    ChargeConstraintConfig,
    FrameRietveldResult,
    FrameSpec,
    PhaseIdConfig,
    SequentialConfig,
    SequentialRietveldResult,
    TargetComposition,
)

__all__ = [
    "INSITU_TOOLS",
    "identify_and_add_phase",
    "parametric_fit",
    "sequential_rietveld",
    "write_sequential_csv",
]

#: FR-504 トラジェクトリ CSV のフレーム共通列 (固定・先頭順)。
#: M2 ``sequential.trajectory._FRAME_COMMON_COLUMNS`` と役割は同じだが、列自体は M9
#: ``SequentialRietveldResult``/``seq_result_to_dict`` が実際に持つフィールドのみで構成する
#: (M2 Trajectory の列をそのまま真似ない — 無い列を空欄で埋めて「あるように見せる」のは禁止)。
_SEQ_CSV_COMMON_COLUMNS = [
    "frame_index",
    "data_path",
    "axis_value",
    "rwp",
    "gof",
    "changepoint",
    "changepoint_reasons",
    "refine_failed",
]
#: 相ごと列の接尾辞。``refined_cells``/``cell_esd`` は (a,b,c,α,β,γ) の先頭 3 (a,b,c) のみを
#: CSV へ出す (M2 Trajectory と同じ設計裁量 — 角度 σ は CSV 列を肥大させないため JSON 側で見る)。
#: M2 の ``sigma_source``/lifecycle 3 列 (birth_frame/death_frame/confidence) は含めない —
#: M9 のフレーム行にはこれらに対応する列が無い (birth は ``appearances`` に別スキーマで出るが
#: death/confidence は持たず、フレーム単位の行に相ライフサイクルは自然にマップしない)。
#: 無い値を空欄で埋めると「持っているように見える」偽装になるため、列自体を作らない。
_SEQ_CSV_PHASE_SUFFIXES = [
    "a",
    "b",
    "c",
    "a_esd",
    "b_esd",
    "c_esd",
    "scale",
    "wt_frac",
    "wt_frac_esd",
]
_SEQ_CSV_REASONS_DELIMITER = "|"


def _seq_csv_num_cell(value: object) -> str:
    """CSV セル用の数値純化 (有限は str、None/非有限 (inf/-inf/NaN) は空欄)。

    ``sequential.trajectory._num_cell`` / ``operando.output._num_cell`` と同一セマンティクス
    (Issue #5 の単一情報源判定へ委譲・書式は元値保持)。本モジュール専用の第三の複製だが、
    層をまたいだ私有 import は既存 2 者間でも避けられている設計裁量を踏襲する。
    """
    return "" if finite_or_none(value) is None else str(value)  # type: ignore[arg-type]


def _seq_csv_phase_refs(result: Mapping[str, object]) -> list[str]:
    """CSV に出す相 ref の集合を全フレームの ``phase_names`` ∪ トップレベル ``phase_names`` から
    sorted 昇順で確定する (Trajectory._sorted_phase_refs と同じ決定論方針)。
    """
    refs: set[str] = set(str(p) for p in result.get("phase_names", ()))  # type: ignore[union-attr]
    for fd in result.get("frames", ()):  # type: ignore[union-attr]
        for p in fd.get("phase_names", ()) if isinstance(fd, Mapping) else ():  # type: ignore[union-attr]
            refs.add(str(p))
    return sorted(refs)


def _seq_csv_header(phase_refs: Sequence[str]) -> list[str]:
    columns = list(_SEQ_CSV_COMMON_COLUMNS)
    for ref in phase_refs:
        columns.extend(f"{ref}.{suffix}" for suffix in _SEQ_CSV_PHASE_SUFFIXES)
    return columns


def _seq_csv_row(fd: Mapping[str, object], phase_refs: Sequence[str]) -> list[str]:
    row = [
        _seq_csv_num_cell(fd.get("frame_index")),
        str(fd.get("data_path", "")),
        _seq_csv_num_cell(fd.get("axis_value")),
        _seq_csv_num_cell(fd.get("rwp")),
        _seq_csv_num_cell(fd.get("gof")),
        str(bool(fd.get("changepoint", False))),
        _SEQ_CSV_REASONS_DELIMITER.join(str(r) for r in fd.get("changepoint_reasons", ())),  # type: ignore[union-attr]
        str(bool(fd.get("refine_failed", False))),
    ]
    refined_cells = fd.get("refined_cells") or {}
    cell_esd = fd.get("cell_esd") or {}
    phase_fractions = fd.get("phase_fractions") or {}
    weight_fractions = fd.get("phase_weight_fractions") or {}
    weight_esd = fd.get("phase_weight_fraction_esd") or {}
    for ref in phase_refs:
        cell = refined_cells.get(ref)  # type: ignore[union-attr]
        esd = cell_esd.get(ref)  # type: ignore[union-attr]
        row.extend(
            [
                _seq_csv_num_cell(cell[0]) if cell else "",
                _seq_csv_num_cell(cell[1]) if cell else "",
                _seq_csv_num_cell(cell[2]) if cell else "",
                _seq_csv_num_cell(esd[0]) if esd else "",
                _seq_csv_num_cell(esd[1]) if esd else "",
                _seq_csv_num_cell(esd[2]) if esd else "",
                _seq_csv_num_cell(phase_fractions.get(ref)),  # type: ignore[union-attr]
                _seq_csv_num_cell(weight_fractions.get(ref)),  # type: ignore[union-attr]
                _seq_csv_num_cell(weight_esd.get(ref)),  # type: ignore[union-attr]
            ]
        )
    return row


def _cells_dict(cells: Mapping[str, Sequence[float]]) -> dict[str, list[float | None]]:
    return {name: [finite_or_none(v) for v in cell] for name, cell in cells.items()}


def _frame_residual_report(f: "FrameRietveldResult") -> dict[str, object] | None:
    """フレームの残差レポートを素の型 dict へ (None = 残差なし; キーは常に存在させる)。

    【単一 serializer】: ``auto_rietveld`` 経路 (``rietveld_tools._result_to_dict``) と同じ
      ``operando_diag_tools.residual_report_to_dict`` を使い、③ から見た残差レポートの形が経路に
      よらず一致することを保証する (二重実装を作らない)。**関数内 import** なのは
      ``operando_diag_tools`` が本モジュールの ``_result_from_dict`` を module-level で import して
      いるため (module-level に上げると循環 import になる)。
    """
    from .operando_diag_tools import residual_report_to_dict

    rep = f.residual_report
    return None if rep is None else residual_report_to_dict(rep)


def seq_result_to_dict(result: SequentialRietveldResult) -> dict[str, object]:
    """SequentialRietveldResult を素の型 dict へ (③ の判断入力・parametric_fit 入力)。

    ⚠ **``phase_fractions`` は Scale であって重量分率ではない**。定量相分析・出版値には
    ``phase_weight_fractions`` (± ``phase_weight_fraction_esd``) を使うこと (Issue #96 レビュー)。

    各フレームには ``residual_report`` を同梱する (architecture.md §4.5 到達可能性 #3): 単独の
    ``residual_report`` ツールは配列入力を要し、``auto_rietveld`` フォールバックは ``FrameSpec``
    から作れない ``HistogramSpec`` を要するため、**同梱しないと系列フレームの J2/J3 (未説明ピーク
    → 欠落相 / 強度比異常 → 対称性低下) は ③ からは原理的に answer 不能**になる。残差配列自体は
    境界を跨がせない (engine が `ResidualReport` に畳んだものを直列化するだけ)。
    """
    return {
        "phase_names": list(result.phase_names),
        "frames": [
            {
                "frame_index": f.frame_index,
                "axis_value": f.axis_value,
                "data_path": f.data_path,
                "rwp": finite_or_none(f.rwp),
                "gof": finite_or_none(f.gof),
                "phase_names": list(f.phase_names),
                "refined_cells": _cells_dict(f.refined_cells),
                "phase_fractions": {k: finite_or_none(v) for k, v in f.phase_fractions.items()},
                "changepoint": bool(f.changepoint),
                "changepoint_reasons": list(f.changepoint_reasons),
                "validity_passed": bool(f.validity_passed),
                "refine_failed": bool(f.refine_failed),
                # 【残差レポート同梱】: 残差なし (スタブ runner 等) でもキーは None で存在させ、
                #   ③ から見たスキーマを安定させる (auto_rietveld 経路と同一規律) 🔵 §4.5
                "residual_report": _frame_residual_report(f),
                # 【出版値 (Issue #96 レビュー)】: operando の主要な報告値は「相分率 vs 時間」だが、
                #   上の `phase_fractions` は **Scale** であって重量分率ではない (単位胞質量が相間で
                #   異なると乖離。実測 K2Mn[Fe(CN)6] tetra: 65.6 Scale% は同じ fit で **47.2 wt%**)。
                #   乖離はフレーム毎に違い (実測 1.39-1.62 倍)、大きさは相の単位胞質量比
                #   (cubic 1103.4 / tetra 517.8 amu = 2.13 倍) と分率で決まる = **換算係数は無い**。
                #   ③ が Scale しか受け取れなければ報告する定量値がそのまま誤る。esd 無しでは出版も
                #   できない。キーは常に存在 (欠落と esd=0 の取り違えを防ぐ; 上と同一規律) 🔵
                "phase_weight_fractions": {
                    k: finite_or_none(v) for k, v in f.phase_weight_fractions.items()
                },
                "phase_weight_fraction_esd": {
                    k: finite_or_none(v) for k, v in f.phase_weight_fraction_esd.items()
                },
                "cell_esd": {
                    k: [finite_or_none(x) for x in esd] for k, esd in f.cell_esd.items()
                },
                # 【FR-318 電気化学制約の診断】: x_XRD vs x_echem・適用拘束・実行可能性。
                #   機能無効フレームは None/空/"" (キーは常に存在 — スキーマ安定の同一規律)。
                #   infeasible = クーロメトリー目標が相組成の範囲外 = 不可逆容量/副反応の疑い。
                "alkali_x_echem": finite_or_none(f.alkali_x_echem)
                if f.alkali_x_echem is not None else None,
                "alkali_x_xrd": finite_or_none(f.alkali_x_xrd)
                if f.alkali_x_xrd is not None else None,
                "alkali_x_xrd_esd": finite_or_none(f.alkali_x_xrd_esd)
                if f.alkali_x_xrd_esd is not None else None,
                "alkali_per_phase": {
                    k: finite_or_none(v) for k, v in f.alkali_per_phase.items()
                },
                "alkali_residual": finite_or_none(f.alkali_residual)
                if f.alkali_residual is not None else None,
                "alkali_constraint_applied": str(f.alkali_constraint_applied),
                "alkali_feasibility": str(f.alkali_feasibility),
            }
            for f in result.frames
        ],
        "appearances": [
            {
                "phase_name": a.phase_name,
                "frame_index": a.frame_index,
                "axis_value": a.axis_value,
                "structure_path": a.structure_path,
                "source": a.source,
                "rwp_before": finite_or_none(a.rwp_before),
                "rwp_after": finite_or_none(a.rwp_after),
                "evidence": {k: _jsonable(v) for k, v in a.evidence.items()},
            }
            for a in result.appearances
        ],
        "warnings": list(result.warnings),
    }


def _jsonable(v: object) -> object:
    """evidence 値を json 安全化 (float は finite_or_none)。"""
    if isinstance(v, float):
        return finite_or_none(v)
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    return str(v)


def _result_from_dict(d: Mapping[str, object]) -> SequentialRietveldResult:
    """seq_result_to_dict の逆写像 (parametric_fit が受け取る系列結果)。最小フィールドのみ復元。

    ``residual_report`` は復元しない (往復先の消費者 — parametric_fit / check_phase_set /
    repair_frames — はいずれも残差を見ない。③ は同梱された dict を直接読む)。

    **``phase_weight_fractions`` は復元する** (Issue #96 レビュー第4巡 HIGH): `parametric_fit` は
    ここで復元した系列から転移 onset/midpoint を**導出する** = 出版値を作る表面であり、往復で
    重量分率が落ちると `basis="weight"` は「重量分率が無い」と答えるほかなく、③ から見て
    **重量分率基準の転移は原理的に到達不能**になる (実際に落ちていた: `seq_result_to_dict` は
    出力していたが本関数が捨てていたため、② の配線は片道しか繋がっていなかった)。
    esd は復元しない (転移推定は値のみを使い、esd が要る ③ は元の dict を直接読む)。
    """
    frames = []
    for fd in d.get("frames", []):  # type: ignore[union-attr]
        cells = {
            name: tuple(float(x) for x in cell)
            for name, cell in (fd.get("refined_cells") or {}).items()
            if all(x is not None for x in cell)
        }
        frames.append(
            FrameRietveldResult(
                frame_index=int(fd["frame_index"]),
                axis_value=fd.get("axis_value"),
                data_path=str(fd.get("data_path", "")),
                rwp=float(fd["rwp"]) if fd.get("rwp") is not None else float("inf"),
                gof=float(fd["gof"]) if fd.get("gof") is not None else float("inf"),
                refined_cells=cells,
                phase_fractions={
                    k: float(v) for k, v in (fd.get("phase_fractions") or {}).items() if v is not None
                },
                phase_names=tuple(fd.get("phase_names", ())),
                refine_failed=bool(fd.get("refine_failed", False)),
                phase_weight_fractions={
                    k: float(v)
                    for k, v in (fd.get("phase_weight_fractions") or {}).items()
                    if v is not None
                },
            )
        )
    return SequentialRietveldResult(
        frames=tuple(frames), phase_names=tuple(d.get("phase_names", ()))
    )


#: 系列結果の各フレームが**判断に足る**ために最低限持つべきキー。``seq_result_to_dict`` は常に
#: この 3 つを出す (値が None でも可)。欠けた dict は ``_result_from_dict`` が既定値
#: (rwp=inf / phase_names=()) で黙って埋めるため、**キーの有無でしか欠落を検出できない**。
_REQUIRED_FRAME_KEYS = ("frame_index", "rwp", "phase_names")


def _validate_seq_result(result: Mapping[str, object]) -> None:
    """系列結果 dict が判断に足る形かを**判定/精密化/導出の前に**検証する。

    **``_result_from_dict`` の寛容さの対**であるため本モジュール (復元器の隣) に置く。復元器は
    ``d.get("frames", [])`` で **``frames`` キーの無い dict を例外にせず空の系列**へ復元する。
    そのため検証を挟まない消費者は**ゴミ入力から自信のある答えを出す**:

    - ``check_phase_set({"nope": 1})`` → ``is_complete=True`` / ``union=[]`` (「相集合は完全」)。
    - ``parametric_fit({}, "tetra")`` → ``fraction_basis="weight"`` / ``transition=None``
      (「重量分率基準で見て転移なし」)。**0 フレームなら重量分率の欠測も 0 件**なので
      `FractionBasisUnavailableError` すら出ず、③ の
      ``assert pf["fraction_basis"] == "weight"`` (skills/insitu・AGENT_PLAYBOOK が指示する
      検算) は**素通りする**。

    どちらも **③ に「疑わなくてよい」と告げる**最悪の失敗様態である (CLAUDE.md ② 不変条件:
    空/不正入力を「正常」と答えない)。何も判断できないときは判断を返してはならず、error dict へ
    縮退する (``insitu.model.FractionBasisUnavailableError`` の「『転移なし』へ縮退するのも禁止 —
    本物の『転移なし』と区別が付かなくなる」と同じ規律)。

    ``frames`` が空の系列も**エラーとする**: 判断の対象が存在しない以上「完全」とも「転移なし」
    とも言えず、黙ってそう答えるのは上と同じ不安全である (系列結果は必ず 1 フレーム以上を持つ)。

    :raises ValueError: ``result`` が Mapping でない、``frames`` が無い/空/列でない、
        フレームが dict でない、フレームが ``_REQUIRED_FRAME_KEYS`` を欠くとき
    """
    if not isinstance(result, Mapping):
        raise ValueError(
            f"result は系列結果 dict である必要があります: {type(result).__name__}"
        )
    if "frames" not in result:
        raise ValueError(
            "result に 'frames' キーがありません。**sequential_rietveld** が返す系列結果 dict を"
            "そのまま渡してください (空の系列を「相集合は完全」/「転移なし」と判定しないため"
            "打ち切ります)。"
            "注: repair_frames の戻り値は系列結果ではない (repairs/needs_model_revision のみ) ので"
            "渡せません — 修復後の系列が要るなら sequential_rietveld を再実行してください。"
        )
    frames = result["frames"]
    if isinstance(frames, (str, bytes)) or not isinstance(frames, Sequence):
        raise ValueError(
            f"result['frames'] はフレーム dict の列である必要があります: {type(frames).__name__}"
        )
    if not frames:
        raise ValueError(
            "result['frames'] が空です。判断の対象が無い系列を「相集合は完全」「転移なし」とは"
            "報告できません (系列を実行できていない可能性があります — sequential_rietveld の"
            "結果を確認してください)。"
        )
    for i, fd in enumerate(frames):
        if not isinstance(fd, Mapping):
            raise ValueError(
                f"result['frames'][{i}] がフレーム dict ではありません: {type(fd).__name__}"
            )
        missing = [key for key in _REQUIRED_FRAME_KEYS if key not in fd]
        if missing:
            raise ValueError(
                f"result['frames'][{i}] に必須キーがありません: {missing}。"
                "欠けたキーは既定値 (rwp=inf / phase_names=()) で黙って埋まり、判定が"
                "入力の不備を反映しない誤った結論になります。"
            )


def _enum_from_value(enum_cls: type, value: object, key: str) -> object:
    """enum の **値** (小文字文字列) から enum メンバを引く。未知値は ValueError (→ error dict)。"""
    try:
        return enum_cls(str(value))
    except ValueError:
        allowed = ", ".join(sorted(str(m.value) for m in enum_cls))  # type: ignore[attr-defined]
        raise ValueError(f"unknown {key}: {value!r} (expected one of: {allowed})") from None


def _parse_two_theta_limits(
    two_theta_limits: Sequence[float] | None,
) -> tuple[float, float] | None:
    """``two_theta_limits`` を検証して ``(lo, hi)`` へ正規化する (None は制限なし)。

    呼び出し側は LLM が組んだ JSON なので、1 要素・3 要素・非数値の取り違えが起きやすい。素朴な
    ``limits[0], limits[1]`` は IndexError/TypeError を MCP 境界に貫かせるため、呼び出し側の try で
    error dict へ縮退できる ``ValueError`` に正規化する。``sequential_rietveld`` と
    ``operando_diag_tools.repair_frames`` の共有ヘルパ (レンジ解釈を一致させる)。

    :raises ValueError: 2 要素の数値ペアでない、または ``lo >= hi`` のとき
    """
    if two_theta_limits is None:
        return None
    try:
        values = list(two_theta_limits)
    except TypeError as exc:
        raise ValueError(
            f"two_theta_limits は [lo, hi] の 2 要素数値ペアです: {two_theta_limits!r}"
        ) from exc
    if len(values) != 2:
        raise ValueError(
            f"two_theta_limits は 2 要素 [lo, hi] である必要があります: "
            f"{two_theta_limits!r} (実際 {len(values)} 要素)"
        )
    try:
        lo, hi = float(values[0]), float(values[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"two_theta_limits の要素が数値ではありません: {two_theta_limits!r}"
        ) from exc
    if not (lo < hi):
        raise ValueError(f"two_theta_limits は lo < hi である必要があります: {two_theta_limits!r}")
    return (lo, hi)


def _instrument_path_resolver(
    spec: Mapping[str, object], frame_specs: Sequence[FrameSpec]
) -> str | Callable[[FrameSpec], str]:
    """instrument spec の ``path``/``paths`` を make_gsas_runner の instrument_path へ写す。

    ``paths`` は frames と 1:1 の列 (フレーム毎に instprm が異なる系列)。JSON からは callable を
    渡せないため、ここでフレーム→パスの解決関数を組み立てる。

    **``id()`` を鍵にしない** (間欠失敗の根治): 以前は ``by_id = {id(fs): path}`` を先に引く
    fast-path を持っていたが、CPython の ``id()`` は GC 後に再利用されるため、runner へ渡る
    フレームが元 ``frame_specs`` と別オブジェクト (③ が組み直した/新規生成した) のとき、
    別オブジェクトの再利用 id が stale entry に稀に当たり **誤ったパス**を返していた。

    フレームの**内容**で解決する:

    - data_path が系列で**一意**なら ``data_path → path`` で引く (新規生成フレームでも頑健)。
    - 一意でない (同一ファイルを複数フレームで使う) 系列は data_path では位置を区別できないため、
      ``FrameSpec`` 全体 (frozen dataclass = 値ハッシュ/値等価) を鍵にした位置解決へ落ちる。
    """
    paths = spec.get("paths")
    if paths is not None:
        path_list = [str(p) for p in paths]  # type: ignore[union-attr]
        if len(path_list) != len(frame_specs):
            raise ValueError(
                f"instrument paths length {len(path_list)} != frames length {len(frame_specs)}"
            )
        # 値等価キー (frozen dataclass): 同一 data_path で axis_value 等が異なるフレームを位置ごと
        # に区別できる。id() と違い GC 再利用の stale ヒットが原理的に起きない。
        by_frame = {fs: p for fs, p in zip(frame_specs, path_list)}
        data_paths = [fs.data_path for fs in frame_specs]
        # data_path が一意なときのみ data_path 索引を使う (重複時は最後のパスで上書きされ静かに
        # 誤るため無効化し、値キーの位置解決に委ねる)。
        by_data = (
            {dp: p for dp, p in zip(data_paths, path_list)}
            if len(set(data_paths)) == len(data_paths)
            else None
        )

        def resolve(frame: FrameSpec) -> str:
            p = by_frame.get(frame)  # 完全一致 (最も特定的)
            if p is not None:
                return p
            if by_data is not None:  # 一部フィールドが再構築で既定化しても data_path で救う
                p = by_data.get(frame.data_path)
                if p is not None:
                    return p
            raise ValueError(f"no instrument path for frame {frame.data_path!r}")

        return resolve
    path = spec.get("path")
    if path is None:
        raise ValueError("instrument spec requires 'path' (str) or 'paths' (list matching frames)")
    return str(path)


def _runner_from_instrument(
    spec: Mapping[str, object],
    frame_specs: Sequence[FrameSpec],
    two_theta_limits: tuple[float, float] | None,
    charge_constraint: "ChargeConstraintConfig | None" = None,
) -> Callable:
    """instrument spec (JSON) から make_gsas_runner で runner を組み立てる (Issue #93)。

    ``spec["recipe"]`` (Issue #114) は `make_gsas_runner(recipe=...)` へそのまま渡す**全段階の
    置換**であり (Issue #52; 未指定なら `make_gsas_runner` 内部で ``build_recipe`` が組む既定 7 段階
    レシピを使う)、`rietveld_tools.auto_rietveld` の ``stages`` (`AnalysisInput.extra_stages` =
    既定レシピへの**追加**段階) とは意味論が異なる — ① `make_gsas_runner` の既存契約をそのまま
    ② へ配線しているだけで、ここで新しい合成規則は作らない。JSON→RefinementStage の変換は
    `rietveld_tools` と共有する `_recipe_spec.stages_from_dicts` を使う (二重実装を避ける)。
    """
    from ..autorietveld.model import Geometry, Radiation
    from ..insitu.engine import make_gsas_runner
    from ._recipe_spec import stages_from_dicts

    afmc = spec.get("auto_freeze_minor_cells")
    # ⚠ #80 の本体は **float 閾値** (bool ではない)。JSON の true をそのまま float 化すると 1.0 =
    # 「分率 1.0 未満の相を凍結」= 多相では全相のセル凍結という静かな事故になるため明示的に拒否する。
    if isinstance(afmc, bool):
        raise ValueError(
            "auto_freeze_minor_cells is a phase-fraction threshold (float, e.g. 0.2), not a bool; "
            "pass null to disable (bool true would freeze every phase in a multiphase run)"
        )
    raw_recipe = spec.get("recipe")
    # recipe は**全置換**の意味論 (auto_rietveld の stages=追加 とは違う)。空 ([]) を許すと engine の
    # `is not None` 判定を通って空タプルのまま使われ、**精密化段階ゼロ = 未精密化 Rwp がそのまま
    # 返る**サイレント失敗になる。省略 (None) は既定 build_recipe へフォールバックするので安全だが、
    # [] は別物。③ が「上書き不要」のつもりで [] を送る事故を明示的に弾く (呼べるが黙って間違う予防)。
    if raw_recipe is not None and not raw_recipe:
        raise ValueError(
            "instrument.recipe が空です。空レシピは精密化段階ゼロ (未精密化の Rwp がそのまま返る) に"
            "なります。既定レシピを使うなら recipe キーを省略してください"
        )
    recipe = stages_from_dicts(raw_recipe) if raw_recipe is not None else None  # type: ignore[arg-type]
    return make_gsas_runner(
        instrument_path=_instrument_path_resolver(spec, frame_specs),
        radiation=_enum_from_value(Radiation, spec.get("radiation", "xray_lab"), "radiation"),
        geometry=_enum_from_value(Geometry, spec.get("geometry", "bragg_brentano"), "geometry"),
        two_theta_limits=two_theta_limits,
        max_cyc=int(spec.get("max_cyc", 12)),  # type: ignore[arg-type]
        background_coeffs=int(spec.get("background_coeffs", 6)),  # type: ignore[arg-type]
        recipe=recipe,
        auto_freeze_minor_cells=None if afmc is None else float(afmc),  # type: ignore[arg-type]
        charge_constraint=charge_constraint,
    )


def _apply_charge_constraint_spec(
    spec: Mapping[str, object], frame_specs: "list[FrameSpec]"
) -> "tuple[ChargeConstraintConfig, list[FrameSpec]]":
    """charge_constraint spec (JSON) → (系列設定, 目標付き FrameSpec 列) (FR-318 の ② 入口)。

    spec キー (§4.5 到達可能性 — 各キーの出所):

    - ``config``: `ChargeConstraintConfig.to_dict` 形 (mobile_sites/z_formula/formula_weights/
      mode/esd/anchor_ab_threshold/...)。**③ が系の結晶学から書く** (可動イオンサイトのラベル・
      多重度・Z・式量)
    - ``targets``: **``alkali_budget`` の出力 ``targets`` をそのまま渡す** (list of
      {frame, x_total, ...})。または {frame_index(str): x_total} の mapping。x_total が None の
      フレーム (echem 範囲外) には目標を付けない (拘束されない)
    - ``per_phase_content``: {相名: xᵢ} — 多相域の相ごとアルカリ量 (**単相アンカーの精密化結果**
      = anchored_sequential の anchors[].alkali.alkali_x_xrd から取る; REQ-318-004)

    frames リスト位置 = frame_index (alkali_budget と同じ列挙) で突き合わせる。
    """
    # 型検証を先に行う (最終レビュー F-final-1): config が Mapping でないと from_dict 内で
    # AttributeError になり、呼び出し側の catch (ValueError/TypeError/KeyError/IndexError) を
    # すり抜けて ② 境界を貫通する。具体的なメッセージの ValueError へ正規化する。
    if not isinstance(spec, Mapping):
        raise ValueError(
            f"charge_constraint は dict である必要があります: {type(spec).__name__}"
        )
    raw_cfg = spec.get("config") or {}
    if not isinstance(raw_cfg, Mapping):
        raise ValueError(
            f"charge_constraint.config は dict (ChargeConstraintConfig.to_dict 形) である"
            f"必要があります: {type(raw_cfg).__name__}"
        )
    raw_pp = spec.get("per_phase_content") or {}
    if not isinstance(raw_pp, Mapping):
        raise ValueError(
            f"charge_constraint.per_phase_content は {{相名: x}} の dict である必要があります: "
            f"{type(raw_pp).__name__}"
        )
    cfg = ChargeConstraintConfig.from_dict(raw_cfg)
    # 物理量の正値検証 (F2): z_formula=0 / formula_weights=0 は下流の除算で
    # ZeroDivisionError となり error-dict 契約を破る — ここ (try 内) で ValueError 化。
    for _nm, _z in cfg.z_formula.items():
        if _z <= 0:
            raise ValueError(f"charge_constraint.config.z_formula[{_nm!r}] は正であること: {_z}")
    for _nm, _fw in cfg.formula_weights.items():
        if _fw <= 0:
            raise ValueError(
                f"charge_constraint.config.formula_weights[{_nm!r}] は正であること: {_fw}"
            )
    if not cfg.enabled:
        raise ValueError(
            "charge_constraint.config.mobile_sites が空です — 相ごとの可動イオンサイト "
            '(例 {"phase_name": "mono", "site_labels": ["K"], "multiplicities": [4.0]}) が必要です'
        )
    per_phase = {str(k): float(v) for k, v in raw_pp.items()}  # type: ignore[arg-type]
    raw = spec.get("targets")
    if raw is None or len(raw) == 0:
        # alkali_budget は範囲外フレームも x_total=None のエントリとして必ず返すため、
        # 空の targets は正規の出力ではあり得ない (= 手組み spec の不備) — 黙って
        # 「拘束ゼロで有効」にしない (レビュー第2巡 F5)。
        raise ValueError(
            "charge_constraint.targets が空/欠落です — alkali_budget の出力 targets を"
            "そのまま渡してください (範囲外フレームも x_total=null で列挙されます)"
        )
    by_frame: dict[int, float] = {}
    if isinstance(raw, Mapping):
        items: "list[tuple[int, object]]" = [(int(k), v) for k, v in raw.items()]
    else:
        items = [(int(t["frame"]), t) for t in raw]  # type: ignore[index,call-overload]
    for idx, t in items:
        x = t.get("x_total") if isinstance(t, Mapping) else t
        if x is None:
            continue  # echem 範囲外 → 目標なし (拘束しない; 捏造禁止)
        by_frame[idx] = float(x)  # type: ignore[arg-type]

    # 【位置ずれの厳格検出】(レビュー MEDIUM): targets は frames リストの**位置**で突き合わせる。
    # サブセット解析 (実測 K-10: 247 中 63 フレーム stride 抽出) に全系列の alkali_budget 出力を
    # そのまま渡すと、位置 4 に「元フレーム 4」の目標が付く = 全フレームの x_echem が静かに誤る。
    # 範囲外 index はその確実な指紋なので**黙って捨てず**エラーにする (境界で error dict へ縮退)。
    if by_frame and (max(by_frame) >= len(frame_specs) or min(by_frame) < 0):
        raise ValueError(
            f"charge_constraint.targets の frame index (範囲 {min(by_frame)}..{max(by_frame)}) "
            f"が frames リスト ({len(frame_specs)} 件) の範囲外です。targets は frames の"
            "**位置**で対応させます — サブセット解析では targets を frames と同じ列挙に "
            "re-key するか、alkali_budget を frames と同じフレーム時刻 (frame_epoch_s) で"
            "回してください"
        )

    out: "list[FrameSpec]" = []
    for i, fs in enumerate(frame_specs):
        x = by_frame.get(i)
        if x is None:
            out.append(fs)
            continue
        tc = TargetComposition(total=x, per_phase=per_phase, mode=cfg.mode, esd=cfg.esd)
        out.append(dataclasses.replace(fs, target_composition=tc))
    return cfg, out


@degrade_oserror
def sequential_rietveld(
    frames: Sequence[Mapping[str, object]],
    initial_phases: Sequence[Mapping[str, object]],
    *,
    phase_id: Mapping[str, object] | None = None,
    warm_start: bool = True,
    warm_start_fractions: bool = False,
    two_theta_limits: Sequence[float] | None = None,
    max_frames: int | None = None,
    workdir: str = ".",
    instrument: Mapping[str, object] | None = None,
    charge_constraint: Mapping[str, object] | None = None,
    runner: Callable | None = None,
    phase_finder: Callable | None = None,
    reason: str = "",
) -> dict:
    """frames/initial_phases spec (JSON) を run_sequential_rietveld で実行し構造化結果を返す。

    :param frames: FrameSpec.to_dict の列
    :param initial_phases: PhaseSpec.to_dict の列 (フレーム 0 の既知相)
    :param phase_id: 新相自動同定の設定 (None で無効)。``PhaseIdConfig`` の**全フィールド**を
        JSON キーとして受ける (未知キーは typo として error dict — 黙って無視しない)。
        主要キー:

        - ``elements``: 相同定に許す元素系 (**文字列のリスト**。裸の ``"CaTeO"`` は拒否 —
          1 文字ずつに分解され別の元素系になるため)。**空なら同定を行わない**
        - ``wavelength``: プリアライン/候補再スコアの線源波長 [Å]。**既定は Cu Kα1 1.5406** —
          **放射光/中性子系列では必ず実波長を指定すること** (例 0.800113)。誤ると d↔2θ 変換が
          丸ごとずれ、プリアライン後のセルも候補順位も系統的に誤る (例外は出ず「同定が効かない」
          ようにしか見えない)
        - ``refine_new_phase_cell``: 新相の異方セルプリアラインの on/off (既定 True)。
          少数相フレームでは prealign が支配相のピークにロックして誤セルを返すことがある —
          そのときの唯一の escape hatch (Issue #20)
        - ``rerank_top_k``: 上位 K 候補を異方格子整合で再スコア (既定 5, 0 で無効)
        - ``min_rwp_gain``: 新相受理に要する**相対** Rwp 改善 (既定 0.01 = 1%)
        - ``require_validity`` / ``require_full_element_system``: 受理の物理・化学ガード
          (既定 False / True)
        - ``snr_trigger``: 残差 S/N の探索発火閾値 (既定 20.0, 0 で無効)。**データセット固有**
        - ``max_new_phases``: 系列全体の追加相数上限 (既定 0 = 無制限)
        - ``bic_acceptance`` / ``bic_base_params`` / ``bic_per_phase_params``: 受理を bic
          モデル選択で行うか (既定 False — 粉末では bic は相対 Rwp より寛容で過剰適合ガードに
          ならない。実効は M10 の区間比較側)
        - ``warm_start_known_phases``: 現行相を残差から先に減算してから新相を探すか (既定 True)
        - ``top_k`` / ``hull_cutoff_ev`` / ``rwp_eps`` / ``trigger_rwp_ratio`` / ``subtract_bg``:
          候補数・MP 安定性フィルタ (null で無効)・最小 Rwp 改善・発火 Rwp 比・背景減算

        ⚠ ``frac_min`` (既定 0.02) は新相採用に要する**最小 Scale** — `phase_fractions` (HAP Scale の
        Σ=1 正規化値) と比較する。**wt% (`phase_weight_fractions`) ではない** (下の
        ``auto_freeze_minor_cells`` と同じ basis 注意)

        【§4.5 引数の出所】: ``elements`` は既知相の構成元素 + ③ が想定する元素 (③ が化学から
        書く。CIF/`identify_phases` の出力を参照してもよい)、``wavelength`` は**測定条件**
        (instprm/ビームライン諸元。``instrument.path`` の instprm と同じ線源のものを書く)。
        残りは**すべて ③ が skill から設定する policy 定数**であり、他 ② ツールの出力から
        導くものではない (受理の厳しさ・探索の広さをどう置くかは判断層の権限)
    :param warm_start_fractions: 直前フレームの精密化相分率も次フレームの初期値に引き継ぐか
        (Issue #82; 分率が seed に張り付くフレームの是正。``warm_start`` 有効時のみ効く)
    :param instrument: **JSON クライアント (③) の実運用経路** (Issue #93)。指定かつ ``runner`` 未指定
        なら、この spec からサーバ側で ``make_gsas_runner`` を組み立てる。指定なし (None) は従来通り
        engine 既定の ``_default_gsas_runner`` (実験室 X 線 Bragg-Brentano・背景 6 項・装置は data_path
        隣接の ``.instprm`` 規約) — 放射光や背景項数の変更はこの spec でしか届かない。キー:

        - ``path``: instprm パス (str, 必須。``paths`` と排他)
        - ``paths``: frames と 1:1 の instprm パス列 (フレーム毎に装置が異なる系列)
        - ``radiation``: ``Radiation`` の **値** ("xray_lab"/"xray_synchrotron"/"neutron_cw"/
          "neutron_tof"、既定 "xray_lab")
        - ``geometry``: ``Geometry`` の値 ("bragg_brentano"/"debye_scherrer"、既定 "bragg_brentano")
        - ``background_coeffs``: Chebyshev 背景項数 (int, 既定 6。実験室 X 線/放射光は 18-24 推奨)
        - ``max_cyc``: 各段階の最大精密化サイクル (int, 既定 12)
        - ``auto_freeze_minor_cells``: 分率連動の自動セル凍結**閾値** (float|None, 既定 None=無効。
          Issue #80: 例 0.2 なら相分率 0.2 未満の相のセルを解放しない)。⚠ **basis は
          `phase_fractions` (= HAP Scale の Σ=1 正規化値) で `phase_weight_fractions` (wt%) では
          ない** — 実測 ``Scale {cubic .75, tetra .25}`` = ``wt% {cubic .865, tetra .135}`` なので
          0.2 は **Scale では tetra を解放し wt% では凍結する**。出版値は wt% なので wt% の直感で
          数字を決めると静かに外れる (③ 向けの警告は skills/insitu・skills/operando-diagnose・
          AGENT_PLAYBOOK の「分率の閾値は Scale 基準」節)
        - ``recipe``: **段階解放レシピの全置換** (Issue #114: ① `make_gsas_runner(recipe=...)`
          [Issue #52] が既に持つ引数を JSON から届くようにしたもの)。``[{"label": str,
          "flags": {GSAS 語彙}, "note": str (省略可)}, ...]`` の列 (語彙は
          ``autorietveld.recipe`` docstring 参照)。指定すると既定の 7 段階 `build_recipe` を
          **使わず**このレシピをそのまま使う (`auto_rietveld` の ``stages`` = 既定への**追加**とは
          意味論が違う点に注意)。省略 (None, 既定) なら従来通り `build_recipe` が組む。不正な
          段階 spec は error dict へ縮退する

        ``two_theta_limits`` は本引数の runner にも転送される (フレーム側指定が優先)。
    :param charge_constraint: **FR-318 電気化学制約の JSON spec**。キー: ``config``
        (`ChargeConstraintConfig.to_dict` 形 — mobile_sites/z_formula/formula_weights/mode/esd
        等)、``targets`` (**``alkali_budget`` の出力 targets をそのまま**)、``per_phase_content``
        ({相名: xᵢ}; 多相域用 — 単相アンカーの精密化結果から)。既定モード diagnose は拘束せず
        x_XRD vs x_echem 乖離を per-frame 出力 (alkali_* キー)。lock_fractions は明示 opt-in
        (2 相では相分率が完全決定される — 採用は第3層判断)。None で従来動作
    :param runner: **注入/テスト用**の Python callable ((frame, phases, initial_cells)→
        AutoRietveldResult)。JSON 境界越しには渡せない。明示指定時は ``instrument`` より優先する
        (後方互換)。None かつ ``instrument`` も None なら engine 既定 GSAS runner
    :param phase_finder: 新相探索器 (注入可能、既定 MP 駆動)
    :returns: 系列構造化結果。instrument spec 不正は ``{"error", "error_type"}``
    """
    from ..insitu.engine import run_sequential_rietveld

    # 【レンジ検証を縮退契約に載せる】: 旧実装は `two_theta_limits[0]` を直接引いており、1 要素等の
    #   取り違えで IndexError が MCP 境界を貫いていた (error dict へ縮退する契約に反する)。
    #   FrameSpec/PhaseSpec の解析も try 内 (最終レビュー F4: FrameSpec.from_dict は
    #   TargetComposition の mode 検証で ValueError を出しうる — anchored_sequential と対称に)。
    # 【phase_id も try の中で組む】: 旧実装は `PhaseIdConfig(...)` を try の**外**で組んでおり、
    #   `float(phase_id.get("frac_min"))` 等が ③ のゴミ入力で送出する ValueError が MCP 境界を
    #   貫通していた (② は例外を送出しない契約 — ③ は LLM なので回復不能なハード失敗になる)。
    #   `anchored_sequential` の `AnchorConfig.from_dict` は最初から try 内にあり非対称だった。
    try:
        frame_specs = [FrameSpec.from_dict(f) for f in frames]
        phase_specs = [PhaseSpec.from_dict(p) for p in initial_phases]
        # 【フィールド駆動パーサ】: 手書きホワイトリスト (旧 7 キー) をやめ、`PhaseIdConfig` の
        #   全フィールドを ③ から到達可能にする (Issue #97 型のカバレッジ欠陥)。とりわけ
        #   `wavelength` は既定 Cu Kα1 なので、届かないと放射光/中性子系列が黙って誤った波長で
        #   異方セルプリアライン/候補再スコアを行う。`anchor_config` と**同じ共有パーサ**。
        pid = PhaseIdConfig.from_dict(phase_id) if phase_id is not None else None
        cc_cfg: ChargeConstraintConfig | None = None
        if charge_constraint is not None:
            cc_cfg, frame_specs = _apply_charge_constraint_spec(charge_constraint, frame_specs)
        limits = _parse_two_theta_limits(two_theta_limits)
        if runner is None and instrument is not None:
            runner = _runner_from_instrument(instrument, frame_specs, limits, cc_cfg)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        # AttributeError も捕捉 (F-final-1 安全網): 深い入れ子のゴミ (例 z_formula: "x") は
        # `.items()`/`.get()` で AttributeError になる — ② は例外を送出しない。
        return {"error": str(exc), "error_type": type(exc).__name__}
    config = SequentialConfig(
        warm_start=warm_start,
        warm_start_fractions=warm_start_fractions,
        two_theta_limits=limits,
        max_frames=max_frames,
        phase_id=pid,
        charge_constraint=cc_cfg,
    )
    result = run_sequential_rietveld(
        frame_specs, phase_specs, config=config, runner=runner,
        phase_finder=phase_finder, workdir=workdir,
    )
    out = seq_result_to_dict(result)
    out["reason"] = reason
    return out


@degrade_oserror
def identify_and_add_phase(
    two_theta: Sequence[float],
    intensity: Sequence[float],
    elements: Sequence[str],
    workdir: str,
    *,
    exclude_formulas: Sequence[str] = (),
    top_k: int = 1,
    hull_cutoff_ev: float | None = 0.1,
    subtract_bg: bool = True,
    provider: object | None = None,
    materializer: object | None = None,
    reason: str = "",
) -> dict:
    """残差/生パターン + elements から新相を同定し CIF 物質化して PhaseSpec 候補を返す (相追加提示)。

    採否・再精密化は行わない (提案≠適用): ③ が返された PhaseSpec を initial_phases に足して
    sequential_rietveld/refine を再実行する。provider/materializer 未指定なら MP を遅延生成。
    """
    import numpy as np

    from ..insitu.phaseid import MPMaterializer, identify_new_phases

    if provider is None or materializer is None:
        # 【DOA バグ修正】: 旧実装は MPReferenceProvider()/MPMaterializer() を client 無しで
        # 構築しており TypeError で即死 = 既定経路が呼び手不在だった (§4.5 到達可能性)。
        # insitu.engine._ensure と同じ構築 (キーは環境変数 MATERIALS_PROJECT_API) に揃える。
        from ..mp.client import MPRestClient

        client = MPRestClient()
        if provider is None:
            from ..mp.provider import MPReferenceProvider

            provider = MPReferenceProvider(client)
        if materializer is None:
            materializer = MPMaterializer(client)

    found = identify_new_phases(
        np.asarray(two_theta, dtype=float),
        np.asarray(intensity, dtype=float),
        elements=list(elements),
        provider=provider,  # type: ignore[arg-type]
        materializer=materializer,  # type: ignore[arg-type]
        workdir=workdir,
        exclude_formulas=list(exclude_formulas),
        top_k=top_k,
        hull_cutoff_ev=hull_cutoff_ev,
        subtract_bg=subtract_bg,
    )
    return {
        "candidates": [
            {
                "phase_spec": ip.phase_spec.to_dict(),
                "phase_id": ip.phase_id,
                "formula": ip.formula,
                "score": finite_or_none(ip.score),
                "strain": finite_or_none(ip.strain),
                "source": ip.source,
            }
            for ip in found
        ],
        "n_candidates": len(found),
        "reason": reason,
    }


def parametric_fit(
    result: Mapping[str, object],
    phase: str,
    *,
    component: str = "a",
    degree: int = 1,
    basis: str = "weight",
    reason: str = "",
) -> dict:
    """系列結果 (JSON) の相 phase について 格子 vs 軸の熱膨張多項式 + 相分率転移を返す。

    :param result: ``sequential_rietveld`` が返す系列結果 (JSON dict)。**空/不正 (``frames`` 無し・
        空・必須キー欠落・フレームが dict でない) は判断せず error dict** — 0 フレームの
        「転移なし」は本物の「転移なし」と区別が付かない (``_validate_seq_result``)
    :param basis: 転移推定に使う相分率の基準。**既定 ``"weight"`` (重量分率 = 出版値)**。
        ``"scale"`` は HAP Scale 由来で**診断・相対比較専用** (出版不可)。
    :returns: ``fraction_basis`` に**どちらで出したかを明示**した結果。重量分率が系列に無い/
        系列結果が空・不正/未知 basis は ``{"error", "error_type"}`` dict (Scale へも
        「転移なし」へも縮退しない)。この場合 ``transition``/``fraction_basis`` キーは返らない
        (③ の ``assert pf["fraction_basis"] == "weight"`` が**素通りしない**)

    ⚠ **転移 onset/midpoint は basis で答えが変わる**: `sequential.thermal.estimate_transition` が
    返すのは「曲線が**絶対レベル** 0.50 / 0.10 を横切る軸値」であり、y 軸が Scale か wt% かで
    交差位置が動く。実測 K₂Mn[Fe(CN)₆] tetra 充電域では、同じ精密化から Scale は
    「midpoint 9.515 h」を、wt% は「**転移なし**」を出した (Scale 0→0.656 は 0.50 を横切るが
    wt% は 0→0.472 で届かない。Scale=0.50 のフレームは実際には 34.0 wt%)。

    **既定を "weight" にした理由** (① `parametric.transition_from_fractions` の既定 "scale" と
    異なる): ② は JSON しか送れない LLM (③) が呼ぶ表面であり、**既定がそのまま ③ にとっての
    実質的な振る舞い**になる (architecture.md §4.5)。既定を Scale にすると ③ は「出版できる
    転移温度」だと信じて Scale 由来の数字を受け取る — それが本 HIGH の実害そのものである。
    ① は Python の呼び出し側が call site で意図を書ける層なので後方互換を優先している。
    """
    from ..insitu.parametric import analyze_phase

    # 【縮退契約】: ② は例外を送出しない (③ は LLM なので例外は回復不能なハード失敗)。
    #   重量分率の欠如 (`FractionBasisUnavailableError`, ValueError の派生) と未知 basis は
    #   error dict にして**復旧方法を示す** — ここで Scale に落ちたり「転移なし」を返したり
    #   すると、③ は静かに違う数字を出版する (CLAUDE.md ② 不変条件)。`error_type` に
    #   例外クラス名が入るので ③ は「重量分率が無い」と「入力が壊れている」を区別できる。
    # 【入力検証を先に (レビュー第4巡 MEDIUM-HIGH)】: `_result_from_dict` は寛容で、`frames` の
    #   無い dict を空の系列へ黙って復元する。0 フレームなら重量分率の**欠測も 0 件**なので
    #   `FractionBasisUnavailableError` すら出ず、`{}` に対して `fraction_basis="weight"` +
    #   `transition=None` = 「重量分率基準で見て転移なし」という**自信のある嘘**を返していた。
    #   ③ に指示してある検算 (`assert pf["fraction_basis"] == "weight"`) も素通りする。
    #   `model.FractionBasisUnavailableError` が「『転移なし』へ縮退するのも禁止」と定めた当の
    #   失敗様態そのものなので、判断の前に形を検証する (`check_phase_set` と同じ縮退契約)。
    # 【AttributeError も捕らえる】: `_result_from_dict` は `d.get(...)` / `fd.get(...)` を呼ぶため、
    #   result が str/list、frames が dict、フレーム要素が str/None のとき AttributeError が
    #   MCP 境界を貫いていた (② は例外を送出しない契約に反する)。`check_phase_set` は同じ復元器を
    #   呼びながら AttributeError を捕らえており、兄弟ツール間で縮退契約が食い違っていた。
    try:
        _validate_seq_result(result)
        seq = _result_from_dict(result)
        pa = analyze_phase(seq, phase, component=component, degree=degree, basis=basis)  # type: ignore[arg-type]
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}
    tr = pa.transition
    return {
        "phase": phase,
        "component": component,
        # 【basis の明示】: Scale 由来の数字が出版値と取り違えられないよう、**常に**どちらで
        #   出したかを返す (③ が見落としても既定が weight なので安全側に倒れる) 🔵 §4.5
        "fraction_basis": pa.fraction_basis,
        "baseline": {
            "parameter": pa.baseline.parameter,
            "coefficients": [finite_or_none(c) for c in pa.baseline.coefficients],
            "outlier_frames": list(pa.baseline.outlier_frames),
        },
        "transition": None
        if tr is None
        else {
            "phase_ref": tr.phase_ref,
            "onset": finite_or_none(tr.onset) if tr.onset is not None else None,
            "midpoint": finite_or_none(tr.midpoint) if tr.midpoint is not None else None,
            "sigma": finite_or_none(tr.sigma) if tr.sigma is not None else None,
            "direction": tr.direction,
        },
        "reason": reason,
    }


@degrade_oserror
def write_sequential_csv(result: Mapping[str, object], path: str, *, reason: str = "") -> dict:
    """``sequential_rietveld``/``anchored_sequential`` の結果 dict から FR-504 トラジェクトリ CSV を
    書き出す (Issue #116 調査の帰結: M2 ``Trajectory.to_csv`` は実データ経路である M9/M10 の結果
    dict から作れず ② に到達不能だった。**M2 の Trajectory を経由せず**、M9 の結果 dict を直接
    CSV へ写す方が実データに即した誠実な実装になるため、こちらを新設する)。

    :param result: ``sequential_rietveld`` (または ``anchored_sequential``, 同一スキーマ) の
        戻り値 dict そのもの (§4.5 到達可能性: 他 ② ツールの出力から来る)。空/不正 (``frames`` 無し・
        空・必須キー欠落) は判断せず error dict (``_validate_seq_result`` と同じ縮退契約 —
        0 フレームを「空の CSV でよい」と黙って書き出さない)
    :param path: 出力 CSV パス

    列は M9 ``SequentialRietveldResult`` が実際に持つ値のみで構成する: フレーム共通列
    (frame_index/data_path/axis_value/rwp/gof/changepoint/changepoint_reasons/refine_failed) +
    相ごと 9 列 (a/b/c/a_esd/b_esd/c_esd/scale/wt_frac/wt_frac_esd)。M2 Trajectory の
    ``sigma_source``/lifecycle 3 列 (birth_frame/death_frame/confidence) は**含めない** — M9 の
    フレーム行にはこれらに対応する列が無い (birth は ``appearances`` に別スキーマで出るが
    death/confidence は持たず、フレーム単位の行に相ライフサイクルは自然にマップしない)。無い値を
    空欄で埋めると「持っているように見える」偽装になる (CLAUDE.md ②不変条件: 空/不正入力を
    「正常」と答えない、と同じ規律の CSV 版)。``scale`` は **Scale であって重量分率ではない**
    (``wt_frac`` を定量値として使うこと — insitu skill 手順 8 と同じ注意)。

    :returns: ``{"path": str, "n_frames": int, "n_phases": int, "reason": str}``。
        入力不正/書き込み失敗は ``{"error", "error_type"}``
    """
    try:
        _validate_seq_result(result)
    except (ValueError, TypeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    phase_refs = _seq_csv_phase_refs(result)
    header = _seq_csv_header(phase_refs)
    frames = result["frames"]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for fd in frames:  # type: ignore[union-attr]
            writer.writerow(_seq_csv_row(fd, phase_refs))  # type: ignore[arg-type]

    return {
        "path": str(path),
        "n_frames": len(frames),  # type: ignore[arg-type]
        "n_phases": len(phase_refs),
        "reason": reason,
    }


# 【M9 ツールレジストリ】: MCP_TOOLS へマージする 4 ツール (architecture.md §6 の 3 + FR-504 CSV)。
INSITU_TOOLS: Mapping[str, object] = {
    "sequential_rietveld": sequential_rietveld,
    "identify_and_add_phase": identify_and_add_phase,
    "parametric_fit": parametric_fit,
    "write_sequential_csv": write_sequential_csv,
}
