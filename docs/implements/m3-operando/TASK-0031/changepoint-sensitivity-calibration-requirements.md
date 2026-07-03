# TASK-0031 要件定義: changepoint 感度較正 (Issue #3)

**機能名**: changepoint-sensitivity-calibration / **タスクID**: TASK-0031 / **要件名**: m3-operando
**タイプ**: TDD (較正・非破壊拡張) / **信頼性**: 🔵 (Issue #3 / REQ-015 / 設計 D7 / interfaces.py L369-371 / TC-206-06)

> すべてのパスはプロジェクトルートからの相対パス。

---

## ⚠️ 前提: 既存テストとの相互作用フラグ (要件確定の根拠)

`new_peak_persistence=2` (連続 M フレーム) の既定値は、既存
`tests/test_sequential_engine.py::test_phase_b_emergence_triggers_changepoint` (L285-302) と**緊張関係**にある。
現行実装で相 B 出現シーケンス (`b_onset=10`) を走らせると **frame10 のみが `changepoint=True` /
`reasons=('new_peaks',)`** で、rwp_jump は直近窓の MAD=0 縮退 (changepoint.py L66-67) により非発火。
すなわち frame10 の発火は **new_peaks 指標に完全依存**する。持続 M=2 を素直に課すと B は frame10 で初出
(連続カウント=1) のため new_peaks が抑制され、発火が **frame10 → frame11 へシフト**し、既存テストの
`assert records[10].changepoint is True` を破る。

根本原因: 単発ノイズ (抑制すべき) と「即採択される真の新相 (採択で未マッチが 1 フレームで消える)」は
未マッチ信号上どちらも 1 フレームのみで**区別不能**。採択は changepoint 発火の下流にあるため循環する。

**本要件は以下で確定する**:
- 純関数 `detect_changepoint` の**判定式・シグネチャは不変** → `tests/test_changepoint.py` (TC-C-*) は**完全無改変 green**。🔵
- 持続/強度ゲートは**engine 側**で `new_unmatched` を組み立てる段階に置く (設計 D7)。🔵
- 相 B 出現テストの frame10 発火保持については **REQ-N-05 / §制約** で扱い、テストケース段階
  (testcases.md 回帰カテゴリ) で解決方針を確定する。プロジェクト先例 (TASK-0024) は「既存テストの期待値変更は
  理由コメント付き最小修正」を許容しており、**相 B テストのみを「無改変 green」の要合意例外**として明示する。🔵

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: `sequential/changepoint.py::ChangepointConfig` に**新規未マッチピーク指標の強度閾値**
  (`new_peak_min_height_frac`, 既定 0.05) と**持続条件** (`new_peak_persistence`, 既定 2 = 連続 M フレーム) を
  既定値付きで非破壊追加し、`sequential/engine.py::SequentialEngine` が未マッチ観測ピークの**位置ビンごと
  連続出現カウンタ**を保持して「強度閾値以上 かつ 連続 M フレーム以上継続」した位置ビン数のみを new_peaks 指標
  (`new_unmatched`) へ計上するよう較正する。
- 🔵 **どのような問題を解決するか**: 現状 `min_new_peaks=1` は単純カウント閾値で `_count_unmatched` は全フレームで
  計算されるため、実 GSAS-II のノイズ付きデータでは未モデル微小ピークが 1 本でもあると**毎フレーム changepoint が
  立ち、その都度 `HypothesisTreeSearch` が起動して探索連発**になり得る (正しさでなく計算量の問題, Issue #3)。
  強度閾値で微小ピークを、持続条件で単発スパイクを除外し、計算量破綻を防ぐ。
- 🔵 **想定されるユーザー**: 実データ運用者 (実 GSAS-II データで operando 逐次解析を回す研究者)。
  「単発ノイズピークで changepoint・木探索が連発しないよう感度を較正してほしい」(ストーリー 3.2)。
- 🔵 **システム内での位置づけ**: `changepoint.py` は Workers 層の**純関数モジュール** (決定論・乱数/IO なし)。
  `engine.py` はオーケストレーション本体で、逐次状態 (`rwp_history`/`lattice_history` 等) を run 内で保持する。
  本タスクは (a) config への非破壊フィールド追加と (b) engine 逐次状態への連続出現カウンタ追加に閉じる。
- **参照した EARS 要件**: REQ-015 (Issue #3)
- **参照したユーザストーリー**: ストーリー 3.2「ノイズによる誤検出の抑制 (Issue #3)」(`docs/spec/m3-operando/user-stories.md` L74-81)
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` D7 (L88-91)、
  `docs/design/m3-operando/interfaces.py` L369-371

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 `ChangepointConfig` の拡張 (frozen dataclass, 非破壊)
🔵 既存 3 フィールドに 2 フィールドを**末尾追加**する (既定値付き):

| フィールド | 型 | 既定値 | 意味 | 信頼性 |
|---|---|---|---|---|
| `window` | int | 5 | (既存) ローリング窓幅 | 🔵 |
| `z_threshold` | float | 5.0 | (既存) robust z 発火閾値 | 🔵 |
| `min_new_peaks` | int | 1 | (既存) new_peaks 発火下限 (計上後の閾値) | 🔵 |
| **`new_peak_min_height_frac`** | **float** | **0.05** | **新規: 未マッチ観測ピークを計上する相対高さ下限** | 🔵 |
| **`new_peak_persistence`** | **int** | **2** | **新規: 同一位置ビンで連続 M フレーム継続時のみ計上 (M=1 は現行等価)** | 🔵 |

- 🔵 追加は末尾・既定値付きのため `ChangepointConfig()` / 位置引数 `ChangepointConfig(5, 5.0, 1)` を壊さない。
- 🔵 frozen は維持 (再代入不可)。

### 2.2 `detect_changepoint` の入出力 (シグネチャ不変)
🔵 `detect_changepoint(rwp_history, lattice_history, new_unmatched, *, config=ChangepointConfig()) -> ChangepointSignal`。
- 入力 `new_unmatched: int` の**意味は不変** (現フレームの新規未マッチピーク数)。判定は従来どおり
  `new_unmatched >= config.min_new_peaks` で new_peaks 発火 (changepoint.py L167)。
- **本タスクでは判定ロジックを変更しない**。強度/持続ゲートは engine が `new_unmatched` を作る段階で適用済とする。
- 🟡 追加 config フィールドを純関数内でも参照するか (例: `min_new_peaks` との整合検証) は任意。既定は engine 側適用に閉じる。

### 2.3 engine 側の連続出現カウンタ (新規逐次状態)
🔵 `SequentialEngine.run` の逐次状態に、未マッチ観測ピークの**位置ビンごと連続未マッチフレーム数**を保持する状態
(例: `dict[bin_key, int]` もしくは前フレーム未マッチ位置集合) を追加する。
- 入力: `_count_unmatched` 相当が返す**未マッチ観測ピークの位置 (2θ) と高さ** (現状は件数 `int` のみ)。
  → `unmatched_peaks(...).unmatched_observed` (現状 `len()` のみ利用, engine.py L439-440) から位置/高さを取り出す拡張が要る。
- 処理: (1) `new_peak_min_height_frac` 未満の未マッチピークを除外、(2) 位置を決定論ビンにキー化 (2θ 量子化)、
  (3) 前フレームから継続するビンはカウンタ +1、非継続ビンは 0/削除、(4) カウンタ `>= new_peak_persistence` の
  ビン数を集計。
- 出力: 集計値を `detect_changepoint` の `new_unmatched` として渡す。
- 🔵 決定論: ビンキー化・カウンタ更新順・dict 反復順を安定化し、同一入力でビット同一。

### 2.4 データフロー (該当区間)
🔵 `run` 逐次ループ (engine.py L191-309):
`intensity_i` → `_count_unmatched`(拡張: 位置付き未マッチ) → **強度/持続ゲート** (新規) →
`new_unmatched`(持続確定ビン数) → `detect_changepoint(rwp_history, lattice_history, new_unmatched, config)` →
`signal.triggered` → 発火時のみ `HypothesisTreeSearch` 起動 → 採択判定。

- **参照した EARS 要件**: REQ-015
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py` L369-371 (config 契約)、
  `src/tsumugin/sequential/changepoint.py` L19-31 / L120-178、`src/tsumugin/sequential/engine.py` L234-248 / L412-440

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **後方互換 (最重要)**: 追加フィールドは既定値付き非破壊。`detect_changepoint` の判定式・シグネチャ不変。
  `tests/test_changepoint.py` (TC-C-N01〜N06 / E01〜E03 / B01〜B05) は**無改変 green**
  (全て純関数を明示 `new_unmatched` 付きで直接呼ぶため engine 側ゲートに非干渉。TC-C-B05 の既定値チェックも
  既存 3 項目のみで新規フィールド追加に非干渉)。🔵 *完了条件④*
- 🔵 **決定論 (NFR-102)**: 乱数不使用・安定ソート・dict 反復順非依存・位置ビンキー化の量子化を固定し、同一入力でビット同一。
- 🔵 **非有限を漏らさない** (M1 教訓 / CLAUDE.md): 非有限を robust z / 下流 / CSV へ漏らさない。失敗フレーム
  (非有限 chi2) は既存どおり履歴非更新で継続 (engine.py L210-230)。持続カウンタも失敗フレームでの扱い
  (据え置き/リセット) を決定論的に定義する。
- 🟡 **パフォーマンス**: 本較正の目的は探索連発 (計算量破綻) の抑止。ゲート追加自体の計算量は
  `_count_unmatched` 既存コスト内に収める (追加は位置抽出とカウンタ更新のみ)。
- 🔵 **アーキテクチャ制約**: 純関数コア + frozen dataclass + Protocol 境界を維持。`changepoint.py` は純関数のまま。
  逐次状態は `SequentialEngine.run` 内ローカル (`rwp_history` 等と同格) に閉じ、外部状態化しない。
- 🟡 **強度閾値の役割分担**: `_count_unmatched` は現状 `search_cfg.min_peak_height_frac` を使う (engine.py L423/L432)。
  新規 `new_peak_min_height_frac` はこれと**別ゲート** (new_peaks 計上専用の追加下限) とし、既存の観測/計算ピーク
  検出閾値には干渉しない設計を既定とする。🟡 (設計 D7 は「新規ピーク指標に強度閾値」と明記、適用点は妥当推測)
- **参照した EARS 要件**: REQ-015, NFR-102
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` D7、`CLAUDE.md` L60/L66/L74-76

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

- 🔵 **基本 (単発ノイズ抑制)**: ある位置ビンに未マッチピークが**1 フレームだけ**出現 (単発スパイク)。連続カウント=1 <
  M=2 のため new_peaks 非計上 → changepoint 非発火 → 木探索非起動。*TC-206-06 前半*
- 🔵 **基本 (真の新相検出)**: ある位置ビンに未マッチピークが**M フレーム以上連続**出現 (持続する真の新相)。
  連続カウント >= M でその位置ビンを計上 → `new_unmatched >= min_new_peaks` → new_peaks 発火。*TC-206-06 後半*
- 🔵 **強度ゲート**: 相対高さ `new_peak_min_height_frac` 未満の微小未マッチピークは、持続していても計上しない
  (実データの微小ノイズフロアによる毎フレーム発火の抑止)。*Issue #3 本旨*
- 🟡 **M=1 の縮退**: `new_peak_persistence=1` に設定すると現行 (持続条件なし) と等価な計上に戻る (後方調整の余地)。
- 🔵 **既定値の回帰**: `ChangepointConfig()` の既定 = window5 / z5.0 / min_new_peaks1 / min_height_frac0.05 / persistence2。
- ⚠️ **相 B 出現 (相互作用)**: 真の相 B が frame10 で出現し即採択されるシーケンス。持続 M=2 では frame10 で連続=1 の
  ため new_peaks 抑制 → 発火が frame11 へシフト。既存テストとの整合は §前提 / testcases.md 回帰カテゴリで解決。
- 🔵 **エラー/縮退**: 観測ピークなし (フラット) → 未マッチ 0 → 非発火 (engine.py L425-427)。warm-up (履歴 < window) →
  detect_changepoint が全指標縮退 (changepoint.py L143-152)。いずれも例外化しない。
- **参照した EARS 要件**: REQ-015, EDGE (探索連発の計算量破綻)
- **参照した設計文書**: `docs/spec/m3-operando/acceptance-criteria.md` TC-206-06 (L58-59)、
  `docs/design/m3-operando/architecture.md` D7

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: ストーリー 3.2「ノイズによる誤検出の抑制 (Issue #3)」(`docs/spec/m3-operando/user-stories.md` L74-81)
- **参照した機能要件**: REQ-015 (`docs/spec/m3-operando/requirements.md` L65-66)
- **参照した非機能要件**: NFR-102 (決定論・再現性)
- **参照したEdgeケース**: 実データ微小ピークによる探索連発 (Issue #3 背景)、単発スパイクノイズ
- **参照した受け入れ基準**: TC-206-06 (`docs/spec/m3-operando/acceptance-criteria.md` L58-59):
  「単発ノイズピーク 1 本では新規ピーク指標が発火しない (持続 M=2 未満)、持続する真の新相ピークでは発火する」
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m3-operando/architecture.md` D7 (L88-91)
  - **型定義/契約**: `docs/design/m3-operando/interfaces.py` L369-371
  - **実装 (拡張対象)**: `src/tsumugin/sequential/changepoint.py` (ChangepointConfig L19-31 / detect_changepoint L120-178)、
    `src/tsumugin/sequential/engine.py` (_count_unmatched L412-440 / run 逐次ループ L191-309 / rwp_history 蓄積 L237-238)
  - **既存テスト**: `tests/test_changepoint.py` (無改変 green 対象)、
    `tests/test_sequential_engine.py::test_phase_b_emergence_triggers_changepoint` (相互作用対象)

## 6. 完了条件 (TASK-0031.md 由来)

- [ ] 単発ノイズピーク 1 フレームでは発火しない 🔵 *TC-206-06*
- [ ] 持続する真の新相ピーク (M=2 以上) で発火する 🔵
- [ ] 強度閾値未満の微小ピークは計上しない 🔵
- [ ] 既存 changepoint/engine テスト無改変 green (後方互換) — 相 B テストは §前提の解決方針に従う 🔵
- [ ] コミットに "Closes #3" (コミット自体は本セッション外) 🔵

---

## 品質判定

- **要件の曖昧さ**: なし (設計 D7 / interfaces.py / TC-206-06 に直接依拠。強度ゲート適用点のみ 🟡)。
- **入出力定義**: 完全 (config フィールド・detect_changepoint 契約・engine カウンタ状態を明記)。
- **制約条件**: 明確 (後方互換・決定論・非有限漏洩なし・相互作用フラグを明示)。
- **実装可能性**: 確実 (既存 `unmatched_peaks` の位置情報活用 + 逐次状態追加で実現可能)。
- **信頼性レベル**: 🔵 多数 / 🟡 少数 (強度ゲート適用点・M=1 縮退・パフォーマンス) / 🔴 なし → **高品質**。
