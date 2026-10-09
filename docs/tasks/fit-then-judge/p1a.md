# P1a 作業計画 — engine の部品 (fit-then-judge)

設計: [`docs/design/fit-then-judge/proposal.md`](../../design/fit-then-judge/proposal.md) §6「P1a の部品」。
ブランチ: `milestone/fit-then-judge`。

## 不変条件 (全タスク共通)

- **既定は無効 (opt-in)・既存経路はビット同一**。観測を足すだけの部品も、フィットの数値を 1 ビットも動かさない。
  確認はタスク 0 のゴールデン (gated) と既存の T1 カナリア (`tests/autorietveld/test_engine_t1.py`)。
- **静的に表す**: 部品はすべて `RefinementStage.flags` か `PhaseSpec`/`HistogramSpec` のフィールド、または
  `run_auto_rietveld` の引数で表し、`run_auto_rietveld(recipe=…)` だけで再生できる (P1-1B の静的コンパイルの前提)。
- **(準) hold-out を使わない**: 新しいフィールド・フラグを使うテストは T1/CaTeO3/T3/T4 のデータを参照しない
  (合成データか、範囲外の公開データ)。既存経路の非回帰 (ゴールデン) と、その観測の整合 (revert 理由の記録)
  だけは読んでよい。関数単位の恒久ガード `tests/test_holdout_guard.py` が強制する。
- **①②③ の露出**: `PhaseSpec` のフィールドと段フラグは既存の ② JSON (`phases`/`stages`) で到達できるようにする
  (`from_dict`/`to_dict` と `mcp/_recipe_spec` の検証)。観測フィールドは `_result_to_dict` に載せる。
  ③ の手順書には P1-1B (テンプレート) まで書かない — **非露出の理由**: 単独では使い道が無く、テンプレートが組み合わせて使う部品だから。
  PR 説明に宣言する。
- TDD: 失敗するテスト → 最小実装 → リファクタ。ガード系テストは変異させて落ちることを確かめる。タスク 1 件 green ごとに 1 コミット。

## タスク

| # | タスク | 変更箇所 | テスト | 状態 |
|---|---|---|---|---|
| 0 | **ゴールデン**: 既定経路の指紋 (最終 Rwp/GOF・段列 [label, rwp, gof, n_params, reverted, converged]・格子・座標・esd) を、変更前のコード (abccffb) で採取。環境の指紋 (Python・numpy・BLAS・GSAS-II の版) が一致するときだけビット比較し、違えば skip | `tests/autorietveld/golden/` + gated テスト | T1 単発 (`run_auto_rietveld` 既定) と CaTeO3 frame030 (`make_gsas_runner` 単発) | 済 (7f0b55f) |
| 1 | revert 理由を `StageResult.revert_reason` に (列挙: `worse`/`unconverged`/`non_finite`/`error`/`gate:cell`/`gate:profile`)。no-op は独立の `is_noop` (検査していなければ None)。値は変えない | `autorietveld/model.py`・`engine.py`・`mcp/rietveld_tools._result_to_dict` | 決定論 (段の判定関数) + ゴールデン | 済 (7331e2d) |
| 2 | `PhaseSpec.uiso_equiv_groups` — 原子ラベルの組ごとに Uiso を `add_EquivConstr` で等値にする。混合占有の Uiso 等価と重なる組は**合併**して 1 回だけ張る (二重拘束を避ける) | `model.py`・`engine._setup_constraints` | 決定論 (合併の純関数) + gated (合成 or 範囲外データで等値が効くこと) | 済 (c76fd2b) |
| 3 | `PhaseSpec.fix_polar_origin` — 極性方向 (`SGPolax`) の並進ごとに、最大散乱能で自由座標を持つ原子の座標を固定 (`add_HoldConstr`; [111] 極性は dAx+dAy+dAz=0 の `add_EqnConstr`、(x,x,x) 上の原子は dAx の hold)。**失敗は握りつぶさず例外** (既存の chi2=inf 経路へ) | `engine._setup_constraints` | 決定論 (極性軸 → 拘束式の純関数) + gated | 済 (11d8ca2) |
| 4 | ゼロ点の独立解放 — 段フラグ `zero_offset` と `CORRELATION_GROUPS["zero_offset"]`。`profile_lorentzian` にキー列 (`["X","Y"]`) を許す (既存の `True` は従来どおり X,Y,Zero) | `recipe.py`・`engine._apply_stage`・`mcp/_recipe_spec.py` | 決定論 (フラグ → 解放キー) + ゴールデン | 済 (85082f0 + ff70fb3) |
| 5 | 相ごとの積分計算強度 `phase_integrated_intensity` — 最終状態の反射リストから Σ Fc²·Icorr (列 9/11) | `engine`・`model`・`_result_to_dict` | 決定論 (反射リスト → 和の純関数) + gated | 済 (f54ff2c) |
| 6 | 座標の自由度の照合 `coordinate_freedom_mismatches` — 座標から `SytSym` で再計算した site symmetry と、原子行の site symmetry から `GetCSxinel` で得た自由度が食い違う原子を列挙 | `engine._phase_atom_info` 周辺・`model` | 決定論 (注入した GetCSxinel/SytSym) + gated | 済 (d6f27ec) |
| 7 | 精密化後の構造の書き出し — `run_auto_rietveld(export_cif_dir=…)` で相ごとに GSAS の `export_CIF` | `engine` | gated | 済 (512b51e) |
| 8 | BLAS のスレッド数 — `run_auto_rietveld(blas_threads=…)` で `threadpoolctl.threadpool_limits` を張る。依存に `threadpoolctl` を追加 | `pyproject.toml`・`engine` | 実行時スレッド数の assert | **P1-1B へ移した** (下記) |

