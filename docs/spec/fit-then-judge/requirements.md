# fit-then-judge P1-1A — 要件 (出版状態の型と出版の止め)

**位置づけ**: 設計 [`docs/design/fit-then-judge/proposal.md`](../../design/fit-then-judge/proposal.md) v5 の
**決定 1A** を実装する段階 (§6 の P1-1A)。既存の標準経路 (`auto_rietveld` の単発・探索・収束確認) が出す値に、
出自・決定性・適用範囲・検査結果・出版の止めを持つ `Claim` を被せ、**証人の無い値・検査できなかった値を
出版しない**。フィットは変えない (既定経路はビット同一 — P1a のゴールデンで縛る)。

設計判断と既存コードとの対応は [`docs/design/fit-then-judge/p1-1a-architecture.md`](../../design/fit-then-judge/p1-1a-architecture.md)、
作業計画は [`docs/tasks/fit-then-judge/p1-1a.md`](../../tasks/fit-then-judge/p1-1a.md)。

**範囲** (proposal §2 の第 1 期): CW X 線・単一ヒストグラム・単一パターン・GSAS-II。範囲外の結果
(TOPAS・joint・中性子・TOF) にも `claims` は付くが、**検査器は `unevaluated` を返し、値は出版不可になる**
(黙って pass にしない)。

**非目標**: フィットのやり直し (D は fit を回さない) / テンプレート (1B) / LLM・人の回答ループ (決定 2) /
operando 系列 / 入力宣言の受け口 (1B §4.1。1A は「宣言なし」として扱う) / MEM 系ツールの sidecar 検査 (P1c)。

---

## 1. 型 (REQ-FTJ-1A-1xx)

- **REQ-FTJ-1A-101** `Claim` は値 1 つにつき 1 つ作り、軸 `determinacy`・`provenance`・`correlations`・`scope`・
  `checks`・`gate`・`witness` を**直積**として持つ (proposal §3.1 の表)。
- **REQ-FTJ-1A-102** `determinacy` は全順序 `exact > determined > locally_stable > esd_only > undetermined_esd >
  initial_value_dependent > unconverged > undeterminable` を持ち、合成は**最小**をとる。
- **REQ-FTJ-1A-103** `checks` は検査名ごとに `fail > unevaluated > pass` の三値をとり、合成は検査ごとに最大 (悪い方)。
- **REQ-FTJ-1A-104** `publishable` は保存せず導出する: `gate = ∅` ∧ `determinacy ≥ esd_only` ∧ 必須検査が
  すべて `pass`。必須検査の集合は値の種類ごとに型が決める (呼び手が渡さない)。
- **REQ-FTJ-1A-105** `determined` と `undeterminable` は**証人があるときだけ**付く。証人の無い強いラベルは
  構築時に拒否する (型の不変条件)。
- **REQ-FTJ-1A-106** 直列化 (`to_dict`→JSON→`from_dict`) は全軸を保存する。**素の float に化ける変換を
  テストで禁止する** (principles §4.4)。

## 2. 写像 (REQ-FTJ-1A-2xx)

- **REQ-FTJ-1A-201** 出自は**最終の共分散の varyList** (と従属変数) で決める。esd の三状態からは決めない
  (esd=None は「未解放・revert・共分散なし」を区別しないため)。
- **REQ-FTJ-1A-202** 写像は proposal §3.1 の表に従う (refined/symmetry/input/pruned/undetermined/
  initial_value_dependent)。最終段が収束していなければ精密化した値は `unconverged`。
- **REQ-FTJ-1A-203** 最終 varyList を持たない結果 (TOPAS・旧結果) では出自を決められないので、全値に
  検査 `provenance_known = unevaluated` を付ける (出版不可)。

## 3. 判断要求と止める値 (REQ-FTJ-1A-3xx)

- **REQ-FTJ-1A-301** proposal §3.2 の 7 種の判断要求を、**どの値を止めるか**込みで発行する
  (相集合の完全性 / 入力構造の出所 / 組成の化学的妥当性 / validity fail / 初期値で割れた / 格子を凍結した相 /
  座標の自由度の不一致)。
- **REQ-FTJ-1A-302** 止める範囲は直接 |ρ| が閾値を超える相手まで (推移閉包はとらない)。
- **REQ-FTJ-1A-303** 既定ポリシー D は各判断要求に既定回答 (`hold`) を版番号付きで返し、**止めを外さない**。
  止めが外れるのはデータの証人 (要求が発行されない) ときだけ。
- **REQ-FTJ-1A-304** 検出器は宣言に関係なく常に走る (1A に宣言の受け口は無いが、型はそれを前提にする)。

## 4. 証人と検査器 (REQ-FTJ-1A-4xx)

- **REQ-FTJ-1A-401** `determined` の証人は「Phase B の全開始点の対で、その値が kσ 以内 (または floor 以内) に
  一致した」こと。摂動が何も動かさなかった収束確認は証人にならない。
- **REQ-FTJ-1A-402** 相集合の完全性の証人は、最終 fit の計算反射位置から離れた窓の残差 S/N で決める。
  計算できないときは `unevaluated` (既定値 0.0 で「計算して 0」と混同しない)。`check_phase_set` は使わない。
- **REQ-FTJ-1A-403** 結晶化学検査器は相ごとに三値 (pass/fail/unevaluated) を返す新しい関数とする
  (既存 `check_bond_validity` の bool は M10 が依存するので変えない)。少なくとも粗大誤差 (短すぎる結合)・
  結合原子価和の GII・電荷中性を見る。pymatgen が無い・構造を組めない・酸化数を決められないときは `unevaluated`。
- **REQ-FTJ-1A-404** 結晶化学検査器は参照構造で陽性/陰性対照を持つ (欠陥を注入した構造で `fail`、
  正しい構造で `pass`)。

## 5. 出版の境界 (REQ-FTJ-1A-5xx)

- **REQ-FTJ-1A-501** ② `auto_rietveld` (単発・探索・収束確認) と `refine_with_revisions` の結果に、既存キーを
  残したまま `claims`・`judgment_requests`・`publishable_values`・`claims_version` を足す。値は JSON 安全
  (NaN/inf を出さない)。
- **REQ-FTJ-1A-502** 精密化済み gpx があるとき、その隣に sidecar `<gpx の stem>.claims.json` を置く。
  gpx の内容ハッシュを記録し、**読み手はハッシュが一致する sidecar だけを採る** (一致しなければ「状態不明」=
  出版不可)。既存の sidecar は上書きしない。
- **REQ-FTJ-1A-503** 表形式の出力 (CSV) は値ごとに出版状態の列を必ず持つ。出版不可の値を素の数値だけで
  書かない。② から呼べる。
- **REQ-FTJ-1A-504** ③ の手順書 (`skills/analyze`) は報告に `publishable_values` を使い、出版不可の値は
  状態を添えて報告するよう書き換え、ガードテストで固定する。⚠ 平文のフィールドは互換のため残るので、
  ② だけでは強制できない (既知の限界)。

## 6. 受け入れ条件

- 決定論テスト (GSAS 非依存) で型・写像・判断要求・D・直列化・CSV・sidecar を検査し、ガード系は変異で落ちることを示す。
- 実 GSAS の gated テストで、engine が足した観測フィールド (最終 varyList 等) が実際に埋まり、既定経路の
  ゴールデンがビット同一のままであること。
- ①②③ 露出: ② の出力に新キーが現れることをテストで確かめ、③ の手順書をガードで縛る
  (`tests/test_layer_coverage.py` の宣言を更新)。
