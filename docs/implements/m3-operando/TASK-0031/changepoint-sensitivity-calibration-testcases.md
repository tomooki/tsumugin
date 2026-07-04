# TASK-0031 テストケース: changepoint 感度較正 (Issue #3)

**機能名**: changepoint-sensitivity-calibration / **タスクID**: TASK-0031 / **要件名**: m3-operando
**対象**: `src/tsumugin/sequential/changepoint.py::ChangepointConfig` (フィールド追加) /
`src/tsumugin/sequential/engine.py::SequentialEngine` (位置ビンごと連続出現カウンタ + 強度/持続ゲート)
**対象テストファイル**: `tests/test_changepoint.py` (config 既定値/後方互換) / `tests/test_sequential_engine.py` (engine ゲート/回帰)
**信頼性**: 🔵 (要件定義 §2〜4 / 設計 D7 / interfaces.py L369-371 / TC-206-06 / 既存実装実測)

> すべてのパスはプロジェクトルートからの相対パス。

---

## ⚠️ テスト設計の前提 (相互作用の確定)

- **ゲートは engine 側** (`new_unmatched` を組み立てる段階) に置き、純関数 `detect_changepoint` の判定式・シグネチャは不変。
  → `tests/test_changepoint.py` の既存 TC-C-N01〜N06 / E01〜E03 / B01〜B05 は**完全無改変 green** (TC-CP-R01)。🔵
- **rwp_jump の非関与保証**: engine ゲートの発火/非発火を new_peaks 指標で観測するため、テストデータは
  変化点近傍の Rwp 窓が MAD=0 縮退 (changepoint.py L66-67) となる合成データ (`SimulatedBackend`, Ycalc) を用いる。
  これにより「未マッチピークの持続/強度」以外の指標が発火せず、new_peaks の挙動を単離できる (現行実測で確認済)。🔵
- **相 B 出現テストの扱い**: 既存 `test_phase_b_emergence_triggers_changepoint` (frame10 発火) は持続 M=2 と緊張。
  TC-CP-R03 で解決方針を確定する (§各前提 / requirements §前提)。🔵
- **注入ノイズの表現**: `SimulatedBackend` は相からクリーンな Ycalc を生成するため、未モデルの「ノイズ/新相ピーク」は
  対象 2θ にガウス的バンプを**強度行列へ直接加算**して表現する (テストヘルパ `_inject_peak(...)` を Red で新設)。🟡

## テストケース総括

| 分類 | 件数 | ケースID |
|---|---|---|
| 1. 正常系 | 3 | TC-CP-N01〜N03 |
| 2. 異常系 | 3 | TC-CP-E01〜E03 |
| 3. 境界値 | 6 | TC-CP-B01〜B06 |
| 4. 回帰 (後方互換) | 4 | TC-CP-R01〜R04 |
| **合計** | **16** | |

**新規テストコード (Red で作成)**:
- `tests/test_sequential_engine.py`: TC-CP-N01 / N02 / N03 / E01 / E02 / E03 / B01 / B02 / B03 / B06 = **10 件**
- `tests/test_changepoint.py`: TC-CP-B04 (既定値) / TC-CP-R02 (後方互換コンストラクタ) = **2 件**

**回帰確認 (既存テスト無改変 green で担保・新規コードなし)**:
- TC-CP-R01 (test_changepoint.py 全件) / TC-CP-R04 (既存 engine テスト群) = **2 件**

**要合意の相互作用**: TC-CP-R03 (相 B 出現テストの frame10→11 シフト解決) = **1 件** (方針確定タスク)

---

## 1. 正常系テストケース（基本的な動作）

### TC-CP-N01: 単発ノイズピーク (1 フレーム) では new_peaks が発火しない
- **何をテストするか**: 未マッチ観測ピークが 1 フレームだけ出現する単発スパイクで、持続 M=2 未満のため
  changepoint が発火しないこと。
  - **期待される動作**: 該当フレームで `record.changepoint == False`、かつ全フレームで new_peaks 起因の探索が起きない。
