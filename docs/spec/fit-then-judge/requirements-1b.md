# fit-then-judge P1-1B — 要件 (テンプレート: pass 1 → 静的コンパイル → 候補 `"template"`)

**位置づけ**: 設計 [`docs/design/fit-then-judge/proposal.md`](../../design/fit-then-judge/proposal.md) v5 の
**決定 1B** (§4) と統計の規約 (§5) を実装する段階 (§6 の P1-1B)。固定順のテンプレートを
「前処理の fit (pass 1) で判断を決め、静的なレシピと `PhaseSpec` にコンパイルし、本番の fit (pass 2) でそれを走らせる」
手続きとして作り、`search` の候補 `"template"` として既存の探索・収束確認に載せる。

設計判断と既存コードとの対応は [`docs/design/fit-then-judge/p1-1b-architecture.md`](../../design/fit-then-judge/p1-1b-architecture.md)、
作業計画は [`docs/tasks/fit-then-judge/p1-1b.md`](../../tasks/fit-then-judge/p1-1b.md)。1A の要件は [requirements.md](requirements.md)。

**範囲** (proposal §2 の第 1 期): CW X 線 (実験室・放射光)・単一ヒストグラム・単一パターン・GSAS-II。
**範囲外の入力で `"template"` を要求されたら、何も回す前に呼び出し全体を失敗させる** (② は error dict)。

**非目標**: 既定を変えること (`DEFAULT_CANDIDATES` に入れない・`run_auto_rietveld(recipe=None)` はビット同一) /
段順・閾値・D の回答表の調整 (P1.5) / 効果の測定 (P2) / LLM・人の回答ループ (決定 2) / TOPAS・joint・中性子・TOF・operando /
BIC 実装の統合 (別作業)。

---

## 1. 統計の規約 (REQ-FTJ-1B-1xx, proposal §5)

- **REQ-FTJ-1B-101** 入れ子のモデル (k 個の母数を足す) の比較は Hamilton の R 比検定 ≒ 尤度比: `Δχ²/GOF²_big` を
  自由度 k の χ² 分位点と比べる。Δχ² ≤ 0 は有意でない。入力が非有限・k < 1 のときは**判定しない** (None)。
  **観測集合が同じことは呼び手が保証する** (関数は観測集合を受け取らない。pass 1 は 1 つの fit の中の隣り合う段だけを比べる)。
- **REQ-FTJ-1B-102** 母数の数が同じ 2 解の比較は計算値の差 `S = Σ((m₁−m₂)/σ)²` を使い、`S/GOF²` が χ²₁ の分位点未満なら
  「区別できない」、それ以外は `z = Δχ²/(2·GOF·√S)` を返す。
- **REQ-FTJ-1B-103** 「同じ解か」はパラメータ差がそれぞれ kσ 以内 (esd は GSAS の値をそのまま — GOF を掛け直さない) で決め、
  Δχ² は使わない。既存の `agreement.parameter_agreements` を唯一の実装とする。
- **REQ-FTJ-1B-104** σ(χ²)=√(2·dof) を同一データ上の比較に使わない (コードに現れないことをガードで縛る)。
- **REQ-FTJ-1B-105** 実効自由度: 残差の系列相関 (Durbin–Watson 統計) から `n_eff/n` を推定する純関数を持つ。
  `RefinementMetrics` に None 既定の `effective_dof_ratio` を足し (None ならビット同一)、`noise_scale` との同時指定はエラー。
  ⚠ **このフィールドを埋める経路は P1-1B では作らない** (非露出の宣言): BIC の実装は 6 箇所に分かれており、その統合は別作業
  (proposal §5)。1B の判定量 (pass 1 の Hamilton 検定) は `fitstats` を直接使う。
  テンプレートの検定は**常に**基準モデル (入れ子なら小さい方) の残差から 1 回計算した比を両方に使う。

## 2. 入力宣言と範囲 (REQ-FTJ-1B-2xx, proposal §4.1・§3.5)

