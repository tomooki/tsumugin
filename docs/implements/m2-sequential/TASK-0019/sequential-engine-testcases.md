# TASK-0019 TDD テストケース — SequentialEngine (オンライン逐次精密化 + 局所木探索)

**要件名**: m2-sequential / **タスクID**: TASK-0019 / **機能名 (英)**: sequential-engine
**対象実装**: `src/tsumugin/sequential/engine.py` (新規) / **テスト**: `tests/test_sequential_engine.py` (新規)
**作成日**: 2026-07-03
**参照**: `docs/implements/m2-sequential/TASK-0019/note.md` /
`docs/implements/m2-sequential/TASK-0019/sequential-engine-requirements.md` /
`docs/tasks/m2-sequential/TASK-0019.md` (完了条件 9 項目) /
`docs/spec/m2-sequential/acceptance-criteria.md` (TC-101/102/108-03)

> テストダブルの範: `tests/test_tree_search.py` の `FakeBackend`(固定 rwp/chi2 スタブ + refine_calls) /
> `RecordingSpyBackend`(SimulatedBackend 委譲 + (free_params,max_cycles) 記録)。合成グリッドは小さく
> (`np.arange(15.0,60.0,0.02)` 程度)。決定論検証は `==`、物理量近似は `pytest.approx`、非有限は `math.isfinite`。

---

## テストケース一覧 (計 18 件)

| ID | 分類 | 概要 | 完了条件 / AC | 信頼性 |
|---|---|---|---|---|
| SE-N01 | 正常 | 線形膨張 20 フレームで格子が真値 ±0.01 追跡 | ①/TC-101-01 | 🔵 |
| SE-N02 | 正常 | warm start 継承 (spy): フレーム i 入力 == i−1 出力 | ①/TC-101-02 | 🔵 |
| SE-N03 | 正常 | 相 B 出現シーケンスで当該近傍が changepoint 判定 | ②/TC-102-01 | 🔵 |
| SE-N04 | 正常 | 局所探索が B 採択 → 以後 B 込みで継続 | ②/TC-102-03 | 🔵 |
| SE-N05 | 正常 | 木探索は changepoint フレームのみ (spy 呼び出し回数) | ③/TC-102-02 | 🔵 |
| SE-N06 | 正常 | Trajectory 組立の完全性 (行数=フレーム数/lifecycles/frame_range) | ②⑥ | 🔵🟡 |
| SE-N07 | 正常 | SequentialResult 構造と ledger adopt/reject 記録 | ②/D3 | 🔵🟡 |
| SE-E01 | 異常 | 空 series → 空 Trajectory・例外なし | ④/TC-101-05/EDGE-001 | 🔵 |
| SE-E02 | 異常 | 失敗フレーム (chi2=inf) 継続 + 警告 + 直近成功 warm start | ④/TC-101-07/EDGE-002 | 🟡 |
| SE-E03 | 異常 | orchestration="native" → NotImplementedError | ⑦/REQ-105 | 🔵 |
| SE-E04 | 異常 | 全フレーム changepoint でも完走 | ⑧/TC-102-05/EDGE-103 | 🟡 |
| SE-B01 | 境界 | 単一フレーム → 長さ 1 の Trajectory | ④/TC-101-06/EDGE-101 | 🔵 |
| SE-B02 | 境界 | 決定論: 2 回実行で全出力ビット同一 | ⑤/TC-101-04 | 🔵 |
| SE-B03 | 境界 | inherit="lattice_only" が機能する | ⑥/TC-101-03 | 🟡 |
| SE-B04 | 境界 | 100 フレーム (changepoint なし) が 60 秒以内 (smoke) | ⑨/TC-108-03 | 🟡 |
| SE-B05 | 境界 | PersistentLedger/Store 注入で M2 経路が無改変で動く | 追加/TC-106-06 相当 | 🔵 |
| SE-B06 | 境界 | changepoint 非発火 (滑らか) で木探索ゼロ・search_results 空 | ③/TC-102-04 | 🔵 |
| SE-B07 | 境界 | evidence 非改善時は現行構成を維持し reject 記録 | ②/D3 | 🟡 |

---

## 1. 正常系テストケース