## 実施中に見つけて直したもの (P1a の範囲外だが同じ PR で扱う)

| コミット | 内容 |
|---|---|
| 8b5d514 | engine の相仕様の検査 (タスク 2・3) が精密化前に例外を出し **② の境界を越えていた**。`errors.InvalidPhaseSpecError` を新設し、② (`auto_rietveld`/`refine_with_revisions`) は `run(inp)` から出る Tsumugin のドメインエラーだけを error dict に縮退する (論理バグは透過)。GSAS 専用の相機能 (`uiso_equiv_groups`/`fix_polar_origin`) を TOPAS に渡すと黙って何もしないので、`resolve_backend("topas")` の入口で拒否する |
| 51a1a33 | `CorrelationGroupViolation` が ValueError だけを継いでいて、③ が相関群を割る段を渡すと例外が ② の境界を越えていた (既存の欠陥)。ドメインエラーにして縮退させる |
| ff70fb3 | ② の段フラグ語彙に `zero_offset` を足したので、③ の手順書 (`skills/analyze`) に「TOPAS では未対応」と明記 (恒久ガード `tests/test_m12_plugin.py` が検出) |

別作業として切り出したもの (このブランチでは直さない): TOPAS が `refine_cell`・`frozen_coord_labels`・
`free_uiso_labels`・`frozen_uiso_labels`・`occupancy_equiv_groups`・`position_equiv_groups`・`temperature` を
黙って無視する既存の穴 / ② の search・multistart 経路で `save_gpx`・`gpx_dir` が渡らない / Phase B が凍結した
格子・座標まで摂動する。

## タスク 8 を P1-1B へ移した理由

`threadpoolctl` は現在の依存に無い。worktree は main チェックアウトの venv を共有しているので、依存を足すと
他セッションの環境も変わる。BLAS のスレッド固定が要るのはテンプレート手続きの再現性 (NFR-102) であり、
既存経路はゴールデンでビット同一が保たれている。テンプレートを実装する P1-1B で、依存の追加と一緒に入れる。

## 保留 (P1-1B)

相ごとの格子ロールバック・任意段の統計的受理・段ごとのサイクル数・再試行段・保存した gpx から開始して摂動・ledger 永続化の ② 配線・BLAS のスレッド固定 (旧タスク 8)。

## セルフレビュー 1 巡目 (読み取り専用のレビューエージェント。HIGH 0 / MEDIUM 8 / LOW 12)

