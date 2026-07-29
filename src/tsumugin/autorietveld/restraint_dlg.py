"""restraint を headless で χ² に入れるための ``dlg`` スタブ (REQ-SAR-203)。

**問題** (requirements.md F5, ソース実測): `GSASIIstrMath.errRefine` は restraint penalty を

    if len(pVals) and dlg:            # dlg = wx プログレスダイアログ
        Nobs += len(pVals)
        M = np.concatenate((M, np.sqrt(pWt)*pVals))   # penalty を残差へ足すのはここだけ
    Histograms['RestraintSum'] = pSum # ← 報告はゲートの外 (効いているように見える)

でゲートする。一方 `dervRefine` (4807-4810) と `HessRefine` (4935-4939) は**ゲートされていない**。
つまり headless (``dlg=None``) では **目的関数は拘束を見ないのに勾配/Hessian だけが引っ張られる**
不整合な最適化になる。Issue #112 で実測した「小飽和摂動・target-invariant」の正体である。

**回避口**: ``G2strMain.Refine(GPXfile, dlg=…)`` は公開パラメータで、`G2Project.refine()` が
渡していないだけ。wx に依存しない duck-typed オブジェクトを渡せば penalty が χ² に入る。

スタブの契約 (GSAS-II ソースから確定。**変えると静かに壊れる**ので `tests/autorietveld/
test_restraint_dlg.py` が変異テストで固定している):

| 要件 | 根拠 |
|---|---|
| ``Update(value, newmsg=...)`` は **タプル ``(True, '')``** を返す | `errRefine`:5017-5023 は ``type(GoOn) is tuple`` なら ``GoOn[0]`` を、そうでなければ ``GoOn`` 自体を真偽判定する。`strMain.AllPrmDerivs`:210 は ``dlg.Update(i)[0]`` と**添字**を取る。タプルなら両方を満たす |
| ``SetRange(n)`` は no-op でよい | `strMain`:207 が呼ぶだけ |
| ``SetHistogram`` は **実装しない** | 呼び出しは全て ``hasattr(dlg,'SetHistogram')`` ガード付き。実装すると余計な状態を持つだけ |
| 型名に ``"G2"`` を**含めない** | `errRefine`:5015 が ``'G2' in str(type(dlg))`` で分岐し、真だと ``Update`` に float を渡す (wx の G2 ダイアログ専用経路)。偽なら int が渡る = 素の Python で扱える |

``Update`` が偽を返すと GSAS は ``G2RefineCancel`` を投げて精密化を中断する。本スタブは
**常に続行**を返す (中断の判断は tsumugin 側の段階ガードが持つ)。

GSAS 非依存 (import なし・純 Python)。
"""

from __future__ import annotations

__all__ = ["RefineProgressStub"]


class RefineProgressStub:
    """`GSASIIstrMain.Refine(dlg=…)` に渡す最小のプログレス受け口 (常に「続行」を返す)。

    ⚠ **クラス名・モジュールパスに ``"G2"`` を入れないこと** — `errRefine` が
    ``'G2' in str(type(dlg))`` で wx 専用経路へ分岐する。

    観測用に呼び出し回数だけ数える (拘束が有効化されたかを ledger で確認できるようにするため)。
    メッセージは**最後の 1 本しか保持しない** — 精密化 1 回で数千回呼ばれるので、全部溜めると
    診断が主記憶を食う。
    """

    __slots__ = ("updates", "ranges", "last_message")

    def __init__(self) -> None:
        self.updates = 0
        self.ranges = 0
        self.last_message = ""

    def SetRange(self, n: object) -> None:  # noqa: N802 — GSAS 側の呼び名に合わせる
        """`GSASIIstrMain.AllPrmDerivs`:207 が呼ぶ。no-op でよい。"""
        self.ranges += 1

    def Update(  # noqa: N802 — GSAS 側の呼び名に合わせる
        self, value: object = 0, newmsg: str = ""
    ) -> "tuple[bool, str]":
        """常に ``(True, '')`` = 「キャンセルされていない・続行せよ」を返す。

        ``value``/``newmsg`` は wx のプログレス表示用で、計算には一切使われない。
        """
        self.updates += 1
        if newmsg:
            self.last_message = str(newmsg)
        return (True, "")