### SE-N01: 線形膨張 20 フレームで格子が真値 ±0.01 Å を追跡
- **何をテストするか**: 格子 a が線形膨張する合成 20 フレーム列に対し `run()` が各フレームを逐次精密化し、
  精密化格子が真値を追跡すること。
- **期待される動作**: `trajectory.records` 各フレームの主相格子 a が対応フレームの真値 ±0.01 Å。
- **入力値**: `SimulatedBackend(peak_fwhm=0.2)`。真値 a を `a0=5.0` から `a0+0.01*i` で線形膨張させた
  合成強度行列 `(20, n_points)`。`initial_phases=[PhaseInstance("A", LatticeParams(5.0,5.0,5.0))]`。
  - **入力データの意味**: 熱膨張の代表。warm start による追従性能を測る最小構成 (相構成不変・changepoint なし)。
- **期待される結果**: 各 `record.phases[0].lattice.a == pytest.approx(真値_i, abs=0.01)`、`records` 長 == 20。
  - **期待結果の理由**: REQ-001/002 の warm start 逐次精密化が滑らかなトレンドを追従できることの直接検証。
- **確認ポイント**: 全 20 フレームで追跡誤差が閾値内。`refine_failed` が全 False。非有限が漏れない。
- 🔵 (完了条件① / TC-101-01 / REQ-001 に直接依拠)

### SE-N02: warm start 継承の検証 (spy backend)
- **何をテストするか**: フレーム i の精密化入力 phases がフレーム i−1 の出力 phases に一致すること。
- **期待される動作**: `RecordingSpyBackend` (または refine 入力を記録する spy) でフレーム i の
  `RefinementModel.phases` の格子/scale が i−1 の結果と一致。
- **入力値**: SE-N01 と同じ線形膨張シーケンス。spy backend で各 `refine` の入力 phases を記録。
  - **入力データの意味**: 継承経路の観測。数値追従 (N01) と別に「入力=前フレーム出力」の契約を明示検証。
- **期待される結果**: 各 i>=2 で `refine_input_phases[i]` の格子 == `record.phases[i-1]` の格子 (`==` またはビット比較)。
  frame 1 の入力は frame 0 (staged) の `final_phases`。
- **確認ポイント**: staged (frame0) → direct refine (frame1) の継承境界も含む。継承対象は `inherit="phases"` 既定。
- 🔵 (完了条件① / TC-101-02 に直接依拠。spy パターンは test_tree_search.py 踏襲)

### SE-N03: 相 B 出現シーケンスで changepoint 判定
- **何をテストするか**: 中間フレーム (例 frame 10) から相 B のピークが出現する合成シーケンスで、
  当該フレーム近傍が changepoint 判定されること。
- **期待される動作**: `trajectory.records` の frame 10 近傍で `record.changepoint == True`、
  `changepoint_reasons` に "new_peaks" 等が含まれる。`search_results` に該当 frame_index キーが存在。
- **入力値**: frame 0-9 は相 A のみ、frame 10 以降は A+B の合成強度。候補プール `candidates=[PhaseCandidate(B), ...]`。
  - **入力データの意味**: 相転移・新相析出の代表。複合指標 (新規未マッチピーク) の発火を測る。
- **期待される結果**: changepoint フラグが frame 10 近傍で立つ (warm-up window=5 を過ぎている)。
- **確認ポイント**: warm-up 期間 (履歴 < window) では非発火。発火フレームが 1 つ以上存在。
- 🔵 (完了条件② / TC-102-01 / REQ-003/101 に依拠)

### SE-N04: 局所探索が新相 B を採択し以後 B 込みで継続
- **何をテストするか**: changepoint フレームの `HypothesisTreeSearch` が B 込み仮説を採択し、以降のフレームの
  相構成が B を含むこと。
- **期待される動作**: 採択後のフレーム (frame 10 以降) の `record.phases` に phase_ref "B" が含まれる。
  `hypotheses` に採択仮説が `frame_range` 付きで登録され、B の相集合を持つ。
- **入力値**: SE-N03 と同じ。evidence は既定 BIC。B を含む構成が evidence 改善するよう合成 (A+B が真値)。
  - **入力データの意味**: D3 の「evidence 改善時のみ採択→継続」経路の代表。
