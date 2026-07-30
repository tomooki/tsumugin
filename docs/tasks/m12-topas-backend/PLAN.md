# M12 実装計画: TOPAS バックエンド

ブランチ: `milestone/m12-topas-backend` / 設計: `docs/design/m12-topas-backend/architecture.md`

到達点はユーザー選択により **「第 2 段: `autorietveld` も Topas 化」** (= `RefinementBackend` 層 +
実構造段階解放エンジンの両方)、段階フラグは **TOF/joint まで**、バックエンド選択は
**② に `backend` 引数を新設**。

## 進捗

| # | タスク | 状態 | 備考 |
|---|---|---|---|
| T0 | 前提確認 (tc.exe がライセンス的に起動するか) | ✅ | CodeMeter ドングルで headless 起動。実測事実 9 件は設計 §2 |
| T1 | 可用性境界 (`topas.availability` / 例外 / marker) | ✅ | 明示指定は権威的・`=none` で強制無効化。skip ガードを 3 モードで実証 |
| T2 | INP 文書ビルダ (`topas.inp`) | ✅ | joint の `prm` 持ち上げ。実 tc.exe で受理・収束を確認 |
| T3 | CIF → `str` ブロック (`topas.structure`) | ✅ | 結晶系拘束。実 PbSO4 CIF で **Rwp 12.30 / GOF 2.49**・セル文献一致 |
| T5 | driver + パーサ (`topas.driver` / `topas.parse`) | ✅ | **終了コードで判定しない** (T0-3)。PATH に home を足す (T0-4)。失敗マーカー行は全部集約 |
| T4 | 装置パラメータ変換 (`topas.instrument`) | 🟡 | `.instprm`/`.PRM` 両対応・データは `.xye` へ。**プロファイル種付けは opt-in のまま** (係数スケール未検証) |
| T6 | 段階フラグ翻訳表 (`topas.flags`) | 🟡 | 13/17 フラグ。未対応は `UnsupportedStageFlagError` で明示的に失敗。残り 4 種は **Issue #173** |
| T8 | TOPAS 段階解放エンジン (`topas.engine`) | ✅ | **実 PbSO4 で Rwp 8.30 / GOF 1.68** (GSAS X 線単独 11.0% 超え) |
| T7 | 段方針の共通化 (`autorietveld.stagepolicy`) | ⏭ | **Issue #175 へ移送**。現状の到達性を損なわないため後続 |
| T10 | バックエンド選択の配線 (①→②) | ✅ | `backend` 引数 + `list_refinement_backends` (MCP_TOOLS 38)。**JSON のみで TOPAS 到達を実測確認** |
| T11 | ③ 手順書 (skill) + 恒久ガード | ✅ | `skills/analyze` に選択規律。ガードは**変異させて fail を実証済** |
| T9 | `backends.topas.TopasBackend` | ⏭ | **Issue #175 へ移送**。`AutoRietveldBackend(runner=)` で代替可能 |
| T12 | 実データ検証 T1–T4 | 🟡 | **T1/T2 実施・未達** (原因切り分け済 → Issue #172)。T3-joint/T4 は Issue #174。結果は `docs/benchmark/m12-topas/README.md` |

## 受け入れ基準

```bash
uv run pytest -m "not gsas and not topas and not agent"   # 外部プログラム非依存 (CI と同じ集合)
uv run pytest -m gsas -k "engine_t1 or engine_t2 or engine_t3 or engine_t4"  # T7 の非回帰
uv run pytest -m topas                                     # 実 tc.exe 経路
uv run ruff check src tests
```

③ からの到達確認 (テスト green ≠ 完了): MCP 経由で `list_refinement_backends` →
`auto_rietveld(backend="topas", ...)` を **JSON 引数だけ**で通し、`result["backend"] == "topas"` と
有限の `final_rwp` を確認する。callable の `runner` を使わずに実行できることが受け入れ条件。

## T12 の合格基準

| # | 系 | GSAS-II 実績 | TOPAS 合格基準 |
|---|---|---|---|
| T1 | fluoroapatite 単相ラボ X 線 | 9.83% | Rwp ≤ 12% |
| T2 | garnet 単相 CW 中性子 (Fe/Al 混合占有) | 4.33% | Rwp ≤ 6.5% + 占有率和 = 1 充足 |
| T3 | PbSO4 X 線 + 中性子 joint | 6.66% | 合計 wR ≤ 8% |
| T4 | NAC+CaF2 TOF + 放射光 多相 | ~12.8% | Rw ≤ 15% |

**両エンジンが同じ格子・同じ相分率に落ちるか**が最重要の観測点。

## 既知の積み残し (T8 時点)

~~座標段が revert される / セル回収未実装 / n_obs が 0~~ → **すべて解消済** (`topas.symmetry` の
サイト対称判定・名前付き `Out()` によるセル回収・`.xye` からの観測点数計上)。

残るもの:

- `cell_esd` / `atom_coords` など**出版値の esd がまだ結果に載っていない**。`Out()` は esd を
  吐けているのでパース側を広げれば埋まる。
- 段階フラグ 4 種未対応 (`tof_profile`/`absorption`/`hydrostatic_strain`/
  `preferred_orientation`)。T12 の T4 (TOF+放射光) に必要。
- プロファイル係数の GSAS↔TOPAS スケール等価が未検証 (`seed_profile` は opt-in のまま)。


## 完了時点のまとめ (2026-07-31)

**動くもの**: 同一の `PhaseSpec`/`HistogramSpec` から `run_topas_rietveld` が
`run_auto_rietveld` と同一契約で回り、③ は **JSON 引数だけ**で
`list_refinement_backends` → `auto_rietveld(backend="topas")` に到達できる (実測確認済)。
実 PbSO4 単独 X 線で **Rwp 7.99% / セル文献一致**。物理妥当性ゲートと出版値 (esd 付き) も配線済み。

**未達**: T1 fluoroapatite 42% / T2 garnet 11.8%。原因は切り分け済 (Issue #172) で、
構造ファイルは忠実 (GSAS に同じ CIF を渡すと 9.80%)、六方/立方晶で相対強度が誤る。

**副産物**: `reference.io` の GSAS STD パーサの既存バグを修正 (固定桁 I2+I6 の空白分割)。
M7 の GSAS 経路は GSAS-II が .raw を直接読むため露見していなかった。

**残タスク**: Issue #172 (相対強度) / #173 (残り 4 フラグ) / #174 (T3-joint/T4) / #175 (TopasBackend + stagepolicy)

## /code-review round 1 の修正 (2026-07-31)

自己レビューで 7 件を検出・修正した。**最も重かったのは「② 経由の `backend="topas"` が GSAS 用
レシピで回っていた」**もので、`build_topas_recipe` を作った意味が ③ から使える唯一の経路で
失われていた (PR 説明の到達確認が出した段列が GSAS 順だったのが証拠)。ほかに `stability` の
無言破棄・`search`/`multistart` 併用時の backend 無視・存在しない引数の ③ への案内・多相での
TCHZ 名衝突・`phase_fractions` 未設定・1:1 テスト欠落 3 本。

**この PR で繰り返した失敗形**: 「エンジンだけ差し替えて周辺 (レシピ・オプション) を
GSAS のまま流す」。同一契約にしたことで**差し替えが効いているように見えてしまう**のが厄介で、
段列やオプションの行き先を実際に確認しないと気づけない。ガードは
`test_topas_backend_uses_the_topas_recipe_not_the_gsas_one` に置き、変異させて fail することを
実証した。


## /code-review round 2-4 (2026-07-31)

round 1 の 7 件を直したあと、**同じクラスの欠陥が 3 巡続けて出た**。すべて
「**joint (複数ヒストグラム) でだけ静かに壊れる**」型である。

| round | 内容 |
|---|---|
| 2 | joint で `scale` の名前が衝突 (round 1 の TCHZ 修正の隣で同じ罠を再導入) / backend 比較が正規化を通っていない |
| 3 | 全生成名を機械的に監査 → `occ`/`beq`/MVW でも衝突。**joint では段階解放も最初から壊れていた** (持ち上げた prm を `!` 無しで宣言) |
| 4 | `out "file"` が xdd ごとに出て 2 本目が 1 本目を切り詰める / joint で構造の出版値が 1 度も出力されない |

**根本原因**: joint 経路は実データ検証 (Issue #174) が無く、テストも単一ヒストグラム中心
だったため、**生成物を目視するまで欠陥が表に出ない**。「同一契約にした」ことが逆に危険で、
単一ヒストグラムで動いていると joint も動いていそうに見えてしまう。

**取った対策**: 個別名を潰すのをやめ、**不変条件**でガードした
(`test_no_parameter_name_is_declared_twice_in_a_joint_document` / `out` 宣言は 1 本 /
構造レコードは 1 回ずつ / Out に重複が無い)。新しい名前や出力を足したときも自動で捕まる。

**残る前提**: joint の**実データ**検証は未実施 (#174)。上記は生成 INP の構造的正しさを
担保するだけで、TOPAS が実際にその INP をどう解釈するかは T3-joint を回すまで未確認である。
