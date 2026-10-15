"""サイト対称による座標の自由軸判定 (M12) — TOPAS 固有部分。

GSAS 経路は ``GSASIIspc.GetCSxinel`` で「その原子のどの座標成分が独立に動けるか」を得ている。
TOPAS には同等の scriptable API が無く、**特殊位置の座標をそのまま解放すると対称性が壊れる**
(実 PbSO4 で座標段の Rwp が 11.1 → 12.1 に悪化し revert された)。

ここでは CIF の対称操作から**サイト対称群**を作り、許される変位方向を線形代数で求める:

1. サイト対称群 ``G = {(R, t) : R·p + t ≡ p (mod 1)}``
2. 許される変位は ``G`` の全 ``R`` で不変なベクトル。射影子 ``P = (1/|G|)·Σ R`` の像が
   その部分空間になる。
3. 軸 ``e_i`` を**独立に**解放してよいのは ``P`` が第 i 行・列で対角 (``P[i,i]≈1`` かつ
   非対角が ``0``) のときだけ。三方晶の ``(x, -x, z)`` のように軸が**結束**している場合は
   1 変数として拘束式を書く必要があるので、v1 では**解放しない** (誤って独立に動かすより安全)。

例: Pnma の Pb (0.188, 1/4, 0.167) は ``x, -y+1/2, z`` で不変 → ``P = diag(1, 0, 1)`` →
x と z のみ解放、y は 1/4 に固定。

射影の本体 (上の 1-3 と特殊位置への吸着) は GSAS 経路も使うので `tsumugin.site_symmetry` へ
移した。ここに残るのは TOPAS 固有の部分 (多重度の許容差・``Sg/`` からの対称操作の補完)。
"""

from __future__ import annotations

import re
from pathlib import Path

# 射影の本体はバックエンド非依存 (GSAS 経路も使う)。ここは同じ実体を再エクスポートする。
from ..site_symmetry import (
    fixed_coord_axes,
    free_coord_axes,
    parse_symop,
    site_coord_axes,
    site_symmetry_projector,
    site_symmetry_residual,
    snap_to_special_position,
)

__all__ = [
    "SITE_MERGE_TOLERANCE",
    "ensure_symops",
    "fixed_coord_axes",
    "free_coord_axes",
    "parse_symop",
    "read_sg_symops",
    "site_coord_axes",
    "site_symmetry_projector",
    "site_symmetry_residual",
    "snap_to_special_position",
]

SITE_MERGE_TOLERANCE: float = 1e-8
"""TOPAS がサイトの多重度を判定する分率座標の許容差 (実測)。

``x`` を 1/3 から 3.3e-8 ずらすと P6₃/m の 4f が一般位置 (多重度 12) に化け、
3.3e-9 なら 4f のままだった。CIF の座標欄は 5-8 桁が標準なので **1/3 は必ずこの網から
漏れる** — :func:`snap_to_special_position` がそれを埋める。
"""

# ---------------------------------------------------------------- Sg/*.sg からの補完

_XYZS_BLOCK = re.compile(r"xyzs\s*\{(.*?)\}", re.DOTALL)


def read_sg_symops(space_group: str, home: "Path | None" = None) -> "tuple[str, ...]":
    """TOPAS が生成した ``Sg/<sg>.sg`` から対称操作を読む (無ければ空タプル)。

    ``Sg/`` は **sgcom6.exe がオンデマンドで生成するキャッシュ**ディレクトリで、
    ``xyzs { x, y, z / -x, y+1/2, -z / … }`` の形で一般位置を列挙している。**CIF が対称操作を
    持たない場合の権威的な供給元**である (空間群記号から自前で展開するより確実)。
    """
    from .availability import topas_home

    base = home or topas_home()
    if base is None:
        return ()
    # ファイル名は H-M 記号を小文字にして空白を除いたもの (実測: Pnma → pnma.sg)。
    # **``/`` は ``o`` (over) にエンコードされる** (実測: P63/m → p63om.sg) —
    # そのままだとファイル名にならないため。これを知らないと ``/`` を含む空間群
    # (単斜晶の P21/c・C2/c、六方晶の P63/m …) で対称操作が引けず、座標段が黙って no-op になる。
    name = re.sub(r"\s+", "", space_group).lower().replace("/", "o")
    path = Path(base) / "Sg" / f"{name}.sg"
    if not path.is_file():
        return ()
    match = _XYZS_BLOCK.search(path.read_text(encoding="utf-8", errors="replace"))
    if match is None:
        return ()
    ops = [line.strip() for line in match.group(1).splitlines()]
    # 【コメント行を操作と読まない】: 体心/面心群の ``.sg`` は中心並進の前に
    #   ``' +(1/2, 1/2, 1/2) ---`` を挟む (実測)。カンマが 2 つあるので素朴な行フィルタを
    #   通ってしまい、回転行列が**零行列**の偽の操作になる。零行列はサイト対称群の射影子を
    #   薄めるので、``(1/2,1/2,1/2)`` にあるサイトの自由軸が消え**座標が一度も解放されない
    #   まま完走する**。TOPAS の INP コメントは ``'`` 始まり。
    return tuple(
        op for op in ops if op and not op.startswith("'") and op.count(",") == 2
    )