- **期待される結果**: 採択フレーム以降で B が相集合に恒常的に含まれる。`ledger` に kind="adopt" 相当のエントリ。
- **確認ポイント**: 採択が一度きりで以後は warm start で B 込み継続 (再探索は次の changepoint まで起きない)。
- 🔵 (完了条件② / TC-102-03 / D3 に依拠)

### SE-N05: 木探索は changepoint フレームでのみ呼ばれる
- **何をテストするか**: `HypothesisTreeSearch.search` の呼び出し回数が changepoint 発火フレーム数と一致すること。
- **期待される動作**: search 呼び出し回数 == `sum(record.changepoint for record in records)` == `len(search_results)`。
- **入力値**: SE-N03 のシーケンス。`HypothesisTreeSearch` をラップした spy か search 呼び出しカウンタで観測。
  - **入力データの意味**: 局所起動の計算量制御 (P5) の核。非 changepoint フレームで無駄に探索しないことを保証。
- **期待される結果**: 呼び出し回数がフレーム総数より十分小さく、changepoint フレーム数と厳密一致。EDGE-104 含む。
- **確認ポイント**: 非 changepoint フレームで search が 0 回。空 changepoint シーケンスでは 0 回。
- 🔵 (完了条件③ / TC-102-02 / EDGE-104 に直接依拠。spy 観測)

### SE-N06: Trajectory 組立の完全性
- **何をテストするか**: `trajectory.records` の行数 = フレーム数、各 FrameRecord のフィールド充足、
  `trajectory.lifecycles` が LifecycleTracker.finalize 由来で埋まること。
- **期待される動作**: `len(records) == series.n_frames`。changepoint フレームは `changepoint=True`。
  相 B が出現・確定した場合 `lifecycles["B"].birth_frame` が確定 (ヒステリシス考慮)。
- **入力値**: SE-N03/N04 のシーケンス。
  - **入力データの意味**: FR-306 の出力契約 (dataflow「行数=フレーム数」データ整合性) の検証。
- **期待される結果**: 行数一致、lifecycles キーに確定相が存在、`axis_value`/`temperature` が channels 由来で反映。
- **確認ポイント**: 失敗フレームも 1 行 (None 値入り) 存在。`Hypothesis.frame_range` が採択区間 [start,end] を保持。
- 🔵🟡 (完了条件②⑥ / FR-306 / dataflow データ整合性。lifecycle 反映の詳細は 🟡)

### SE-N07: SequentialResult 構造と ledger 記録
- **何をテストするか**: `SequentialResult` の各フィールドが契約通り構築され、採択/棄却が理由付き ledger 記録されること。
- **期待される動作**: `first_frame_report` は非 None (`first_frame_staged=True`)、`search_results` は
  frame_index をキーとする Mapping、`ledger.entries` に adopt/reject 相当のエントリが含まれる。
- **入力値**: SE-N03/N04 のシーケンス。
  - **入力データの意味**: interfaces.py L224-234 の出力契約の網羅検証。
- **期待される結果**: `search_results` の全キーが changepoint フレーム、`hypotheses` 非空、`warnings` は tuple。
- **確認ポイント**: ledger/snapshots が返却実体 (検証可能)。決定論のため ID 採番が入力順非依存。
- 🔵🟡 (完了条件② / D3 / interfaces.py に依拠。ledger kind 名は 🟡)

## 2. 異常系テストケース

### SE-E01: 空フレーム列 → 空 Trajectory・例外なし
- **エラーケースの概要**: `series.n_frames == 0` (空強度行列) を渡した場合。
- **エラー処理の重要性**: 上流の空入力で例外を投げず安全側に縮退する契約 (EDGE-001)。
- **入力値**: `FrameSeries(two_theta, intensities=np.empty((0, n_points)))`, `initial_phases=[...]`。
  - **不正な理由**: 精密化対象フレームが 0 件。staged 確立の入力すら無い。
  - **実際の発生シナリオ**: 測定データ未取得・フィルタ後に全フレーム除外された場合。
