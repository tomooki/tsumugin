# 修正案 v5: Fit → Judge — 出版の型を先に作り、テンプレートは静的にコンパイルして試す

- **状態**: Proposed **v5** (2026-10-09。批判的レビュー 4 巡を反映。対応表は [review-response.md](review-response.md))。
  **P1a (engine の部品) はタスク 0–7 を実装済み** (`docs/tasks/fit-then-judge/p1a.md`) — 4 巡目で 3 名とも「P1a は着手してよい」と判定し、ユーザーが承認した
- **v5 で変えた骨格** (4 巡目):
  1. **決定 1 を 1A と 1B に分けた**。1A = 出版状態の型・出版の止め・判断要求の発行を**既存の標準経路の出力に被せる**。
     1B = テンプレートの手続き。証拠のある不足 (Rwp で見えない誤りを止める型が無い・出力に出自が無い) を、
     未検証の仮説 (固定順で足りる) から切り離す。principles §6 の「型が先」の順序とも一致する
  2. **テンプレートは「前処理で判断し、静的なレシピにコンパイルし、それを走らせる」2 段**にした。動的な実行の器を作らず、
     再生は `recipe=` だけで済む (§4)
  3. **出版状態の各軸に順序と合成規則を定義**し、`unevaluated` は出版不可、`determined` は証人があるときだけにした (§3.1)
  4. **同一データ上の比較の尺度を直した** — σ(χ²)=√(2·dof) は誤り (principles §3.2 も訂正済み)。esd に GOF を二重に掛けない (§5)
  5. 呼び手の宣言は**検出器を黙らせず、判断要求も閉じない** (§3.5)
- **採否**: 1A と 1B は独立に採否できる。決定 2 (LLM/人の回答ループ) は引き続き設計段階に留める
- **第 1 期の範囲**: CW X 線・単一ヒストグラム・単一パターン・GSAS-II。範囲外は**明示的に失敗させる**
- **関連**: `docs/design/stable-baseline-recipe/STANDARD-PROCEDURE.md` / `docs/design/claim-oriented-architecture/principles.md` /
  `docs/design/m8-agentic-loop/` / `docs/spec/stable-auto-rietveld/requirements.md` / 作業計画 `docs/tasks/fit-then-judge/p1a.md` / P0 事前登録 [p0-preregistration.md](p0-preregistration.md)

---

## 0. 要旨

**1A**: 既存の標準経路 (`auto_rietveld` の単発、`optimize_then_confirm`) が出す値に、出自・決定性・適用範囲・検査結果・出版の止めを
軸に持つ `Claim` を付ける。決まらなかったこと・検査できなかったことは**判断要求**として出し、決定論の既定ポリシー D が既定回答する
(1A の D は fit をやり直さず、出版の可否だけを決める)。証人の無い値・検査できなかった値は出版しない。

**1B**: 固定順のテンプレートを、**前処理の fit (pass 1) で判断を決め、静的なレシピと `PhaseSpec` にコンパイルし、本番の fit (pass 2) で
それを走らせる**手続きとして作る。コンパイル結果は `search` の候補 `"template"` として既存の探索・収束確認に載る
(`DEFAULT_CANDIDATES` には入れない)。手順そのものの効果は P2 のアブレーションで測る。

---

## 1. 背景 — 確かめたこと / まだ確かめていないこと

2026-10-07〜09 に、手書きの段階精密化 (RIETPY の stagefit) 10 本・Tsumugin の現行規定・試作した汎用テンプレート
(RIETAN-FP / GSAS-II / TOPAS) を、未公開の実測データ (CW X 線・単一ヒストグラム・1–3 相) で比較した。数値は非公開の
ローカル成果物にのみ置く (`docs/benchmark/` の規約)。

**確かめたこと** (この範囲・この条件で):
- 人の種付けが入った出発状態から同じエンジンで走らせると、固定順の手順 1 本で手書きの**初段**と同等以上のフィットが得られた。
  種付けの無い移植は一部のデータで初段を下回った。
- テンプレートの**モデル化の選択** (背景項数・Uiso の等値化・副相の構造凍結・段ごとの物理ゲート) は、現行の候補群が共有していた
  破綻 (副相の格子発散・座標の暴走) を避けた。
