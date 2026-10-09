"""段の間の精密化値の持ち越し (#218) — 純関数。

TOPAS は精密化後、**INP そのものに精密化値を埋め込んだもの**を ``.out`` に書き戻す
(``a PbSO4_a 8.48`` → ``a PbSO4_a 8.482776`_0.000101``)。段階解放の次段は、この値から
始めなければならない。TOPAS の通常運用 (``.out`` を ``.inp`` にして続行) と同じ形である。

以前の engine は段ごとに `TopasDocument.render` から INP を作り直し、``.out`` を指標の
読み取りにしか使っていなかった。そのため「段階解放」が実際には**累積した解放フラグで、
毎段 CIF の出発値から解き直す**動作になっていた — 後段ほど多くのパラメータを遠い出発点から
同時に解くことになり、受理判定も別の軌跡どうしを比べ、revert も「直前の受理状態」に
戻っていなかった。GSAS 経路は gpx が値を持ち越すので、**同じレシピの意味がバックエンドで
違っていた**。

持ち越す経路は値の書かれ方で 3 つ:

==========================  =========================================  ==========================
値                          ``.out`` での形                             持ち越し先
==========================  =========================================  ==========================
名前付きパラメータ          ``name 8.48`_0.0001`` / ``name,-0.002`_…``  `TopasDocument.carried_values`
背景係数 (名前を付けられない) ``bkg @ 111.4`_1.0 13.5`_1.6 …``         `TopasHistogram.background_values`
球面調和の選択配向          係数を展開した ``… load sh_Cij_prm { … }``  str ブロックの追加行を置換
==========================  =========================================  ==========================

無名の ``@`` は持ち越せないので、`topas.flags` / `TopasDocument.render` は解放しうる値に
名前を付ける (``CS_L``/``Strain_L``/``Simple_Axial_Model`` と、結果出力時の固定サイト値)。
"""

from __future__ import annotations

from .flags import po_line_key
from .inp import TopasDocument, TopasHistogram
from .parse import (
    background_values_from_out,
    named_refined_values_from_out,
    spherical_harmonics_blocks_from_out,
)

__all__ = ["carry_refined_values"]


def carry_refined_values(
    doc: TopasDocument, out_text: str
) -> "tuple[TopasDocument, tuple[str, ...]]":
    """受理した段の ``.out`` から精密化値を読み戻した文書を返す。

    解放フラグには触らない (値とフラグの分担は `TopasDocument.carried_values` を参照)。

    :returns: ``(文書, 警告)``。警告は**持ち越せなかったもの**の説明で、engine が段の note と
        ledger に残す (黙って出発値へ戻さない)。
    """
    warnings: list[str] = []

    carried = {**doc.carried_values, **named_refined_values_from_out(out_text)}

    histograms = list(doc.histograms)
    with_background = [i for i, hist in enumerate(histograms) if hist.background is not None]
    rows = background_values_from_out(out_text)
    if len(rows) != len(with_background):
        # 【位置で写すので数が合わなければ写さない】: どの bkg 行がどの xdd か決められない。
        #   別のヒストグラムの係数を入れるより、前段の値のまま進める方が安全。
        warnings.append(
            f"背景係数を持ち越せません: .out の bkg 行 {len(rows)} 本に対し"
            f"背景を持つヒストグラムが {len(with_background)} 本"
        )
    else:
        for index, row in zip(with_background, rows):
            if row is None:
                warnings.append(f"ヒストグラム {index} の背景係数を読めず持ち越せません")
                continue
            histograms[index] = histograms[index].with_updates(background_values=row)

    blocks = spherical_harmonics_blocks_from_out(out_text)
    if blocks:
        histograms = [_with_expanded_harmonics(hist, blocks) for hist in histograms]

    return (
        doc.with_updates(histograms=tuple(histograms), carried_values=carried),
        tuple(warnings),
    )


def _with_expanded_harmonics(hist: TopasHistogram, blocks: "dict[str, str]") -> TopasHistogram:
    """str ブロックの ``PO_Spherical_Harmonics(name, …)`` 行を係数展開形へ置き換える。"""
    terms = dict(hist.phase_terms)
    for phase_name, term in terms.items():
        extras = []
        for line in term.extras:
            key = po_line_key(line)
            extras.append(blocks.get(key[0], line) if key else line)
        terms[phase_name] = term.with_updates(extras=tuple(extras))
    return hist.with_updates(phase_terms=terms)
