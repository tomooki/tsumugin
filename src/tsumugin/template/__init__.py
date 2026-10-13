"""fit-then-judge 決定 1B — テンプレートの手続き (前処理 fit → 静的コンパイル → 本番 fit)。

設計: ``docs/design/fit-then-judge/p1-1b-architecture.md``。テンプレートは engine の部品を組み合わせて使う
手続きで、engine の外から ``run_auto_rietveld(recipe=…)`` だけを呼ぶ (静的コンパイルの不変条件)。
``autorietveld.search`` はテンプレートを候補 ``"template"`` として呼ぶが、本パッケージは ``search`` を
import しない (循環を作らない)。
"""