- **Rwp では見えない誤り**が両方の手順に多数あった (入力構造の欠陥・化学的にあり得ない結合長・内部矛盾)。

**確かめていない/撤回したこと**:
- 「現行規定の選択層は役に立っていない」は撤回 (既定レシピ単独より大きく効いていた)。
- 優位が手順によるのかモデル化の選択によるのかは識別していない。手書きの最終版はテンプレートを上回るデータが多い。
- 評価は in-sample。初期値依存・収束・コールドスタートは未測定。
- 「単一の段順で全データを満たせない」(requirements.md F1) は範囲内にも記録がある。**固定順は前提であって事実ではない**。

**この設計が解く問題を 2 つに分ける** (4 巡目の指摘): (a) Rwp で見えない誤りを出版前に止める型が無い・出力に出自が無い
(証拠あり → 1A)、(b) 固定順のテンプレートとそのモデル化の方針が現行より良い (仮説 → 1B、P2 で検証)。

---

## 2. 範囲と非目標

| | 第 1 期で扱う | 扱わない |
|---|---|---|
| 放射源 | CW X 線 (実験室・放射光) | 中性子 CW・TOF |
| ヒストグラム | 単一 | joint |
| 解析単位 | 単一パターン | operando/in situ 系列 (REQ-SAR-502) |
| エンジン | GSAS-II | TOPAS (#218/#219 の後に別途判断) |

範囲外の入力で 1B を要求されたら呼び出し全体を error dict にする (ガードテスト付き)。1A は既存経路の出力に被せるだけなので、
範囲外のデータでは**検査器が `unevaluated` を返す** (黙って pass にしない)。
**非目標**: 新エンジンの導入 / LLM に構造を自由に書き換えさせること / operando のフレーム単位の判断 / 第 1 期に既定を変えること。

---

## 3. 決定 1A — 出版状態の型と出版の止め (既存経路の出力に被せる)

### 3.1 `Claim` の軸・順序・合成

principles §3 の `Claim = (value, evidence, scope, refuter)` を 1 種類だけ使い、出版状態はその中に**軸ごとの直積**として持つ。

| 軸 | 値域と順序 (左ほど強い) | 合成 (開始点間・依存の伝播) |
|---|---|---|
| `determinacy` | `exact` (対称性で厳密) > `determined` (証人あり) > `locally_stable` (初期値プローブで戻った) > `esd_only` (esd>0 だけ) > `undetermined_esd` > `initial_value_dependent` > `unconverged` > `undeterminable(証人)` | **最小** (弱い方)。開始点間で値が kσ を超えて割れたら `initial_value_dependent` に落とす |
| `provenance` | 集合 ⊆ {`refined`, `input`, `symmetry`, `origin_fix`, `pruned`, `declared(id)`, `policy_default(版)`} (順序なし) | **和集合**。~~開始点間で異なれば `determinacy` を `initial_value_dependent` に落とす~~ → **改訂 (2026-10-15, P1.5, ユーザー決定)**: 出自の違いだけでは落とさない。値が開始点の一致の許容幅を超えて割れたときだけ `initial_value_dependent`。出自が違ったことは証人 `provenance_varied` に残し、その値は `determined` に上げない (ある開始点では精密化していないので試験したとは言えない)。**同日の改訂 2**: 最良の開始点より χ² が有意に大きい開始点 (Δχ²/GOF²_best > χ²₁ の 99% 点) は「最良の解に届かなかった」として値の比較から外す (validity に落ちた開始点と同じ扱い。全開始点が揃わないので `determined` にもしない) |
| `correlations` | 相手の集合 (\|ρ\| が閾値超) | 和集合 (推移閉包はとらない — §3.3) |
| `scope` | `absolute` / `relative_within_sample` (同一試料・同一測定内の比・差にのみ有効) | 弱い方 (`relative`) |
| `checks` | 検査ごとに `fail` > `unevaluated` > `pass` | 検査ごとに最大 (悪い方) |
| `gate` | 出版を止める判断要求 id の集合 | 和集合 |
| `witness` | `determined`・`undeterminable`・閉じた判断要求の根拠 | 合成時は両方を保持 |

- **`publishable` は保存せず導出する**: `gate = ∅` かつ `determinacy ≥ esd_only` かつ**必須検査がすべて `pass`**
  (`unevaluated` は出版不可 = `provisional`)。`exact` と `not refined` の固定値は `provenance` で区別する。
- **`determined` は証人があるときだけ**付ける。1A での証人は「判断を固定した Phase B で全開始点が kσ 以内に一致した」。
  証人の無い esd>0 は `esd_only` (基底状態)。予算切れでプローブを省いた値は基底状態のまま (強いラベルが残らない)。
- **既存フィールドからの写像** (出自は最終の共分散の varyList で決める — esd=None は「未解放・revert・共分散なし」を区別しないため):

| 既存の状態 | `provenance` | `determinacy` |
|---|---|---|
| 最終 varyList にあり esd>0 | `refined` | `esd_only` (証人があれば昇格) |
| 対称性で固定 (`GetCSxinel` の従属・特殊位置) | `symmetry` | `exact` |
| 最終 varyList に無い (解放しなかった) | `input` | `exact` ではない固定値 — 出版は「入力値」と明示 |
| `frozen_parameters` (救済凍結・毎段プルーニング・最終研磨) | `pruned` | `undetermined_esd` |
| `undetermined_parameters` | `refined` | `undetermined_esd` |
| `undetermined_by_initial_values` | `refined` | `initial_value_dependent` |

### 3.2 判断要求 — 必須項目と止める値

- **既存の `ActionProposal` (`refine_loop/diagnostics.py`) を拡張する** (trigger・evidence・default・priority・blocking・候補・止める値)。
- 判断要求ごとに**どの値を止めるか**を表で固定する (伝播の範囲を明示し、推移閉包はとらない):

| 判断要求 | blocking | 止める値 | 1A での出所 |
|---|---|---|---|
| 相集合の完全性 (必須) | 証人が `fail`/`unevaluated` なら yes | 全相の相分率・格子・構造 (欠落相は全値を偏らせる) | §3.3 の証人 |
| 入力構造の出所 (必須) | no — **宣言でしか閉じない項目**として `scope` に写す (データから証人は原理的に得られない) | — (`scope.input_provenance = declared/undeclared`) | 呼び手の宣言 |
| 組成の化学的妥当性 (必須) | 検査が `fail`/`unevaluated` なら yes | その相の構造値 | 結晶化学検査 |
| 物理妥当性 (validity) fail | yes | 違反した変数とその相 | `check_validity` |
| 初期値で割れた | yes | 割れた変数 + \|ρ\| 直接相関の相手 | Phase B の `agreement` |
| 格子を凍結した相 | yes | その相の相分率 | 解放状態 |
| 座標の自由度の不一致 | yes | その原子の座標 | §6 P1a 部品 7 |

- **検出器は宣言に関係なく常に走る** (§3.5)。
- 結晶化学検査は粗大誤差のフラグ (短すぎる結合・GII・電荷中性) を三値で返す**新しいフィールド**として足す
  (既存の `check_bond_validity` の bool `passed` は M10 が依存しているので変えない)。

### 3.3 証人

- **相集合の完全性の証人** (`check_phase_set` は系列専用で 1 フレームでは常に完全と答えるので使わない — ガードテストで固定):
  - **残差側**: 最終 fit の計算反射位置 (GSAS の反射リスト) から**離れた**窓ごとに、残差の積分 S/N を求める。閾値を超える窓があれば `fail`。
    値は Optional で、計算できない (残差が空・反射リストが取れない) ときは **None = `unevaluated`** (既定値 0.0 で「計算して 0」と
    区別できない既存の `unindexed_peak_frac` は使わない)。
  - **同定側** (任意): M11 `identify_pattern` の残差同定を使うときは、検索範囲 (供給元・元素系・候補数) を `witness` に記録する。
    範囲が空、または既知の相だけなら `unevaluated`。
- **|ρ| による伝播**は、最終の共分散で直接 |ρ| が閾値を超える相手まで (推移閉包はとらない — スケールと B を経由してほぼ全値が止まるため)。
  凍結した変数は共分散に入らないので、凍結の影響は 1B の反証プローブでしか見えない。1A では凍結した変数の存在そのものを
  `provenance` に記録し、依存する値 (同じ相の相分率など) を表で止める。

### 3.4 既定ポリシー D (1A)

- 1A の D は **fit をやり直さない**。各判断要求に既定回答 (`hold` = 出版しない) を返し、版番号付きで記録する。
- **D は出版の止めを外さない**。止めが外れるのは「データが決めた (証人付き)」ときだけ (1A では人の回答経路が無い = 決定 2)。
- D は `AnalysisPolicy` を実装しない (ループしないため)。テンプレート/1A 経路では M8 の `RuleBasedPolicy` を回さない。

### 3.5 呼び手の宣言

- ② から入る宣言 (§4.1 の入力宣言を含む) は `actor = caller_unverified` として ledger に記録する。② は LLM と人を区別できない。
- **宣言は fit の設定を変えるが、検出器を黙らせず、判断要求も閉じない** (principles §1.4: 凍結・宣言は検出器を黙らせる)。
  例: 対象相を宣言しても、相ごとの積分強度が僅差なら判断要求は出る。宣言に依存した値は `provenance = declared(id)` を持つ。
- 判断要求を閉じられるのはデータの証人と、決定 2 の承認済み回答 (workbench の `approve` モードで人が出した `approval_decision`) だけ。

### 3.6 出版の境界

- ② の結果 dict: 既存の平文のフィールドは**互換のため残す**。そのうえで `claims` と、**出版可の値だけを集めた `publishable_values`** を足す。
  ③ の手順書は報告に `publishable_values` を使うよう書き換え、ガードテストで固定する。
  ⚠ 平文のフィールドが残る以上、② だけでは強制できない (既知の限界として明記)。強制するのは出力層 (CIF/CSV/GUI) と ③ の手順書。
- CIF/CSV 出力は出版不可の値を出さない (または明示的な印を付ける)。
- `.gpx` は状態を持てないので sidecar を置く: **`<gpx の名前>.claims.json`** (gpx と 1 対 1・上書き禁止・合成した claims は対象の gpx を記録)。
  1A/1B 以降の run で sidecar が無ければ「状態不明」として出版不可に倒す。精密化済み gpx を入力に取る ② ツール (MEM 等) は sidecar を読む。
- 状態を落とす変換 (直列化の往復・エクスポート) をテストで禁止する。

---

## 4. 決定 1B — テンプレートの手続き (前処理 → 静的コンパイル → 本番)

### 4.1 入力宣言

| 宣言 | 効くもの | 宣言が無いとき |
|---|---|---|
| 装置の較正 (標準試料由来の U,V,W,X,Y・非対称・ゼロ点・波長) | 幅を試料広がりとして読めるか / ゼロ点 | 幅は装置関数込みで精密化、試料広がりは解放しない |
| 格子の絶対値の基準 (**同一試料内の内部標準**) | `scope = absolute` | `scope = relative_within_sample`。Debye-Scherrer でもキャピラリの偏心・吸収によるずれは試料ごとの量なので、内部標準が無ければ relative |
| 試料の幾何 (反射 / 透過・キャピラリ、μR、表面粗さ) | オフセットの型・B・占有率 | `read_pattern_metadata` が拾えた値。拾えなければ判断要求 + D の既定 (下表) |
| 偏光・単色器 / 外部背景 / 対象相 / 参照構造の温度 | (v4 と同じ) | (v4 と同じ) |

宣言は §3.5 の規則に従う (記録され、検出器を黙らせない)。

### 4.2 段 (pass 2 の静的レシピ)

群の定義は `recipe.CORRELATION_GROUPS` を唯一の出所とする。ゼロ点は現在どの群にも属さない (`profile_lorentzian` に束ねられている) ので、
**`zero_offset` 群を新設**して位置オフセットを規則の内側に入れる。

| # | 段 | 解放 |
|---|---|---|
| 0 | scale+bkgd | 全相スケール + 背景 (項数は pass 1 で決めた値) |
| 1 | lattice+offset | 格子を凍結しないと決めた全相の格子 + オフセットを 1 つ (下の表) |
| 2 | width-1 | 較正なし: U,V,W / 較正あり: Size+Mustrain |
| 3 | width-2 | 較正なし: X,Y (ゼロ点は束ねない) / 較正あり: 異方性幅 |
| 4 | asym | 較正なしのときだけ |
| R | lattice-retry | pass 1 で格子を凍結した相 (弱い相を含む) の格子を 1 回 |
| 5 | coords | 対象相の自由座標 (原点固定込み)。**期待自由度が 0 の段は noop 判定から除く** |
| 6 | B | 対象相の Uiso を pass 1 で決めたまとめ方で |
| 7 | occupancy | 混合占有 (和=1 + Uiso 等価)・部分占有 |
| 8 | pref | 選択配向 (対象相に。回転キャピラリでは既定で試さない) |
| 8R | struct-retry | 段 5/6 が棄却されていたら 1 回だけ再試行 (選択配向で B 段が棄却されたまま戻らない病理を拾う) |
| 9 | final | 全受理パラメータ + **収束確認の追加 1–2 サイクル** (\|shift\|/esd を自前で計算。GSAS の `Max shft/sig` は Refine 呼び出し開始点からの総移動量の符号付き最大値で、収束判定に使えない) |

**オフセットの扱い**:

| 幾何 | 解放 | ゼロ点 | 反証 |
|---|---|---|---|
| Bragg-Brentano | `Shift` | 装置値に固定 (= D の既定回答)。装置ファイルの Zero が既定値かを `inspect_instprm` で判定し、既定値なら `provenance = policy_default` | pass 1 で `Shift` のみ vs `Shift + Zero` を Hamilton 検定 (§5)。Zero が有意なら格子を `correlations = {Shift, Zero}`・`scope = relative` にし、判断要求 (非 blocking) |
| Debye-Scherrer | `Zero` | — | 偏心 (`DisplaceX/Y`) は解放しない。格子は内部標準が無ければ relative |
| 不明 | なし | 装置値 | 判断要求 (blocking: 格子・相分率)。D の既定 = 解放しない |

### 4.3 pass 1 — 判断を決める前処理 fit

pass 1 は段 0–4 を走らせ、次を決めて記録する (`derivation`):
- **格子を凍結する相**: 段 1 は**全体を戻してから、違反した相の格子を凍結して段 1 をやり直す** (同時解の一部だけを戻すと
  非停留の状態が残るため)。帰属は相ごとの物理ゲート (格子の許容窓・崩壊) の違反で決める。違反が無いのに全体が悪化したときは、
  相ごとに 1 相ずつ格子を外した fit を比べて帰属させる。**段 0 の強度での事前凍結はしない** (段 0 の分率は潰れうる)。
- **背景の項数**: 段 4 の後に候補ごとに比べ、Hamilton 検定 (§5) で選ぶ (段 0 では格子とプロファイルが未精密化で背景がピークの
  合わなさを吸収するため)。
- **対象相**: 段 4 の後の相ごとの**積分計算強度 Σ Fc²·Icorr** (GSAS の反射リスト。Icorr はスケール・多重度・偏光・選択配向・
  吸収・Lorentz・1/V² を含む) が最大の 1 相。近い相があれば blocking な判断要求。
- **Uiso のまとめ方**: 規則で決める (同一位置は等値、元素×配位環境でまとめる)。段階緩和の検定は P2 で効果を測ってから。
- **オフセット**: §4.2 の表と反証。

pass 1 の成果物も gpxstore に役割名 (`template_pass1`) 付きで全保存する。

### 4.4 コンパイルと再生

- コンパイル結果は、**静的な `RefinementStage` 列 + `PhaseSpec` のフィールド + `HistogramSpec` の背景項数**だけで表す
  (例 `refine_cell=False`・`uiso_equiv_groups`・`fix_polar_origin`・非対象相の構造凍結)。**`run_auto_rietveld(recipe=…)` だけで再生できる**
  ことを不変条件にする (engine の部品はすべて静的なフラグか `PhaseSpec`/`HistogramSpec` のフィールドで表す)。
- **固定するもの / 評価し直すもの**:

| 固定する (コンパイル済み) | 開始点ごとに評価し直す (engine) |
|---|---|
| 対象相・格子を凍結する相・背景項数・Uiso のまとめ方・原点固定・オフセットの選択・段列 | 段の受理/revert・救済凍結/剪定・任意段の統計的受理 |

  評価し直す側の結果が開始点で割れたら、それ自体を `initial_value_dependent` として記録する (隠さない)。
- **既存の探索・収束確認に載せる**: `CANDIDATE_NAMES` に `"template"` を足す (`DEFAULT_CANDIDATES` には入れない)。この候補の
  ビルダーが pass 1 を走らせ、`RecipeCandidate(stages=コンパイル済み段列, histograms=…)` を返す。候補が `PhaseSpec` を変えられる
  よう `RecipeCandidate` に `phases` を末尾追加する (既定 None で後方互換)。Phase B は `run_multistart_rietveld(recipe=…)` で再生し、
  **摂動は精密化するパラメータにだけ掛ける** (凍結した格子・座標への摂動は既存の欠陥として別作業で修正中)。
- `refine_with_revisions` は spec を受けず `from_dict` が未知のキーを黙って捨てるので、テンプレート由来かを判定できない。
  ② の入口で**生の dict のまま**目印 (`template_version`) を検査して error dict を返し、③ の手順書とガードテストで補う
  (強制は不完全だと明記)。
- `template_rietveld` という別ツールは作らない (候補として載るので `auto_rietveld(search=["template"])` で到達できる)。
  範囲外のデータに `"template"` を要求したら呼び出し全体を error dict にする。

### 4.5 初期値依存

- 初期値プローブ (最終状態から ±δ の 2 開始点) には「保存した gpx から開始して摂動する」engine の部品が要る (P1-1B で作る)。
- 判定は §5 の規約: 「同じ解に戻った」= パラメータ差がそれぞれ kσ 以内 (esd は GSAS の値をそのまま使う — 既に GOF² を含む)。
  戻っても `locally_stable` 止まり。
- 極性群では Phase B の座標ジッタを原点固定した座標に掛けず、ベイスン比較では極性方向の並進を除く。
  (この変更を共有の multistart に入れると既存の Phase B の結果が変わるので、テンプレートのフラグの裏に置く。)

---

## 5. 統計の規約 (1A/1B 共通。principles §3.2 を 2026-10-09 に訂正)

| 比較 | 判定量 |
|---|---|
| 入れ子のモデル (k 個の母数を足す: 任意段・背景項数・凍結の解除・オフセット) | **Hamilton の R 比検定 ≒ 尤度比**: `Δχ²/GOF²` を自由度 k の χ² 分位点と比べる |
| 母数の数が同じ 2 解 (ベイスン・±δ) | 計算値の差 `S = Σ((m₁−m₂)/σ)²`。`S/GOF²` が χ²₁ 分位点未満なら区別できない。大きければ `z = Δχ²/(2·GOF·√S)` |
| 「同じ解か」 | パラメータ差がそれぞれ kσ 以内 (Δχ² は使わない) |
| 観測集合が違う | χ²/Rwp を比べない。観測集合は除外区間の内容ハッシュで識別する |

- **σ(χ²)=√(2·dof) は使わない**: データを取り直したときのばらつきで、同じデータ上の 2 つの fit の差の雑音ではない (点数が増えるほど甘くなる)。
- **esd に GOF を掛け直さない**: GSAS-II の esd は既に GOF² を含む (`covMatrix = result[1]*GOF**2`)。構造の悪化の指標は
  `σ_c = √(σ_ref² + σ_fit²)`。
- **実効自由度** (残差の系列相関): `RefinementMetrics` に `noise_scale` (FR-123) と同じく None 既定の opt-in 項目として足す
  (None ならビット同一)。推定は Durbin–Watson 統計からの Bérar–Lelann 型の補正。1B では**常に渡す**。比較では基準モデル
  (入れ子なら小さい方) で 1 回計算して両方に使う。`noise_scale` との同時指定はエラー。BIC の実装の統合は別作業
  (`evidence/ic.py` の他に `search.candidate_bic`・`anchor/select.frame_bic`・`insitu/engine`・`nested/laplace`・`workbench/session`)。
- 凍結の反証 (BIC/Hamilton) は副相では検出力が低い (母数あたりの罰則)。**検出力を報告する**。反証の fit が発散・失敗したら
  「反証なし」ではなく `unevaluated` にする (物理ゲートを掛ける)。

---

## 6. 検証計画

### データの区分 (P0 で commit)

| 区分 | 中身 | 使ってよい段階 |
|---|---|---|
| 開発用 | 未公開の実測データ (試作に使った群) + 合成ケース (**hold-out と別の構造から作る**。既知の欠陥の注入・混合占有・極性群) | P1・P1.5 (実データの検査はリポジトリの外で記録 — 未公開データは public に置けない) |
| 準 hold-out | 範囲内の公開データ (T1・CaTeO3・T3 の X 線単独・T4 の 11-BM 単独)。⚠ テンプレートの設計自体がこれらの既知の挙動 (F1–F3・recipe.py の教訓) から作られているので「準」と表示する | P2 のみ。1 回だけ |
| hold-out | 凍結後に取得した未公開データ。**最小件数はこれで満たす** (公開 4–5 件では率の推定に検出力が無い)。P0 v1.2 で公開・未使用データの無作為抽出を追加 ([p0-preregistration.md](p0-preregistration.md) §3.2) | P2 のみ。1 回だけ |

- **テンプレートのフラグ・`PhaseSpec` の新フィールドを使うテストは、(準) hold-out のファイルを参照しない** — ガードテストで縛る
  (ファイル名だけでなく、データディレクトリの参照を検査する)。既存経路の非回帰テスト (ゴールデン) は読んでよい。
- 構造の悪化の指標の**参照構造は出発構造と独立な出典**にする (同じ出典だと何も動かさない fit が最良になり、凍結の多い手順に有利)。
  格子の比較は `scope = absolute` のものだけ。

### 段階

| 段階 | 内容 | 通過条件 |
|---|---|---|
| **P0** | 不変の評価プロトコルの事前登録 (指標・同値幅・通過基準・データ区分と最小件数・構造の悪化の指標・`provisional` 割合の上限・`determined` の外れ率の上限・反証の検出力の報告形式)。結晶化学検査器の**実装は P1-1A に分ける** (登録と実装を混ぜない)。→ [p0-preregistration.md](p0-preregistration.md) | commit |
| **P1a** | engine の部品 (下表)。すべて**既定は無効 (opt-in)・既存経路はビット同一** | 決定論テスト + ゴールデン |
| **P1-1A** | `Claim` の型と写像 → 判断要求の発行 → 証人 → D → ② (`claims`/`publishable_values`) → ③ の手順書 → sidecar → CIF/CSV。結晶化学検査器 (R0 表・酸化数・`unevaluated`) と参照構造での陽性/陰性対照 | 決定論テスト + ①②③ 露出 + 状態を落とす変換の禁止テスト |
| **P1-1B** | pass 1 → コンパイル → `"template"` 候補 → 既存ツールとの境界 → ③ 手順書。統計規約 (§5) の実装 | 同上 |
| **P1c** | GUI の承認カード・MEM 系ツールの sidecar 検査 | — |
| **P1.5** | 開発用データで段順・閾値・D の回答表を調整し、**テンプレート版と D の版のハッシュを hold-out の前に commit** | 凍結版の commit |
| **P2** | 凍結版を (準) hold-out で 1 回だけ測る。基準 = 単発 `build_recipe` と Phase A+B。アーム = アブレーション (背景を揃えたもの・現行候補にモデル化を移植) / コールドスタート / 段順の置換 / 頑健性 / 吸収・粗さ・偏光の宣言 / 多相で副相の幅が共有 U,V,W しか持てない影響。反証条件が発火したら再調整版は新しい hold-out まで in-sample と表示 | 事前登録の基準 |
| **P3/P4** | (v4 と同じ) 決定 2 の試験・ADR | — |

### P1a の部品 (詳細は `docs/tasks/fit-then-judge/p1a.md`)

| # | 部品 | 表し方 (静的) | 既定 |
|---|---|---|---|
| 0 | **ゴールデン**: 既存の既定経路 (T1・CaTeO3) の最終値・段列・esd の指紋を、変更前の main で同じ環境から採る | テスト | — |
| 1 | revert 理由の列挙を `StageResult` に | 観測 | 常に記録 (値は変えない) |
| 2 | Uiso の等値グループ | `PhaseSpec.uiso_equiv_groups` | 空 |
| 3 | 極性方向の原点固定 | `PhaseSpec.fix_polar_origin` | False |
| 4 | ゼロ点を独立に解放 | 段フラグ `zero_offset` + `CORRELATION_GROUPS["zero_offset"]`、`profile_lorentzian` にキー列を許す | 既存の `profile_lorentzian: True` は従来どおり X,Y,Zero |
| 5 | 相ごとの積分計算強度 Σ Fc²·Icorr | 観測 (結果のフィールド) | 常に記録 |
| 6 | 座標の自由度の照合 (座標から再計算した site symmetry と `GetCSxinel`) | 観測 | 常に記録 |
| 7 | 精密化後の構造の書き出し | `run_auto_rietveld` の引数 | 無効 |
| 8 | BLAS のスレッド数の固定 (`threadpoolctl`) — **P1-1B へ移した** (依存の追加が共有 venv に及ぶため、使うときに入れる) | 引数 | 無効 (プロセス全体に効くことを明記) |

**engine の変更が要らないと分かったもの**: ledger の永続化 — `run_auto_rietveld` は既に `ledger=` を受けるので、既存の
`PersistentLedger` を渡せば足りる (② からの配線は P1-1B)。

**保留** (P1-1B の設計に依存): 相ごとの格子ロールバック (pass 1 の中で実装)・任意段の統計的受理・段ごとのサイクル数・再試行段・
保存した gpx から開始して摂動する部品 (初期値プローブ用。`run_auto_rietveld` は毎回 CIF から組み立てるので作りが大きく変わる)。

---

## 7. この提案を反証する結果

- 1A: `provisional` の割合が上限を超える (止めすぎて情報が無い) / 出版可とした値が参照から kσ を超えて外れる率が上限を超える
- 1B (P2): テンプレートが基準より構造を悪くする / 優位がすべてモデル化の選択で説明される (→ 1B は「現行候補のモデル化を直す」に縮小) /
  段順の置換で結果の差が同値幅を超える (→ 固定順の前提を撤回) / 開始点で割れる率が Phase A+B より高い
- D の既定回答の反証率、または反証の検出力が事前登録の下限を下回る
- P3: LLM/人の上書きが D に勝てない、害の率が閾値を超える

---

## 8. 影響範囲

| 既定 | 第 1 期 |
|---|---|
| ① `run_auto_rietveld(recipe=None)` | 変えない (ゴールデン) |
| ② `auto_rietveld` / `search` / `DEFAULT_CANDIDATES` | 変えない。1A は結果 dict に `claims`/`publishable_values` を**足す**。1B は `CANDIDATE_NAMES` に `"template"` を足す |
| ③ `skills/analyze` | Phase A+B の規定は変えない。報告は `publishable_values` から行うよう書き換える (1A) |

| 共有コードの変化 | 既存経路への影響 | 保証 |
|---|---|---|
| P1a の部品 | なし (すべて opt-in・観測のみ) | ゴールデン |
| `RefinementMetrics` の実効自由度 | なし (None でビット同一) | 既存 BIC の非回帰 |
| BLAS 固定 | 有効にしたプロセス全体 (workbench の並行ジョブを含む) | 文書化 + 実行時スレッド数の assert |
| `check_bond_validity` の三値 | 新フィールドのみ | M10 のテスト |
| `propose_next_actions` の縮退・直列化・`features_from_dicts` の全復元 | 既存の analyze ループに `SetAbsorption` 等の提案が出始める (`_result_from_dict` が `hist_absorption` を戻さないので現在値も復元する) | ② の境界テスト |
| `RecipeCandidate.phases` | なし (末尾追加・既定 None) | 既存 search のテスト |

---

## 9. 未決事項

- 結晶化学検査の R0 表の出典と unevaluated の境界 (P1-1A)
- 実効自由度と `noise_scale` の関係・推定法の詳細 (P1-1B の前)
- 合成ケースの作り方と出所の記録 (P0)
- 第 2 期 (joint・中性子・TOF)、TOPAS でテンプレートを使うか
- workbench の役割と承認カードの語彙 (P1c / 決定 2)
- BIC 実装の統合 (別作業)
- spec は P1-1A の着手時に `docs/spec/fit-then-judge/` に置く (P1a は `docs/tasks/fit-then-judge/p1a.md` で足りる規模)