- **期待される結果**: `SequentialResult` を返し、`trajectory.records == ()`、`trajectory.lifecycles == {}`、
  `first_frame_report is None`、`search_results == {}`。例外は送出しない。
  - **システムの安全性**: 空でも実体を返すため下流 (CSV 出力等) が破綻しない。
- **確認ポイント**: 例外を投げないこと。全コレクションが空値へ縮退。
- 🔵 (完了条件④ / TC-101-05 / EDGE-001 に直接依拠)

### SE-E02: 失敗フレーム継続 (chi2=inf) + 警告 + 直近成功 warm start
- **エラーケースの概要**: 中間フレームで `backend.refine` が `chi2=inf`/`converged=False` を返す場合。
- **エラー処理の重要性**: 単一フレームの精密化失敗で全系列を止めず、直近成功フレームから継続する (EDGE-002/M1 教訓)。
- **入力値**: `FakeBackend` で特定フレーム (例 frame 7) の組合せに `chi2=inf` を注入。他は正常。
  - **不正な理由**: 発散・非収束。非有限を下流に伝播させてはならない。
  - **実際の発生シナリオ**: ノイズフレーム・一時的な測定不良。
- **期待される結果**: 該当 `record.refine_failed == True`、`record.rwp is None`、`record.chi2 is None`、
  `warnings` に警告文字列が追加。**次フレームの warm start は失敗フレームでなく直近成功フレームの phases** を使用。
  - **システムの安全性**: 非有限が FrameRecord/CSV に漏れない (`math.isfinite` で検証)。
- **確認ポイント**: 失敗フレームも 1 行存在 (行数=フレーム数を維持)。継続後のフレームが正常に精密化される。
- 🟡 (完了条件④ / TC-101-07 / EDGE-002。warm start 詳細は 🟡)

### SE-E03: orchestration="native" → NotImplementedError
- **エラーケースの概要**: `SequentialConfig(orchestration="native")` で `run()` を呼ぶ。
- **エラー処理の重要性**: native 協調精密化は M-later スコープ。誤動作でなく明示的に未実装を通知 (REQ-105/FR-302)。
- **入力値**: `SequentialConfig(orchestration="native")`、任意の有効な series。
  - **不正な理由**: 未実装のオーケストレーションモード。
  - **実際の発生シナリオ**: 将来機能を先取りした設定ミス。
- **期待される結果**: `run()` が `NotImplementedError` を送出 (`pytest.raises(NotImplementedError)`)。
  - **エラーメッセージの内容**: native 未対応である旨。
- **確認ポイント**: `run()` 冒頭で早期に送出し、副作用 (ファイル書き込み等) を起こさない。
- 🔵 (完了条件⑦ / REQ-105 / FR-302 に直接依拠)

### SE-E04: 全フレーム changepoint でも完走
- **エラーケースの概要**: 全フレームで changepoint が発火する極端なシーケンス (毎フレーム局所探索起動)。
- **エラー処理の重要性**: 高頻度探索でも例外なく Trajectory を返し完走する堅牢性 (EDGE-103)。
- **入力値**: フレーム毎に相構成/格子が大きく跳ねる合成シーケンス (warm-up 後は毎フレーム発火)。
  - **不正な理由**: 通常想定を超える異常な変化率 (実質「常時変化」)。
  - **実際の発生シナリオ**: 非常に高速なその場反応・不安定系。
- **期待される結果**: 例外なく完走。`len(search_results)` が warm-up 後の全フレーム数に一致。`records` 長=フレーム数。
  - **システムの安全性**: 探索連発でもメモリ/状態が破綻しない。
- **確認ポイント**: 完走することが主眼 (結果の物理的正しさは問わない)。決定論は維持。
- 🟡 (完了条件⑧ / TC-102-05 / EDGE-103。「全発火」合成の作り込みは 🟡)

## 3. 境界値テストケース

### SE-B01: 単一フレーム → 長さ 1 の Trajectory
- **境界値の意味**: フレーム数の最小非空境界 (n_frames=1)。frame 0 の staged 確立のみが走る。
- **入力値**: `intensities` が `(1, n_points)`。`initial_phases=[...]`。
  - **境界値選択の根拠**: 「後続フレーム無し」の境界。warm start 経路も changepoint も発火しない最小系。