| 指摘 | 対応 |
|---|---|
| M1 測っていない値を「正常」と返す (no-op 未検査で `false`、TOPAS の観測が `{}`) | `is_noop` は未検査なら None → ② は null。理由を記録しない revert は `"unrecorded"`。観測フィールドは未計測なら None → null |
| M2 `zero_offset: false`/`profile_lorentzian: false` で解放される | engine を値の真偽で判定 |
| M3 TOPAS が `profile_lorentzian` のキー列を x,y の解放と読む | TOPAS の入口でキー列を拒否 (`UnsupportedStageFlagError`)、手順書に明記 |
| M4 系列の ② ツールで新しいドメインエラーが境界を越える | `degrade_domain_errors` を `sequential_rietveld`/`anchored_sequential`/`repair_frames` に。※ MCP の実際の境界 (`server._call_tool`) は元から全例外を縮退しているので、③ に例外が届く欠陥ではなかった |
| M5 静的に分かる Uiso の組の割れが毎段の revert に溶ける | free/frozen で割れる組・未知ラベル・2 原子未満の組は精密化前に `InvalidPhaseSpecError`。混合占有の組の未知ラベルは既存経路と同じく無視。段の例外の文言を note に載せる |
| M6 極性原点の固定と元素ランクの座標段の衝突 | 組み合わせを精密化前に拒否 (段ごとの拘束の入れ替えは P1-1B) |
| M7 `freeze_others` で Zero だけ残せない | 残す名前に `zero_offset` を追加、② で名前の語彙を閉じる (`scale`/`background` は元々凍結されないので無害な名前として許容) |
| M8 CIF 書き出しの失敗がフィットを落とす | ディレクトリ作成も失敗を記録して続行、一時ファイルに書いてから改名 |
| L2 積分強度の想定外の形・空の反射リスト | 読めなければ None、空は未計算として None |
| L3 docstring の「1/V²」 | 「体積の補正 (Vst)」に訂正 |
| L4 極性原点で site symmetry を解釈できない原子を例外にしていた | engine と同じく凍結された原子 (= 原点を決めている) として扱う |
| L5 座標の自由度の比較が係数を見ていない | 番号の並びと係数の両方を比べる |
| L6 1 原子・空の組を黙って受理 | M5 と同じく精密化前に拒否 |
| L10 弱い比較・誤ったコメント | 修正 |
| L11 ゴールデン (準 hold-out) で新しい観測を検査していた / hold-out のガード未実装 | 新しい観測の検査は garnet へ移した。関数単位のガードを実装 |
| L12 文書の語彙が実装と食い違う | 修正 |

**見送った指摘 (理由)**:

- **L1** `run_topas_rietveld` を直接呼ぶと GSAS 専用の相機能が素通りする: TOPAS 本体は別作業 (PR #229, TOPAS が
  相の機能を一括分類して入口で拒否する仕組み) の範囲。#229 の後で `uiso_equiv_groups`/`fix_polar_origin` を「拒否」に分類する。
- **L7** 論理バグを関数レベルで透過させるテストが「② は例外を送出しない」と衝突する: MCP の実際の境界
  (`server._call_tool`) は全例外を縮退しており、関数レベルで論理バグを透過させるのは既存の `degrade_oserror` と同じ
  方針 (握り潰すと不具合が入力の誤りに見える)。衝突しない。
- **L8** 最終段が revert されると `export_CIF` の従属パラメータの esd が古い拘束構造から計算されうる: 推測で未確認。
  書き出した CIF は P1-1A の結晶化学検査器の入力 (esd は使わない) なので、出版に使う前に P1-1A で確かめる。
- ~~**L9** 極性原点の固定と Phase B の摂動: 既存の欠陥と同じ根~~ → **2 巡目で撤回**: hold した原子は
  `frozen_coord_labels` に入らないので別作業では直らない。摂動は原点固定より先に掛かるので、極性方向へずれた解に
  なる。設計 §4.5 の対応 (hold した座標を摂動しない・並進を除いて比べる) が入る P1-1B までは、原点固定の相への
  座標の摂動を精密化前に拒否する。

## セルフレビュー 2 巡目 (HIGH 0 / MEDIUM 1 / LOW 5。1 巡目の 18 件は 15 解消・3 部分的)

| 指摘 | 対応 |
|---|---|
| N1 MEDIUM hold-out ガードの抜け道 (補助関数・fixture・import・型注釈付き定数・デコレータ・分割したパス) | 参照を推移的に辿る形に強化し、抜け道 7 種を自己テストで固定 |
| N6 ガードのトークンが hold-out より広い (T3 中性子単独・T4 TOF も弾く) | T3/T4 はヒストグラムのファイル名で照合 (T1・CaTeO3 はディレクトリ全体) |
| N3 手順書の「段が失敗する」は実装と違う (呼び出し全体が拒否される) | 記述を訂正 |
| N4 `refine_with_revisions` の `ReleaseParams` が段フラグの検証を迂回する (既存の抜け道) | ② で `stages` と同じ検証を通す |
| N5 recipe.py の docstring が古い | 訂正 |
| L2 の残り (項目が dict でない・RefList がスカラー) | 項目の扱い全体を try の中へ |
| L8 への意見 (CIF は P1-1A の外へも持ち出される) | `export_cif_dir` の docstring に従属パラメータの esd を保証しない旨を明記 |
| L9 への反論 | 上記のとおり撤回し、原点固定の相への座標の摂動を拒否 |
| N2 TOPAS の `StageResult` が既に持っている判定 (`is_noop`/`reason`) を渡していない | **見送り**: TOPAS 本体は PR #229 が変更中。#229 のマージ後に main を取り込むとき直す |

変異 3 個 (L9・N4・ガードの推移的な辿り) をすべて検出。