- **REQ-FTJ-1B-201** 宣言は JSON から作れる不変の型 (`TemplateDeclarations`) で受け、未知のキー・型違いは `ValueError`
  (② は error dict)。宣言しないことは「宣言なし」として扱い、各項目の既定は proposal §4.1 の表に従う。
- **REQ-FTJ-1B-202** 宣言は fit の設定を変えるが、**検出器を黙らせず、判断要求も閉じない**。宣言に依存した値は
  `provenance` に `declared:<キー>` を持つ (`Claim` の語彙。proposal の `declared(id)` と同じもの)。宣言は
  `actor = caller_unverified` として ledger に記録する。
- **REQ-FTJ-1B-203** 範囲の検査 (CW X 線・ヒストグラム 1 本・GSAS-II) は**精密化の前に**行い、外れたら
  `TemplateScopeError` (Tsumugin のドメインエラー)。`"template"` を含む探索・収束確認はこの 1 件で呼び出し全体が失敗する。

## 3. pass 1 — 判断を決める前処理 fit (REQ-FTJ-1B-3xx, proposal §4.3)

- **REQ-FTJ-1B-301** pass 1 は pass 2 と同じ段の 0–4 を走らせ、次を決めて `derivation` に記録する (何を見てどう決めたか)。
  - **格子を凍結する相**: 段 1 が棄却されたら全体を戻し (= 段 1 の前から)、違反した相の格子を外して段 1 をやり直す。
    帰属は 1 相ずつ格子を外した fit の比較で決める。段 0 の強度での事前凍結はしない。
  - **背景の項数**: 段 4 の後に項数を増やす段を並べ、Hamilton 検定 (実効自由度で補正) で有意でなくなる手前を採る。
  - **対象相**: 段 4 の後の相ごとの積分計算強度 Σ Fc²·Icorr が最大の 1 相。2 位との比が閾値を超えたら blocking な判断要求。
    対象相を宣言しても、近ければ判断要求は出る。
  - **Uiso のまとめ方**: 対象相の原子を (元素, 配位数) でまとめる規則。配位数を計算できないときは原子ごと (まとめない) とし、
    `derivation` に `unevaluated` と記録する。
  - **オフセット**: Bragg-Brentano は `Shift` を解放し Zero は装置値 (= D の既定)。pass 1 で `Shift` のみ vs `Shift + Zero` を
    Hamilton 検定し、有意なら格子に Zero との相関 (Shift は `Claim` の値ではないので判断要求の evidence に記す) と非 blocking な
    判断要求を付ける。Debye-Scherrer は `Zero`
    (偏心は解放しない)。
- **REQ-FTJ-1B-302** pass 1 の検定の fit が失敗・発散したら、その判断は「反証なし」ではなく `unevaluated` にして既定側を採る。
- **REQ-FTJ-1B-303** pass 1 の成果物は gpxstore に役割名 `template_pass1` で全保存する (規定 2026-08-20)。
- **REQ-FTJ-1B-304** pass 1 は決定論 (同じ入力・同じ runner ならビット同一の `derivation`)。

## 4. コンパイルと再生 (REQ-FTJ-1B-4xx, proposal §4.2・§4.4)

- **REQ-FTJ-1B-401** コンパイル結果は**静的な `RefinementStage` 列 + `PhaseSpec` のフィールド + ヒストグラム**だけで表し、
  `run_auto_rietveld(recipe=…)` だけで再生できる (動的な実行の器を作らない)。コンパイルは純関数。
- **REQ-FTJ-1B-402** 段は proposal §4.2 の表 (0 scale+bkgd / 1 lattice+offset / 2–3 width / 4 asym / R lattice-retry /
  5 coords / 6 B / 7 occupancy / 8 pref / 8R struct-retry / 9 final)。要らない段 (較正ありの asym・凍結相なしの R・
  混合占有なしの occupancy・Debye-Scherrer の pref) は出さない。相関群 (`CORRELATION_GROUPS`) を割らない。