- **期待される結果**: `len(records) == 1`、`first_frame_report is not None`、`search_results == {}`
  (単一フレームでは warm-up により changepoint 非発火)。
  - **境界での正確性**: staged 確立結果が 1 行の FrameRecord に正しく写像される。
- **確認ポイント**: 空 (n=0) と 2 フレーム以上の中間として一貫した振る舞い。
- 🔵 (完了条件④ / TC-101-06 / EDGE-101 に直接依拠)

### SE-B02: 決定論 — 2 回実行で全出力ビット同一
- **境界値の意味**: 決定論の要 (NFR-102/REQ-402)。同一入力の再現性境界。
- **入力値**: SE-N03/N04 と同じシーケンスで `run()` を 2 回実行 (新規エンジン同士、または同一設定)。
  - **境界値選択の根拠**: changepoint・局所探索・採択を含む複雑経路でも決定論が崩れないことを確認。
- **期待される結果**: `records` (FrameRecord tuple) が `==` でビット同一、`hypotheses` の ID/相/metrics 一致、
  `search_results` のキー・内容一致、`ledger.entries` の hash 列一致。
  - **一貫した動作**: 乱数なし・安定ソート・dict 反復順非依存が全経路で守られる。
- **確認ポイント**: `pytest.approx` を使わず `==` で比較。ID 採番・frame_index キー順も一致。
- 🔵 (完了条件⑤ / TC-101-04 / REQ-402 に直接依拠)

### SE-B03: inherit="lattice_only" が機能する
- **境界値の意味**: 継承対象設定の分岐境界 (`"phases"` vs `"lattice_only"`)。
- **入力値**: `SequentialConfig(inherit="lattice_only")`。SE-N01 相当の線形膨張シーケンス。
  - **境界値選択の根拠**: warm start の継承粒度を切り替えたときの分岐動作を確認。
- **期待される結果**: 後続フレームの初期値が前フレームの**格子のみ**を継承 (scale 等はリセット/初期値)。
  格子追跡は依然として真値近傍 (追従性が保たれる)。`inherit="phases"` と結果が区別できる。
  - **境界での正確性**: 継承対象の切替が精密化入力に正しく反映される。
- **確認ポイント**: spy で refine 入力 phases を観測し、格子は継承・scale は非継承であることを確認。
- 🟡 (完了条件⑥ / TC-101-03。lattice_only セマンティクス詳細は 🟡)

### SE-B04: 100 フレーム (changepoint なし) が 60 秒以内 (smoke)
- **境界値の意味**: 性能境界 (NFR-001/REQ-403)。実用規模の最小担保。
- **入力値**: 滑らかな線形膨張の合成 100 フレーム (changepoint 非発火)。小グリッド (15-60°, step 0.02 前後)。
  - **境界値選択の根拠**: 後続フレーム direct refine が支配的な現実的規模。
- **期待される結果**: `run()` が 60 秒以内に完了 (`time.perf_counter` 計測)。`len(records) == 100`。
  - **堅牢性の確認**: direct refine (~7 パラメータ × ≤10 cycles) が線形にスケールする。
- **確認ポイント**: changepoint を発火させない (局所探索コスト混入を避ける)。CI 変動を考慮した閾値。
  必要なら `@pytest.mark.slow` 等でマークし通常実行と分離検討。
- 🟡 (完了条件⑨ / TC-108-03 / NFR-001。閾値・マーク方針は 🟡)

### SE-B05: PersistentLedger/Store 注入で M2 経路が無改変で動く
- **境界値の意味**: 注入境界 (REQ-012)。in-memory 版と Persistent 版の契約互換性。
- **入力値**: `tmp_path` の JSONL パスで `PersistentLedger(path)` / `PersistentSnapshotStore(path, ledger)` を構築し
  `SequentialEngine(..., ledger=pl, snapshots=ps)` に注入。SE-N01 相当のシーケンス。
  - **境界値選択の根拠**: 台帳/スナップショットを差し替えても逐次解析が同一意味論で動くこと (TC-106-06 相当)。