def ensure_symops(
    space_group: str, symops: "tuple[str, ...]", *, generate: bool = True
) -> "tuple[str, ...]":
    """対称操作を確保する。CIF 由来があればそれを、無ければ TOPAS の ``Sg/`` から補完する。

    ``Sg/<sg>.sg`` がまだ生成されていない場合、``generate=True`` なら**空間群だけを宣言した
    最小 INP を 1 回流して** TOPAS に生成させる (sgcom6 は tc.exe 経由でしか呼べない)。

    **補完できなければ :class:`~tsumugin.errors.TopasSymmetryError` を送出する** (#219)。
    以前は失敗を握りつぶして空タプルを返し、呼び出し側は「座標を解放しない」を黙って
    選んでいた — 結果にも ledger にもその選択が残らず、座標段が無言 no-op になるうえ
    特殊位置の吸着 (#172) も効かなかった。しかも ``Sg/`` は実精密化のたびに TOPAS が
    育てるキャッシュなので、**同じ CIF の結果が実行環境の履歴で変わっていた** (NFR-102)。

    ``generate=False`` は tc.exe を起動したくない呼び出し側の逃げ道で、キャッシュに
    無ければ空タプルが返る (空の扱いは呼び出し側の責任)。

    :raises TopasSymmetryError: CIF に対称操作が無く、生成も読み取りもできなかったとき
    """
    if symops:
        return symops
    found = read_sg_symops(space_group)
    if found or not generate:
        return found
    from ..errors import TopasSymmetryError

    # 【成否は「Sg/ から読めるか」で決める】: 探査の目的はファイルであって精密化ではない。
    #   TOPAS は空間群を展開して ``.sg`` を書いた**後で**別の理由 (``No hkls`` 等) で異常終了
    #   しうる (実測: 探査が狭かった頃の Fd-3m / I41/amd / R-3 / P42/mnm)。終了状態で
    #   判定すると、対称操作が手に入っているのに止めてしまう。探査の失敗は原因として運ぶ。
    probe_error: "Exception | None" = None
    try:
        _generate_sg_file(space_group)
    except Exception as exc:  # noqa: BLE001 — 下で読めなければ原因として上げる
        probe_error = exc
    generated = read_sg_symops(space_group)
    if generated:
        return generated
    if probe_error is not None:
        raise TopasSymmetryError(
            f"CIF に対称操作が無く、空間群 {space_group} の対称操作を TOPAS の Sg/ から"
            f"生成できませんでした ({type(probe_error).__name__}: {probe_error})。CIF に"
            f"対称操作ループを足すか、空間群記号を確かめてください。"
        ) from probe_error
    # 【生成は成功・読めない】: ファイル名の符号化 (``/`` → ``o``) がずれるとここに来る
    #   (`read_sg_symops`)。空で続けると上と同じ無言 no-op になる。
    raise TopasSymmetryError(
        f"空間群 {space_group} の Sg ファイル生成を試みましたが、Sg/ から対称操作を"
        f"読めませんでした (ファイル名の対応か TOPAS ホームの書き込み権を確かめてください)。"
    )


def _generate_sg_file(space_group: str) -> None:
    """空間群だけを宣言した最小 INP を流し、TOPAS に ``Sg/<sg>.sg`` を生成させる。

    **``lam`` を必ず置く** (#219): 波長の無い ``xdd`` は CW のパターンとして解釈できず、
    tc.exe は空間群を展開する前に ``Cannot locate lam from riet_app_3 in data structures`` で
    必ず異常終了する (実測)。値に意味は無い — 生成されるのは空間群の一般位置だけである。

    **反射が範囲に入る広さにする**: 2θ 10–20°・a=5 Å では d が 4.4–8.8 Å しか無く、消滅則の
    多い群 (Fd-3m の最初の反射 111 は d=2.9 Å) で ``No hkls`` により異常終了した (実測。
    ``.sg`` はその前に書かれる)。2θ 5–150°・a=10 Å なら d≥0.8 Å まで入り、どの群でも反射が立つ。
    """
    import tempfile

    from .driver import run_tc

    with tempfile.TemporaryDirectory(prefix="tsumugin-topas-sg-") as tmp:
        work = Path(tmp)
        (work / "sgprobe.xye").write_text(
            "\n".join(f"{5.0 + 0.05 * i:.4f} 1.0 1.0" for i in range(2901)) + "\n",
            encoding="utf-8",
        )
        inp = (
            "r_wp 0\n"
            "iters 0\n"
            'xdd "sgprobe.xye"\n'
            "   bkg 0\n"
            "   lam ymin_on_ymax 0.001 la 1 lo 1.5406 lh 0.1\n"
            "   str\n"
            f"      space_group {space_group}\n"
            "      a 10 b 10 c 10\n"
            "      site A x 0 y 0 z 0 occ C 1 beq 1\n"
            "      scale 0.0001\n"
        )
        run_tc(inp, workdir=work, basename="sgprobe", timeout=120.0)