- **REQ-FTJ-1B-403** 非対象相の構造 (座標・Uiso) は凍結する。極性群の対象相は原点を固定する。
- **REQ-FTJ-1B-404** コンパイル結果は版 (`template_version`) と `derivation` を持ち、② の出力に現れる。
- **REQ-FTJ-1B-405** engine に足す静的な部品: 段フラグ `cell_phases` (格子を解放する相を絞る。`refine_cell=False` には勝たない) /
  `run_auto_rietveld(blas_threads=…)` (BLAS のスレッド数の固定。プロセス全体に効くことを明記し、実行時のスレッド数を確かめる)。
  どちらも既定は無効で、既存経路はビット同一。

## 5. 探索・収束確認への載せ方 (REQ-FTJ-1B-5xx, proposal §4.4)

- **REQ-FTJ-1B-501** `CANDIDATE_NAMES` に `"template"` を足す。`DEFAULT_CANDIDATES` には入れない。
- **REQ-FTJ-1B-502** `RecipeCandidate` に `phases` (と `derivation`・`blas_threads`) を末尾追加する (既定 None で後方互換)。
  候補の実行と収束確認 (Phase B) は、候補が `phases` を持てばそれを使う。
- **REQ-FTJ-1B-503** 収束確認の摂動は**精密化するパラメータにだけ**掛ける。極性群で原点を固定した座標には座標の摂動を掛けない
  (従来は組み合わせを拒否していた。原点固定を指定したときだけの挙動なので既存の Phase B は変わらない)。
- **REQ-FTJ-1B-504** 開始点ごとに評価し直す側 (段の受理/revert・救済凍結) が開始点で割れたら、それを隠さず
  `initial_value_dependent` として記録する (1A の写像がそのまま担う)。

## 6. 初期値プローブ (REQ-FTJ-1B-6xx, proposal §4.5)

- **REQ-FTJ-1B-601** 保存した精密化済み gpx から開始し、**最終状態で解放されているパラメータだけ**を ±δ 摂動して
  同じ解放集合のまま精密化し直す engine の部品を作る。gpx は書き換えない (複製して使う)。
- **REQ-FTJ-1B-602** ±δ の 2 開始点の両方で値が kσ 以内に戻った値に `locally_stable` の証人を付ける。**振った値 (格子・実際に
  動かした座標) だけ**が対象で、摂動は一致の許容幅を超え、両開始点とも収束していること。戻らなかった値は
  `initial_value_dependent`。プローブを回さなかった・失敗した値は基底状態のまま (強いラベルを残さない)。
  `determined` の証人 (収束確認) がある値は降格しない (合成は最小 — 割れたときだけ落ちる)。
- **REQ-FTJ-1B-603** ② から JSON で要求できる。gpx を保存しない呼び出しでは回さず、理由を返す。

## 7. 露出 (REQ-FTJ-1B-7xx)

- **REQ-FTJ-1B-701** ②: `auto_rietveld(search=["template"], template={…宣言…})` で到達できる (別ツールは作らない)。
  範囲外は error dict。`refine_with_revisions` は spec に `template_version` があれば error dict を返す
  (テンプレートの手続きを経ない改訂を「テンプレートの結果」として出さない。強制は不完全だと明記する)。
- **REQ-FTJ-1B-702** ③: `skills/analyze` と AGENT_PLAYBOOK に「いつテンプレートを使うか・使えない範囲・`derivation` の読み方」を
  書き、手順書ガードで縛る (キーと候補名が ② に実在すること)。
- **REQ-FTJ-1B-703** 新しいフラグ・フィールドを使うテストは (準) hold-out を参照しない (`tests/test_holdout_guard.py`)。

## 8. 受け入れ条件

- 決定論テスト (GSAS 非依存) で統計・宣言・範囲・pass 1 の判断・コンパイル・候補・プローブの判定を検査し、ガード系は変異で落ちる。
- 実 GSAS の gated テストで、合成データ (`S-dev`) に対してテンプレート候補が pass 1 → コンパイル → pass 2 を完走し、
  `recipe=` での再生がビット同一になること。既存経路のゴールデンはビット同一のまま。
- ①②③ 露出: ② の出力に `derivation` 等が現れること、③ の手順書をガードで縛る (`tests/test_layer_coverage.py` の宣言を更新)。