- **期待される結果**: `run()` 完走。実行後 `pl.verify() == True`、JSONL ファイルにエントリが追記され再オープンで verify True。
  結果 (trajectory 等) は in-memory 版注入時と等価。
  - **一貫した動作**: append のみで成長 (削除・上書きなし)。
- **確認ポイント**: engine と下位エンジン (staged/tree) が同一 ledger インスタンスを共有して追記する。
- 🔵 (追加/TC-106-06 相当 / REQ-012。note.md 注意事項「Persistent 版で 1 本」に依拠)

### SE-B06: changepoint 非発火 (滑らか) で木探索ゼロ・search_results 空
- **境界値の意味**: changepoint ゼロ境界 (TC-102-04)。変化のないシーケンスの下限挙動。
- **入力値**: 相構成不変・滑らかな線形膨張シーケンス (SE-N01 相当)。
  - **境界値選択の根拠**: 発火閾値を一度も超えないケースで探索が完全に抑制されることを確認。
- **期待される結果**: 全 `record.changepoint == False`、`search_results == {}`、search 呼び出し回数 0。
  - **境界での正確性**: warm-up 縮退 + 滑らかトレンドの非発火 (格子差分の robust z が閾値未満)。
- **確認ポイント**: SE-N05 の対極 (発火ゼロ)。線形膨張が誤発火しないこと (changepoint.py の差分ベース判定に依拠)。
- 🔵 (完了条件③ 補完 / TC-102-04 に依拠)

### SE-B07: evidence 非改善時は現行構成を維持し reject 記録
- **境界値の意味**: 採択判定の境界 (D3)。changepoint は発火するが新構成が evidence 改善しないケース。
- **入力値**: changepoint が発火するが、局所探索の最良仮説が現行相と同集合 or evidence 非改善となる合成
  (`FakeBackend` で現行構成の方が良い rwp/chi2 を返すよう制御)。
  - **境界値選択の根拠**: 「evidence 改善時のみ採択」の否定側 (境界=非改善) を検証。
- **期待される結果**: 相構成が変化せず現行を維持。`ledger` に kind="reject" 相当のエントリ。`search_results[i]` は
  記録されるが採択は起きない (`hypotheses` に新採択 frame_range が増えない)。
  - **一貫した動作**: 境界 (evidence 同値) は非改善扱いで現行維持。
- **確認ポイント**: 棄却も理由付き ledger 記録 (説明可能性)。現行相の継続性が保たれる。
- 🟡 (完了条件② / D3。evidence 同値=非改善の境界解釈は 🟡)

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12 🔵
  - **言語選択の理由**: 既存コードベース (src layout + uv + hatchling) が Python。frozen dataclass + Protocol 前提。
  - **テストに適した機能**: dataclass の `==` 比較 (決定論ビット同一検証)、`math.isfinite` (非有限漏洩検証)。
- **テストフレームワーク**: pytest (`uv run pytest`) 🔵
  - **フレームワーク選択の理由**: 既存テスト (test_tree_search.py 等) が pytest。`pytest.approx`/`pytest.raises`/`tmp_path` を活用。
  - **テスト実行環境**: `pyproject.toml` の `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `addopts="-q"`)。
    `tests/conftest.py` は gsas マーカー skip のみ (本タスクは GSAS 非依存)。
- 🔵 (note.md §5 テスト関連情報に依拠)

## 5. テストケース実装時の日本語コメント指針

`tests/test_sequential_engine.py` は下記スタイルを踏襲する (test_tree_search.py / test_changepoint.py の範):

```python
def test_linear_expansion_tracks_true_lattice():
    # 【テスト目的】: 線形膨張 20 フレームで精密化格子が真値 ±0.01 Å を追跡することを確認 (SE-N01/TC-101-01)
    # 【テスト内容】: SimulatedBackend の膨張シーケンスに対する SequentialEngine.run() の逐次追従
    # 【期待される動作】: 各 record.phases[0].lattice.a == approx(真値_i, abs=0.01)
    # 🔵 信頼性レベル: 完了条件① / TC-101-01 / REQ-001 に直接依拠

    # 【テストデータ準備】: a0=5.0 から 0.01*i で線形膨張させた (20, n_points) 強度行列
    # 【初期条件設定】: 単一相 A・相構成不変 (changepoint なし)・候補プール空
    backend = SimulatedBackend(peak_fwhm=0.2)
    series = _make_expansion_series(a0=5.0, delta=0.01, n_frames=20)

    # 【実際の処理実行】: frame0 staged 確立 → 後続 warm start direct refine のフルパス
    result = SequentialEngine(backend).run(series, [_phase(5.0, "A")])

    # 【結果検証】: 各フレームの主相格子が真値近傍を追跡
    assert len(result.trajectory.records) == 20  # 【確認内容】: 行数=フレーム数 🔵
    for i, rec in enumerate(result.trajectory.records):
        # 【検証項目】: フレーム i の格子 a が真値 ±0.01 🔵
        assert rec.phases[0].lattice.a == pytest.approx(5.0 + 0.01 * i, abs=0.01)
