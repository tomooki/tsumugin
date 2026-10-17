"""fit-then-judge の事前登録した評価 (P0 §1–§2・§4・§7) の計算。

設計は `docs/design/fit-then-judge/p15-architecture.md`、定義の正は `docs/design/fit-then-judge/p0-preregistration.md`。
数値の核は stdlib + numpy だけ (凍結する評価スクリプトの依存を最小にする)。② / ③ には出さない (事前登録した実験の道具)。
"""
