# P1a 作業計画 — engine の部品 (fit-then-judge)

設計: [`docs/design/fit-then-judge/proposal.md`](../../design/fit-then-judge/proposal.md) §6「P1a の部品」。
ブランチ: `milestone/fit-then-judge`。

## 不変条件 (全タスク共通)

- **既定は無効 (opt-in)・既存経路はビット同一**。観測を足すだけの部品も、フィットの数値を 1 ビットも動かさない。
  確認はタスク 0 のゴールデン (gated) と既存の T1 カナリア (`tests/autorietveld/test_engine_t1.py`)。
- **静的に表す**: 部品はすべて `RefinementStage.flags` か `PhaseSpec`/`HistogramSpec` のフィールド、または
  `run_auto_rietveld` の引数で表し、`run_auto_rietveld(recipe=…)` だけで再生できる (P1-1B の静的コンパイルの前提)。
- **(準) hold-out を使わない**: 新しいフィールド・フラグを使うテストは T1/CaTeO3/T3/T4 のデータを参照しない
  (合成データか、範囲外の公開データ)。既存経路の非回帰 (ゴールデン) だけは読んでよい。
- **①②③ の露出**: `PhaseSpec` のフィールドと段フラグは既存の ② JSON (`phases`/`stages`) で到達できるようにする
  (`from_dict`/`to_dict` と `mcp/_recipe_spec` の検証)。観測フィールドは `_result_to_dict` に載せる。
  ③ の手順書には P1-1B (テンプレート) まで書かない — **非露出の理由**: 単独では使い道が無く、テンプレートが組み合わせて使う部品だから。
  PR 説明に宣言する。
- TDD: 失敗するテスト → 最小実装 → リファクタ。ガード系テストは変異させて落ちることを確かめる。タスク 1 件 green ごとに 1 コミット。

## タスク

| # | タスク | 変更箇所 | テスト | 状態 |
|---|---|---|---|---|
| 0 | **ゴールデン**: 既定経路の指紋 (最終 Rwp/GOF・段列 [label, rwp, gof, n_params, reverted, converged]・格子・座標・esd) を、変更前のコード (abccffb) で採取。環境の指紋 (Python・numpy・BLAS・GSAS-II の版) が一致するときだけビット比較し、違えば skip | `tests/autorietveld/golden/` + gated テスト | T1 単発 (`run_auto_rietveld` 既定) と CaTeO3 frame030 (`make_gsas_runner` 単発) | |
| 1 | revert 理由を `StageResult.revert_reason` に (列挙: `worse`/`non_finite`/`error`/`gate:<名前>`/`noop`)。値は変えない | `autorietveld/model.py`・`engine.py`・`mcp/rietveld_tools._result_to_dict` | 決定論 (段の判定関数) + ゴールデン | |
| 2 | `PhaseSpec.uiso_equiv_groups` — 原子ラベルの組ごとに Uiso を `add_EquivConstr` で等値にする。混合占有の Uiso 等価と重なる組は**合併**して 1 回だけ張る (二重拘束を避ける) | `model.py`・`engine._setup_constraints` | 決定論 (合併の純関数) + gated (合成 or 範囲外データで等値が効くこと) | |
| 3 | `PhaseSpec.fix_polar_origin` — 極性方向 (`SGPolax`) の並進ごとに、最大散乱能で自由座標を持つ原子の座標を固定 (`add_HoldConstr`; [111] 極性は dAx+dAy+dAz=0 の `add_EqnConstr`、(x,x,x) 上の原子は dAx の hold)。**失敗は握りつぶさず例外** (既存の chi2=inf 経路へ) | `engine._setup_constraints` | 決定論 (極性軸 → 拘束式の純関数) + gated | |
| 4 | ゼロ点の独立解放 — 段フラグ `zero_offset` と `CORRELATION_GROUPS["zero_offset"]`。`profile_lorentzian` にキー列 (`["X","Y"]`) を許す (既存の `True` は従来どおり X,Y,Zero) | `recipe.py`・`engine._apply_stage`・`mcp/_recipe_spec.py` | 決定論 (フラグ → 解放キー) + ゴールデン | |
| 5 | 相ごとの積分計算強度 `phase_integrated_intensity` — 最終状態の反射リストから Σ Fc²·Icorr (列 9/11) | `engine`・`model`・`_result_to_dict` | 決定論 (反射リスト → 和の純関数) + gated | |
| 6 | 座標の自由度の照合 `coordinate_freedom_mismatches` — 座標から `SytSym` で再計算した site symmetry と、原子行の site symmetry から `GetCSxinel` で得た自由度が食い違う原子を列挙 | `engine._phase_atom_info` 周辺・`model` | 決定論 (注入した GetCSxinel/SytSym) + gated | |
| 7 | 精密化後の構造の書き出し — `run_auto_rietveld(export_cif_dir=…)` で相ごとに GSAS の `export_CIF` | `engine` | gated | |
| 8 | BLAS のスレッド数 — `run_auto_rietveld(blas_threads=…)` で `threadpoolctl.threadpool_limits` を張る。依存に `threadpoolctl` を追加 | `pyproject.toml`・`engine` | 実行時スレッド数の assert | |

## 保留 (P1-1B)

相ごとの格子ロールバック・任意段の統計的受理・段ごとのサイクル数・再試行段・保存した gpx から開始して摂動・ledger 永続化の ② 配線。