```

- **決定論テスト (SE-B02)** は `==` でビット同一を検証し `pytest.approx` を使わない。
- **非有限漏洩 (SE-E02)** は `math.isfinite` / `is None` で検証。
- **例外 (SE-E03)** は `pytest.raises(NotImplementedError)`。
- **spy 観測 (SE-N02/N05/B03)** は test_tree_search.py の `RecordingSpyBackend` / `FakeBackend.refine_calls` 相当を用いる。
- **永続化 (SE-B05)** は `tmp_path` フィクスチャで JSONL パスを与える。

## 6. 要件定義との対応関係

- **参照した機能概要**: `sequential-engine-requirements.md` §1 (オンライン単一パス / D1-D3)
- **参照した入力・出力仕様**: 同 §2 (SequentialConfig/SequentialResult/SequentialEngine, データフロー)
- **参照した制約条件**: 同 §3 (決定論/非有限/後方互換/注入/native 未実装/性能)
- **参照した使用例**: 同 §4 (線形膨張/相 B 出現/空・単一・失敗継続/全 changepoint/性能 smoke)
- **完了条件との対応**: `docs/tasks/m2-sequential/TASK-0019.md` 9 項目を SE-N01〜SE-B07 に 1:N マッピング (上表)
- **受け入れ基準との対応**: `docs/spec/m2-sequential/acceptance-criteria.md` TC-101-01〜07 / TC-102-01/02/03/04/05 /
  TC-108-03 / TC-106-06 (相当)

---

## テストケースサマリー

| 分類 | 件数 | テスト ID |
|---|---|---|
| 正常系 | 7 | SE-N01, SE-N02, SE-N03, SE-N04, SE-N05, SE-N06, SE-N07 |
| 異常系 | 4 | SE-E01, SE-E02, SE-E03, SE-E04 |
| 境界値 | 7 | SE-B01, SE-B02, SE-B03, SE-B04, SE-B05, SE-B06, SE-B07 |
| **合計** | **18** | — |

### 信頼性レベル分布
- 🔵 青信号: 11 件 (SE-N01〜N05, SE-E01, SE-E03, SE-B01, SE-B02, SE-B05, SE-B06)
- 🟡 黄信号: 7 件 (SE-N06, SE-N07, SE-E02, SE-E04, SE-B03, SE-B04, SE-B07) ※ 🔵🟡 併記は 🟡 に計上
- 🔴 赤信号: 0 件
- **品質評価: 高品質** — 正常系・異常系・境界値を網羅し、完了条件 9 項目 + 注入検証を全カバー。

## 品質判定

- **テストケース分類**: 正常系 7 / 異常系 4 / 境界値 7 で網羅 ✅
- **期待値定義**: 各ケースに具体的期待値 (approx 閾値・== ビット同一・例外型・呼び出し回数) を明記 ✅
- **技術選択**: Python 3.12 + pytest 確定、テストダブルは test_tree_search.py 踏襲で確定 ✅
- **実装可能性**: 下位部品 (staged/tree/changepoint/lifecycle/trajectory/persistent) 実装済みで確実 ✅
- **信頼性レベル**: 🔵 が過半 (11/18)、🔴 なし ✅

**総合判定: ✅ 高品質** — Red フェーズ (`/tsumiki:tdd-red m2-sequential TASK-0019`) へ進行可能。