- **入力値**: 単一相 A のクリーン 16 フレーム列に、frame10 のみ 2θ=X (相 A/候補と無関係の位置) へ相対高さ 0.20 の
  バンプを加算。候補プールは空 (`candidates=[]`)。既定 `ChangepointConfig()` (persistence=2, min_height_frac=0.05)。
  - **入力データの意味**: 実データの単発スパイクノイズを代表。強度は閾値 (0.05) を十分上回り、抑制要因が
    「持続不足」のみであることを保証する。
- **期待される結果**: `result.trajectory.records[10].changepoint is False`、
  `"new_peaks" not in records[10].changepoint_reasons`、`10 not in result.search_results`、
  `len(result.search_results) == 0`。
  - **期待結果の理由**: frame10 で当該位置ビンの連続未マッチカウント=1 < M=2 → 計上されず `new_unmatched=0` →
    new_peaks 非発火。rwp_jump は窓 MAD=0 で非発火。
- **テストの目的**: TC-206-06 前半「単発ノイズピーク 1 本では発火しない」の確認。
  - **確認ポイント**: 探索連発 (Issue #3) の根因である「単発で毎回 changepoint」が抑止されること。
- 🔵 信頼性: 要件定義 §4 (単発ノイズ抑制) / TC-206-06 (`docs/spec/m3-operando/acceptance-criteria.md` L58-59)

### TC-CP-N02: 持続する真の新相ピーク (連続 M フレーム) で new_peaks が発火する
- **何をテストするか**: 同一位置ビンの未マッチピークが M=2 フレーム以上連続したとき new_peaks が発火すること。
  - **期待される動作**: 連続 2 フレーム目 (frame b_onset+1) で `changepoint == True` かつ reasons に "new_peaks"。
- **入力値**: 単一相 A のクリーン 16 フレーム列に、frame10 以降 (10,11,12,…) へ 2θ=X の相対高さ 0.20 バンプを
  **継続加算**。候補プールは空 (採択で消えないよう、未モデルの持続ピークとして観測)。既定 config。
  - **入力データの意味**: 採択されない (候補なし) 持続的な新相/未モデルピークを代表。持続条件のみで発火が決まる。
- **期待される結果**: `records[10].changepoint is False` (連続=1)、`records[11].changepoint is True` かつ
  `"new_peaks" in records[11].changepoint_reasons`、`11 in result.search_results`。
  - **期待結果の理由**: frame10 で連続=1 (非発火)、frame11 で連続=2 >= M → 計上 → new_peaks 発火。
- **テストの目的**: TC-206-06 後半「持続する真の新相ピークでは発火する」の確認。
  - **確認ポイント**: 発火フレームが b_onset ではなく b_onset+(M-1) になる (持続確認後発火)。
- 🔵 信頼性: 要件定義 §4 (真の新相検出) / TC-206-06

### TC-CP-N03: 強度閾値以上かつ持続で計上、探索は発火フレームでのみ起動
- **何をテストするか**: 強度閾値以上の未マッチピークが持続した場合に new_peaks が計上され、局所探索が
  発火フレームでのみ起動する (無駄打ちなし)。
  - **期待される動作**: `len(result.search_results) == sum(r.changepoint for r in records)` かつ全キーが発火フレーム。
- **入力値**: TC-CP-N02 と同一データ。
  - **入力データの意味**: 較正後も「探索回数 == 発火フレーム数」の P5 不変 (計算量制御) が保たれることを代表。
- **期待される結果**: `set(result.search_results) == {i for i,r in enumerate(records) if r.changepoint}`。
  - **期待結果の理由**: changepoint 発火時のみ `HypothesisTreeSearch` 起動 (engine.py L255-269) は不変。
- **テストの目的**: 較正がゲート追加のみで、既存の探索起動契約 (発火フレーム限定) を壊さないことの確認。
  - **確認ポイント**: 較正後、単発ノイズフレームでは探索が起動しない (連発抑止の実効)。
- 🔵 信頼性: 既存 `test_tree_search_runs_only_on_changepoint_frames` (`tests/test_sequential_engine.py` L325-) の不変性 / 要件定義 §3

---

## 2. 異常系テストケース（エラーハンドリング）

### TC-CP-E01: 強度閾値未満の微小ピークは持続しても計上しない
- **エラーケースの概要**: 相対高さが `new_peak_min_height_frac` (0.05) 未満の微小未マッチピークが**毎フレーム
  持続**しても new_peaks を計上せず、探索連発を起こさない。
  - **エラー処理の重要性**: Issue #3 の直接原因 (実 GSAS-II の未モデル微小ピークが毎フレーム発火) の抑止。
- **入力値**: 単一相 A のクリーン 16 フレーム列に、frame5 以降すべてへ 2θ=X の相対高さ 0.02 (< 0.05) バンプを継続加算。既定 config。
  - **不正な理由**: ノイズフロア相当の微小ピークは物理的に新相を意味せず、探索対象にすべきでない。
  - **実際の発生シナリオ**: 実データのバックグラウンド揺らぎ・未モデル微弱反射。
- **期待される結果**: 全フレームで `record.changepoint is False` (new_peaks 起因なし)、`len(result.search_results) == 0`。
  - **エラーメッセージの内容**: 例外化しない (安全側縮退)。単に計上されないだけ。
  - **システムの安全性**: 微小ピークが持続しても計算量が破綻しない (探索非起動)。
- **テストの目的**: 強度ゲートが持続ゲートと独立に効くことの確認 (持続していても強度不足なら非計上)。
  - **品質保証の観点**: 較正の主目的 (実データでの探索連発防止) を保証。
- 🔵 信頼性: 要件定義 §3 (強度ゲート) / §4 / Issue #3 背景 (`docs/spec/m3-operando/requirements.md` L65-66)

### TC-CP-E02: 精密化失敗フレーム (非有限) を跨ぐ持続カウンタの決定論的扱い
- **エラーケースの概要**: 持続中の未マッチピーク系列の途中に精密化失敗フレーム (非有限 chi2) が挟まったとき、
  持続カウンタが決定論的に扱われ、例外化せず完走する。
  - **エラー処理の重要性**: 失敗フレームは履歴非更新で継続する既存挙動 (engine.py L210-230) との一貫性が必要。
- **入力値**: TC-CP-N02 の持続ピーク列に対し、`FrameFailBackend` 相当で frame11 の精密化を非収束
  (chi2=inf) にする。既定 config。
  - **不正な理由**: 非有限フレームは robust z / カウンタ更新に混入させてはならない (非有限漏洩禁止)。
  - **実際の発生シナリオ**: 特定フレームでの精密化発散 (EDGE-002)。
- **期待される結果**: 例外なく完走し、`result.warnings` に該当フレームの失敗警告。持続カウンタは**失敗フレームで
  据え置き** (更新しない) とし、成功フレーム系列で連続性を評価 (要件定義 §3 の定義)。結果は**決定論 (再実行でビット同一)**。
  - **システムの安全性**: 非有限を下流へ漏らさず、失敗フレームがカウンタを不定にしない。
- **テストの目的**: 失敗フレームとカウンタ相互作用の決定論・安全性の確認。
  - **品質保証の観点**: M1 教訓 (非有限漏洩なし) と NFR-102 (決定論) の両立。
- 🟡 信頼性: 要件定義 §3 (失敗フレーム扱いの定義) / 既存 EDGE-002 挙動 (据え置きは妥当推測)

### TC-CP-E03: 観測ピークなし (フラットパターン) では未マッチ 0 で非発火
- **エラーケースの概要**: 強度がフラット (観測ピークなし) のフレームで未マッチ 0 となり new_peaks 非発火。
  - **エラー処理の重要性**: 空縮退の既存挙動 (engine.py L425-427) を較正後も維持。
- **入力値**: 全フレーム平坦強度 (ピークなし) の 8 フレーム列。既定 config。
  - **実際の発生シナリオ**: 測定欠損・信号なしフレーム。
- **期待される結果**: 全フレームで `record.changepoint is False`、`len(result.search_results) == 0`、例外なし。
  - **システムの安全性**: 観測ピーク 0 で位置ビン抽出・カウンタが空でも安全に縮退。
- **テストの目的**: 空入力での縮退が較正で壊れないことの確認。
  - **品質保証の観点**: 境界的入力での堅牢性。
- 🔵 信頼性: 既存 `_count_unmatched` 空縮退 (engine.py L425-427) / 要件定義 §4 (縮退)

---

## 3. 境界値テストケース（最小値、最大値、null等）

### TC-CP-B01: 連続 M=2 ちょうどで発火 / M-1=1 で非発火 (持続境界)
- **境界値の意味**: 持続条件の発火境界 (連続カウント == persistence)。
- **入力値**: TC-CP-N02 データ。既定 `new_peak_persistence=2`。
  - **境界値選択の根拠**: M=2 の直前 (連続1) と到達 (連続2) が発火の分かれ目。
- **期待される結果**: `records[10].changepoint is False` (連続1)、`records[11].changepoint is True` (連続2)。
  - **境界での正確性**: 「>= persistence」の包含境界 (2 で発火) が実装されていること。
- **テストの目的**: 持続閾値の包含規則 (>=) の確認。
- 🔵 信頼性: 要件定義 §2.3 (`>= new_peak_persistence`) / TC-206-06

### TC-CP-B02: 相対高さがちょうど強度閾値 (0.05) の境界
- **境界値の意味**: 強度ゲートの計上境界 (相対高さ == min_height_frac)。
- **入力値**: 持続する未マッチピークの相対高さを (a) 0.05 直下 (例 0.049) と (b) 0.05 以上 (例 0.06) の 2 条件で注入。既定 config。
  - **境界値選択の根拠**: `find_peaks(min_height_frac=...)` の閾値挙動 (含む/含まない) に整合させる。
- **期待される結果**: (a) 非計上 → 非発火、(b) 計上 → 持続 2 フレームで発火。閾値の等値時の扱いは
  既存 `find_peaks` の `min_height_frac` 規則に一致させる (実装で確定、Red で期待値固定)。
  - **一貫した動作**: 強度ゲートの境界が既存ピーク検出の閾値規則と整合。
- **テストの目的**: 強度閾値の境界挙動の確認。
- 🟡 信頼性: 要件定義 §3 (強度ゲート適用点) / `src/tsumugin/search/peaks.py` find_peaks の閾値規則 (等値扱いは実装依存)

### TC-CP-B03: persistence=1 で現行 (持続条件なし) と等価に縮退
- **境界値の意味**: 持続条件の下限 (M=1)。M=1 は「即計上」= 較正前挙動。
- **入力値**: TC-CP-N01 の単発ピークデータ + `ChangepointConfig(new_peak_persistence=1)`。
  - **境界値選択の根拠**: 後方調整余地 (M=1 で旧挙動) の担保。
- **期待される結果**: frame10 (単発) で `changepoint is True` かつ "new_peaks" in reasons (M=1 では連続1 で発火)。
  - **境界での正確性**: M=1 が旧来の「1 フレームで発火」に一致。
- **テストの目的**: 持続条件のオプトアウト (M=1) が可能なことの確認。
- 🟡 信頼性: 要件定義 §4 (M=1 縮退) — 妥当推測

### TC-CP-B04: `ChangepointConfig` の既定値 (新規 2 フィールド含む)
- **境界値の意味**: 既定コンストラクタの契約値 (追加フィールドの既定)。
- **入力値**: `ChangepointConfig()` (引数なし)。
  - **境界値選択の根拠**: 既定値変更はリグレッション。設計 D7 / interfaces.py L369-371 の値を固定。
- **期待される結果**: `window == 5`、`z_threshold == pytest.approx(5.0)`、`min_new_peaks == 1`、
  `new_peak_min_height_frac == pytest.approx(0.05)`、`new_peak_persistence == 2`、frozen (再代入で `FrozenInstanceError`)。
  - **境界での正確性**: 既存 3 値 (TC-C-B05 と同一) + 新規 2 値。
- **テストの目的**: 追加フィールドの既定値と frozen の確認。**対象: `tests/test_changepoint.py`**。
- 🔵 信頼性: `docs/design/m3-operando/interfaces.py` L369-371 / architecture.md D7 / 既存 `test_changepoint_config_defaults` (L331-347)

### TC-CP-B05: 決定論 (同一入力 2 回でビット同一)
- **境界値の意味**: NFR-102 再現性。カウンタ・ビンキー化・dict 反復順の安定性境界。
- **入力値**: TC-CP-N02 データを同一 config で 2 回 `run`。
  - **境界値選択の根拠**: カウンタ導入で反復順依存やビン化揺らぎが混入しないことを保証。
- **期待される結果**: 2 回の `result.trajectory.records` の changepoint / reasons / phases 系列がビット同一、
  `result.search_results` のキー集合も一致。
  - **一貫した動作**: 位置ビンキー化 (2θ 量子化) とカウンタ更新順が決定論。
- **テストの目的**: 較正が決定論を壊さないことの確認。
- 🔵 信頼性: NFR-102 / CLAUDE.md L66 / 既存 `test_deterministic_bit_identical` (test_changepoint.py L306-)

### TC-CP-B06: 非連続 (途中消失→再出現) でカウンタがリセットされる
- **境界値の意味**: 「連続」の定義境界 (中断でカウンタ 0 復帰)。
- **入力値**: 2θ=X へ frame10 のみ、frame11 で消失 (バンプなし)、frame12,13 で再出現、という非連続注入。既定 config。
  - **境界値選択の根拠**: 連続 (consecutive) と累積 (cumulative) の区別。単発 1 回 + 単発 1 回 + 連続2 の混在。
- **期待される結果**: frame10 非発火 (連続1)、frame11 非発火 (消失=カウンタ0)、frame12 非発火 (連続1)、
  frame13 発火 (連続2)。
  - **境界での正確性**: 中断でカウンタがリセットされ、累積カウントでは発火しないこと。
- **テストの目的**: 持続が「連続」であり中断でリセットされることの確認。
- 🟡 信頼性: 要件定義 §2.3「連続 M フレーム」/ 設計 D7「連続出現カウント」— 連続解釈は妥当推測

---

## 4. 回帰テストケース（後方互換・無改変 green）

### TC-CP-R01: `tests/test_changepoint.py` 全件が無改変で green
- **何をテストするか**: 純関数 `detect_changepoint` の判定式・シグネチャ不変により、既存 TC-C-N01〜N06 /
  E01〜E03 / B01〜B05 が**コード変更なし**で通ること。
- **入力値**: 既存テスト群 (無改変)。config 既定値追加のみ。
- **期待される結果**: `uv run pytest tests/test_changepoint.py` 全 green。特に TC-C-B05
  (`test_changepoint_config_defaults`) は既存 3 フィールドのみを assert し新規フィールドに非干渉。
  - **確認ポイント**: 追加フィールドが位置引数/既定コンストラクタ/frozen 契約を壊さないこと。
- **テストの目的**: 純関数層の完全後方互換 (完了条件④の中核) の担保。**新規コードなし (既存で担保)**。
- 🔵 信頼性: 要件定義 §3 (後方互換) / 既存 `tests/test_changepoint.py` (直接呼び出し構造)

### TC-CP-R02: `ChangepointConfig` の後方互換コンストラクタ
- **何をテストするか**: 位置引数 `ChangepointConfig(5, 5.0, 1)` と部分キーワード指定が既存どおり動くこと。
- **入力値**: `ChangepointConfig(5, 5.0, 1)`、`ChangepointConfig(window=3)`、`ChangepointConfig(min_new_peaks=2)`。
- **期待される結果**: 既存 3 引数指定で構築でき、未指定の新規 2 フィールドは既定 (0.05 / 2) が入る。例外なし。
  - **確認ポイント**: 新規フィールドが**末尾追加**で既定値付きのため既存呼び出しを壊さない。
- **テストの目的**: config 拡張の非破壊性の確認。**対象: `tests/test_changepoint.py`**。
- 🔵 信頼性: 要件定義 §2.1 (末尾・既定値付き追加) / frozen dataclass の位置引数規則

### TC-CP-R03: 相 B 出現テストの frame10 発火シフト (要合意の相互作用解決)
- **何をテストするか**: 既存 `test_phase_b_emergence_triggers_changepoint` (相 B が frame10 で出現し即採択)
  が持続 M=2 の下でどう振る舞うか、解決方針をテストで固定する。
- **背景 (現行実測)**: 現行は frame10 のみ発火 (reasons=('new_peaks',)、rwp_jump は MAD=0 で非発火)。
  持続 M=2 では frame10 の連続=1 で new_peaks 抑制 → 採択されず → 未マッチが frame11 まで継続 → **発火が
  frame11 へシフト**。単発ノイズ (TC-CP-N01 で抑制すべき) と即採択される真の新相は未マッチ信号上区別不能なため、
  frame10 発火の literal 維持は持続ゲートと両立しない (requirements §前提)。
- **解決方針 (Red で確定)**: **方針 A を採用** — 既存テストの**期待フレームを 10→11 へ理由コメント付き最小修正**する。
  - 修正後: `assert records[11].changepoint is True` / `"new_peaks" in records[11].changepoint_reasons` /
    `11 in result.search_results`。B の採択・以後継続 (`records[15]` に "B") 等の他 assert は不変。
  - 根拠: 持続 M=2 の正しい帰結として「真の新相は M フレーム確認後に発火」。プロジェクト先例 (TASK-0024 note.md
    §矛盾フラグ) が「既存テストの期待値変更は理由コメント付き最小修正」を許容。
  - **注記**: TASK-0031.md の完了条件「既存テスト無改変 green」に対する**唯一の合意例外**として明示する
    (test_changepoint.py 全件と他の engine テストは無改変)。方針 A/B の最終選択は tdd-red で確定。
- **期待される結果**: 方針 A 採用時、修正した相 B テストが green。`test_local_search_adopts_phase_b_and_continues`
  (frame12/15 の B 継続・adopt 記録) は発火フレームが 11 になっても採択継続の assert は成立し green。
- **テストの目的**: 相互作用の明示的解決と、他 engine テストへの波及の限定。
- 🔵 信頼性: 現行実測 (frame10 のみ new_peaks 発火) / requirements §前提 / TASK-0024 先例

### TC-CP-R04: 既存 engine テスト群の無改変 green (相 B 関連以外)
- **何をテストするか**: 相 B 出現以外の既存 engine テスト (線形膨張で非発火、warm start、失敗フレーム継続、
  全フレーム changepoint 完走、単一フレーム等) が無改変で green。
- **入力値**: 既存 `tests/test_sequential_engine.py` の非相B テスト (無改変)。
- **期待される結果**: 該当テスト全 green。特に線形熱膨張シーケンス (相構成不変・changepoint なし想定) は
  未マッチ 0 のままで、ゲート追加により偽発火/偽抑制が生じない。
  - **確認ポイント**: ゲートは未マッチピーク存在時のみ作用し、未マッチ 0 の系列 (合成完全適合) に影響しない。
- **テストの目的**: engine ゲート追加が相 B 系以外へ波及しないことの確認。**新規コードなし (既存で担保)**。
- 🔵 信頼性: 既存 `tests/test_sequential_engine.py` の SE-N/E/B 系 / 要件定義 §3

---

## 4'. 開発言語・フレームワーク

- **プログラミング言語**: Python (>=3.12)
  - **言語選択の理由**: プロジェクト実装言語 (`pyproject.toml`)。`changepoint.py`/`engine.py` は Python 純関数/クラス。
  - **テストに適した機能**: `dataclasses.FrozenInstanceError` 検証、`numpy` による決定論的合成データ生成。
- **テストフレームワーク**: pytest (`uv run pytest`)
  - **フレームワーク選択の理由**: 既存テストが pytest (`tests/test_changepoint.py` / `tests/test_sequential_engine.py`)。
    パラメトライズ (`@pytest.mark.parametrize`)・`pytest.approx`・`pytest.raises` を踏襲。
  - **テスト実行環境**: `uv run pytest tests/test_changepoint.py tests/test_sequential_engine.py`。合成データのため
    GSAS-II 非依存 (`@pytest.mark.gsas` 不要)。
- 🔵 信頼性: `CLAUDE.md` L21-22 / L76 / 既存テストファイル構成

## 5. テストケース実装時の日本語コメント指針 (Red フェーズ)

各テストに以下の日本語ブロックコメントを付す (既存 `tests/test_sequential_engine.py` / `test_changepoint.py` の様式に一致):

```python
def test_single_frame_noise_does_not_trigger():
    # 【テスト目的】: 単発ノイズピーク (1 フレーム) で new_peaks が発火しないこと (TC-CP-N01 / TC-206-06 前半)
    # 【テスト内容】: frame10 のみ 2θ=X へ相対高さ 0.20 のバンプを注入、候補プール空、既定 config
    # 【期待される動作】: records[10].changepoint == False、search_results 空 (探索連発しない)
    # 🔵 信頼性レベル: TC-206-06 / 要件定義 §4 に依拠

    # 【テストデータ準備】: 単一相 A のクリーン列に単発バンプ注入 (_inject_peak で強度行列へ加算)
    # 【初期条件設定】: persistence=2 (既定)、強度は閾値 0.05 を十分上回る (抑制要因を持続不足のみに限定)
    series = _inject_peak(_clean_A_series(n_frames=16), two_theta=X, frames=[10], height_frac=0.20)

    # 【実際の処理実行】: 候補プール空でエンジンを走らせ、単発未マッチの changepoint 判定を観測
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2), candidates=[]).run(series, [_phase(5.0, "A")])

    # 【結果検証】: 単発では持続不足で非計上 → new_peaks 非発火 → 探索非起動
    assert result.trajectory.records[10].changepoint is False  # 【確認内容】: 連続=1 < M=2 で非発火 🔵
    assert "new_peaks" not in result.trajectory.records[10].changepoint_reasons  # 【確認内容】: new_peaks 非計上 🔵
    assert len(result.search_results) == 0  # 【確認内容】: 探索連発が起きない (Issue #3 較正の実効) 🔵
```

## 6. 要件定義との対応関係

- **参照した機能概要**: requirements §1 (強度閾値+持続条件の較正 / Issue #3 探索連発の抑止)
- **参照した入力・出力仕様**: requirements §2 (ChangepointConfig 2 フィールド追加 / detect_changepoint 不変 /
  engine 連続出現カウンタ / データフロー §2.4)
- **参照した制約条件**: requirements §3 (後方互換=純関数不変で test_changepoint.py 無改変 / 決定論 NFR-102 /
  非有限漏洩なし / 強度ゲート適用点 / 失敗フレーム扱い)
- **参照した使用例**: requirements §4 (単発抑制 / 真の新相検出 / 強度ゲート / M=1 縮退 / 相 B 相互作用 / 縮退)
- **参照した受け入れ基準**: TC-206-06 (`docs/spec/m3-operando/acceptance-criteria.md` L58-59)
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` D7 (L88-91)、
  `docs/design/m3-operando/interfaces.py` L369-371
- **参照した既存実装**: `src/tsumugin/sequential/changepoint.py` (ChangepointConfig L19-31 / detect_changepoint L120-178)、
  `src/tsumugin/sequential/engine.py` (_count_unmatched L412-440 / run 逐次ループ L191-309 / rwp_history 蓄積 L237-238)、
  `tests/test_changepoint.py`、`tests/test_sequential_engine.py`

---

## 品質判定

- **テストケース分類**: 正常系 3 / 異常系 3 / 境界値 6 / 回帰 4 = 16 件で網羅 (発火・非発火・強度・持続・境界・決定論・後方互換)。
- **期待値定義**: 各ケースで具体 assert (フレーム index・reasons・search_results・config 値) を明示。
- **技術選択**: Python / pytest 確定 (既存踏襲)。合成データ (SimulatedBackend + _inject_peak) で GSAS-II 非依存。
- **実装可能性**: `unmatched_peaks` の位置情報活用 + engine 逐次状態カウンタで実現可能。
- **信頼性レベル**: 🔵 多数 / 🟡 少数 (強度閾値等値扱い・失敗フレーム据え置き・連続解釈・M=1 縮退) / 🔴 なし → **高品質**。
- **要注意**: TC-CP-R03 (相 B テスト frame10→11) は「既存テスト無改変 green」への合意例外。tdd-red で方針最終確定。
