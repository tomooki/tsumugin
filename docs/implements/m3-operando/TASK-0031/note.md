# TASK-0031 TDD 開発コンテキストノート

**タスク**: changepoint 感度較正 — `ChangepointConfig` に強度閾値 (`new_peak_min_height_frac=0.05`) と持続条件 (`new_peak_persistence=2`) を追加し、engine 側で未マッチピークの位置ビンごと連続出現カウンタを保持して持続 M フレーム以上のみ new_peaks 指標へ計上する (Issue #3)
**要件名**: m3-operando / **タスクID**: TASK-0031 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 3 / **信頼性**: 🔵 5/5 (Issue #3 / REQ-015 / 設計 D7 / TC-206-06 / interfaces.py L369-371)
**作成日時**: 2026-07-04 / **ブランチ**: milestone/m3-operando (想定)

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

実 GSAS-II のノイズ付きデータでは未モデル微小ピークが 1 本でもあると毎フレーム changepoint が立ち、
その都度 `HypothesisTreeSearch` が起動して**探索連発**になり得る (正しさでなく計算量の問題, Issue #3)。
これを較正するため 2 つのゲートを追加する:

1. **強度閾値 `new_peak_min_height_frac=0.05`** — 相対高さが閾値未満の**微小ピーク**を new_peaks 計上対象から除外。
   実データの持続的な微小ノイズピーク (Issue #3 の「毎フレーム発火」原因) を抑える。
2. **持続条件 `new_peak_persistence=2` (連続 M フレーム)** — 同一位置ビンで M フレーム連続して
   未マッチが継続したときのみ new_peaks を発火。**単発 (1 フレーム) のスパイクノイズ**を抑える。

**実装方針 (設計 D7 / interfaces.py L369-371)**:
- `src/tsumugin/sequential/changepoint.py::ChangepointConfig` に 2 フィールドを**既定値付き非破壊追加**。
  純関数 `detect_changepoint` の**判定ロジックとシグネチャは不変**に保つ (new_unmatched は従来どおり
  `>= min_new_peaks` で評価)。ゲートは**engine 側**で `new_unmatched` を組み立てる段階に置く。
- `src/tsumugin/sequential/engine.py::SequentialEngine`: `_count_unmatched` 系の経路で
  未マッチ観測ピークの**位置ビンごと連続出現カウンタ**を engine 状態として保持し、
  「強度閾値以上 かつ 連続 M フレーム以上継続」した位置ビン数を `detect_changepoint` へ渡す
  `new_unmatched` として計上する。

**🚨 絶対制約 (完了条件と直結)**:
- 単発ノイズピーク (1 フレーム) では new_peaks 指標が**発火しない** (持続 M=2 未満) 🔵 *TC-206-06*
- 持続する真の新相ピーク (M=2 以上) では new_peaks が**発火する** 🔵 *TC-206-06*
- 強度閾値 (`new_peak_min_height_frac`) 未満の微小ピークは**計上しない** 🔵
- 既存 `changepoint`/`engine` テストが**無改変 green** (後方互換) — ⚠️ §6 の相互作用フラグ必読 🔵
- **決定論 (NFR-102)** 維持 — 乱数/IO なし・安定ソート・dict 反復順非依存・同一入力ビット同一。
- **非有限漏洩なし** (M1 教訓 / CLAUDE.md) — 非有限を robust z / 下流へ漏らさない。
- 追加フィールドは**既定値付き**で、既存呼び出し (`ChangepointConfig()` / `detect_changepoint(...)`) を壊さない。
- **git commit しない** (本セッションはユーザー判断)。**質問しない** (自律実行)。
- (コミット時) メッセージに **"Closes #3"** を含める (コミット自体は本タスク外)。

**参照元**: `docs/tasks/m3-operando/TASK-0031.md`, `docs/design/m3-operando/architecture.md` D7 (L88-91),
`docs/design/m3-operando/interfaces.py` L369-371, `docs/spec/m3-operando/requirements.md` REQ-015 (L65-66),
`docs/spec/m3-operando/acceptance-criteria.md` TC-206-06 (L58-59),
`docs/spec/m3-operando/user-stories.md` ストーリー 3.2 (L74-81), GitHub Issue #3

---

## 1. 技術スタック

- **言語 / ランタイム**: Python >=3.12 (`pyproject.toml`)。数値は `numpy>=1.26`。
- **パッケージ / テスト**: `uv` 管理。テストは `uv run pytest` (カバレッジ `uv run pytest --cov=tsumugin`)。
- **アーキテクチャパターン**: 不変データ (`frozen dataclass` + 非破壊更新) + `typing.Protocol` 境界 +
  追記専用ストア (`Ledger`/`SnapshotStore`) + **純関数コア**。M0〜M2 と同一パターン。
- **本タスクの対象レイヤ**:
  - `changepoint.py` = **純関数モジュール** (乱数・I/O・外部状態なし・決定論)。設定は frozen dataclass。
  - `engine.py` = オーケストレーション本体 (下位部品を束ねる。逐次状態は run 内ローカル変数で保持)。
- **参照元**: `pyproject.toml`, `CLAUDE.md` (L21-22, L60, L66, L74-76),
  `src/tsumugin/sequential/changepoint.py`, `src/tsumugin/sequential/engine.py`

## 2. 開発ルール

- **TDD 厳守**: Red(失敗テスト) → Green(最小実装) → Refactor。テストなしの実装コミット禁止。
- **テスト配置**: `tests/` に実装ファイルと 1:1 対応。本タスクは既存
  `tests/test_changepoint.py` / `tests/test_sequential_engine.py` に追加/新規テストを載せる。
- **決定論 (NFR-102 再現性)**: 乱数種固定でビット同一。GSAS-II のノイズ付き Yobs でなく Ycalc を使う。
  安定ソート・dict 反復順非依存。
- **非破壊更新**: `frozen dataclass` + `with_updates()` 等。境界は `typing.Protocol`。
- **非有限を漏らさない** (M1 教訓): `inf`/`NaN` を robust z・下流・CSV へ漏らさない。
- **後方互換 (本タスク固有)**: 追加は既定値付き非破壊。既存テストの期待値変更は原則不可
  (⚠️ §6 の相互作用は要合意。プロジェクト先例 TASK-0024 では「既存テストの期待値変更は理由コメント付き最小修正」を許容)。
- **コミット規約**: kairo/dev タスク 1 件完了 (テスト green) ごとに 1 コミット。本セッションではコミットしない。
- **参照元**: `CLAUDE.md` (L45, L60, L66, L74-76), `docs/implements/m3-operando/TASK-0024/note.md` (先例)

## 3. 関連実装

### 3.1 `src/tsumugin/sequential/changepoint.py` (拡張対象・必読)
- `ChangepointConfig` (frozen): 既定 `window=5` / `z_threshold=5.0` / `min_new_peaks=1` (L19-31)。
  → ここに `new_peak_min_height_frac: float = 0.05` / `new_peak_persistence: int = 2` を追加。
- `detect_changepoint(rwp_history, lattice_history, new_unmatched, *, config)` (L120-178):
  3 指標 (rwp_jump / lattice_jump / new_peaks) の robust z を OR 結合。**new_peaks は
  `new_unmatched >= config.min_new_peaks`** の単純カウント (L167)。
  → **本タスクではこの純関数の判定式・シグネチャは変えない**。持続/強度ゲートは engine 側で `new_unmatched`
     を組み立てる段階に置く (設計 D7 の「engine が連続出現カウントを保持」に合致)。
- `_robust_z` / `_lattice_z` / `_axis_diff_series`: 変更なし。MAD=0 縮退ガードあり (L66-67)。

### 3.2 `src/tsumugin/sequential/engine.py` (拡張対象・必読)
- `_count_unmatched(phases, two_theta, intensity) -> int` (L412-440): 観測ピーク検出 →
  各相 simulate→find_peaks→match_score → `unmatched_peaks` で未マッチ観測ピーク集約 → **件数**を返す。
  現状は `find_peaks(min_height_frac=search_cfg.min_peak_height_frac)` を使い、**位置情報を捨てて件数のみ**返す。
  → 位置ビンごとの持続カウントには、未マッチ観測ピークの**位置 (2θ)** が必要。`unmatched_peaks` の
     `report.unmatched_observed` (現状 `len()` のみ利用) から位置を取り出す拡張が要る。
- `run(...)` の逐次ループ (L191-309):
  - `new_unmatched = self._count_unmatched(current_phases, two_theta, intensity_i)` (L234)。
  - `rwp_history.append(...)` / `lattice_history.append(...)` の履歴蓄積部 (L237-238)。
  - `detect_changepoint(rwp_history, lattice_history, new_unmatched, config=config.changepoint)` (L246-248)。
  → engine の逐次状態 (`rwp_history`/`lattice_history` と同格) に **位置ビンごとの連続未マッチカウンタ**
     (例: `dict[bin_key, int]` または前フレーム未マッチ位置集合) を追加し、
     持続 M フレーム以上 かつ 強度閾値以上の位置ビン数を `new_unmatched` として `detect_changepoint` へ渡す。
  - 失敗フレーム (非有限) は履歴を更新せず継続 (L210-230)。**持続カウンタも失敗フレームでは据え置き**とするか
    は要検討 (決定論・warm start 継続の一貫性)。

### 3.3 再利用ユーティリティ
- `src/tsumugin/search/peaks.py::find_peaks(two_theta, intensity, min_height_frac)` — 観測/計算ピーク検出。
  **強度閾値ゲート**は `min_height_frac` パラメータで表現可能 (新規 `new_peak_min_height_frac` を渡す設計余地)。
- `src/tsumugin/search/matcher.py::match_score` / `unmatched_peaks` — 未マッチ観測ピーク集約。
  `unmatched_peaks(...).unmatched_observed` に未マッチ観測ピーク (位置を含む) が入る。
- 位置ビン化: 決定論のため 2θ を一定刻みで量子化 (engine 既に `_quantize_history` で量子化の先例あり, L516-523)。
- **参照元**: `src/tsumugin/sequential/changepoint.py`, `src/tsumugin/sequential/engine.py`,
  `src/tsumugin/search/peaks.py`, `src/tsumugin/search/matcher.py`

## 4. 設計文書

- **設計 D7 (Issue #3 の較正)** 🔵: `ChangepointConfig` に `new_peak_min_height_frac` (既定 0.05) と
  `new_peak_persistence` (既定 2) を追加 (既定値付き非破壊)。SequentialEngine は未マッチピークの
  **連続出現カウント**を保持し、持続 M フレーム以上で初めて new_peaks 指標を発火させる。
  参照元: `docs/design/m3-operando/architecture.md` L88-91。
- **interfaces.py 契約** 🔵: `ChangepointConfig に追加 (既定値付き非破壊): new_peak_min_height_frac: float = 0.05 /
  new_peak_persistence: int = 2 # 連続 M フレームで発火`。参照元: `docs/design/m3-operando/interfaces.py` L369-371。
- **REQ-015 (Issue #3)** 🔵: 新規未マッチピーク指標は**強度閾値と持続条件 (連続 M フレーム、既定 2)** を持ち、
  単発ノイズで changepoint / 局所探索が連発しないよう較正されなければならない。
  参照元: `docs/spec/m3-operando/requirements.md` L65-66。
- **既存 ChangepointConfig 契約 (M2)**: window=5 / z_threshold=5.0 / min_new_peaks=1。
  参照元: `docs/design` (interfaces.py L81-88 相当) / `src/tsumugin/sequential/changepoint.py` L29-31。
- **参照元**: `docs/design/m3-operando/architecture.md`, `docs/design/m3-operando/interfaces.py`,
  `docs/spec/m3-operando/requirements.md`, `docs/spec/m3-operando/user-stories.md`

## 5. テスト関連情報

- **テストフレームワーク**: `pytest` (`uv run pytest`)。設定は `pyproject.toml` (`[dependency-groups] dev`)。
- **対象テストファイル**:
  - `tests/test_changepoint.py` (347 行, 純関数 `detect_changepoint` の単体テスト。TC-C-N01〜N06 /
    TC-C-E01〜E03 / TC-C-B01〜B05)。**全て `detect_changepoint` を明示 `new_unmatched` 付きで直接呼ぶ**ため、
    engine 側ゲート追加では**無改変で green を維持** (config 既定値追加も TC-C-B05 の 3 項目チェックに非干渉)。
  - `tests/test_sequential_engine.py` (逐次エンジン統合テスト。SE-N/E/B 系 18 件)。
    - `_phase_b_series(n_frames=16, b_onset=10)` = 相 B が frame10 から出現するシーケンス (L104-109)。
    - `test_phase_b_emergence_triggers_changepoint` (L285-302): **frame10 で changepoint=True かつ
      "new_peaks" が reasons に含まれる**ことを検証 — ⚠️ §6 の相互作用の中心。
    - `test_local_search_adopts_phase_b_and_continues` (L305-322) / `test_tree_search_runs_only_on_changepoint_frames` (L325-)。
- **既存テストの命名/構成パターン**: 関数名 `test_*`、日本語コメント (【テスト目的】/【テスト内容】/
  【期待される動作】/信頼性レベル 🔵🟡)。`GRID = np.arange(15.0, 60.0, 0.02)`、`_phase(a, ref)` ヘルパ。
- **テストダブル**: `SimulatedBackend(peak_fwhm=0.2)` (合成データ)、`PhaseRecordingSpyBackend` /
  `FrameFailBackend` / `FakeBackend` (test_sequential_engine.py L117-229) — refine 入力/失敗注入/evidence 制御用。
- **合成データの決定論**: `SimulatedBackend` は Ycalc ベースで乱数なし → ビット同一。
- **参照元**: `tests/test_changepoint.py`, `tests/test_sequential_engine.py`, `pyproject.toml`, `CLAUDE.md` L21-22

## 6. 注意事項

### ⚠️ 相互作用フラグ (実装前に必読 — 本タスク最大のリスク)

**既存 `tests/test_sequential_engine.py::test_phase_b_emergence_triggers_changepoint` (L285-302) と
`new_peak_persistence=2` 既定は緊張関係にある。**

**実測 (現行実装で確認済み)**: 相 B 出現シーケンス (`b_onset=10`) を現行エンジンで走らせると、
**frame10 のみが changepoint=True で reasons=('new_peaks',)** (rwp_jump は非発火)。frame11 以降は
B が採択され模型に取り込まれるため未マッチ 0 → 非発火:

```
frame10  cp=True  reasons=('new_peaks',)  phases=['A','B']  ← 唯一の発火。rwp_jump は MAD=0 で非発火
frame11+ cp=False reasons=()              phases=['A','B']
```

- frame10 で rwp_jump が発火しない理由: 直近窓 (frame6-10) の Rwp は frame6-9 がほぼ 0 (完全適合) で
  MAD=0 → robust z が縮退ガード (changepoint.py L66-67) で 0.0 になり `> z_threshold` を満たさない。
  **frame10 の発火は new_peaks 指標に完全依存**する。

**問題**: 位置ビンごと連続出現カウンタで持続 M=2 を素直に課すと、B は frame10 で初出 (連続カウント=1)
のため new_peaks が抑制され、frame10 の changepoint が立たない。すると B は frame10 で採択されず、
未マッチが frame11 まで継続 (連続カウント=2) して **発火が frame10 → frame11 へシフト**する。
これは既存テストの `assert records[10].changepoint is True` を破る。

**根本原因**: 単発ノイズ (TC-206-06 で抑制すべき対象) と「即採択される真の新相 (frame10 で採択され未マッチが
1 フレームで消える)」は、**未マッチ信号上はどちらも 1 フレームのみ**で区別不能。持続ゲートを未マッチ信号に
かける限り、両者を frame10 時点で判別できない (採択は changepoint 発火の下流にあるため循環)。

**resolve 方針 (tdd-red / tdd-testcases で確定)** — 以下いずれかを選択・合意する:
- **(A) 相 B テストの期待フレームを 10→11 に理由コメント付き最小修正** — 持続 M=2 の正しい帰結として
  「真の新相は M フレーム確認後に発火」を受け入れる。プロジェクト先例 (TASK-0024 note.md §矛盾フラグ)
  が「既存テストの期待値変更は理由コメント付き最小修正」を許容している点と整合。ただし本タスクの
  「無改変」制約とは緊張。→ **推奨: このケースを「無改変 green」の例外として要件段階で明示合意**。
- **(B) 持続カウンタの評価順序を工夫**して frame10 発火を保つ (例: 未マッチ位置の持続を採択前信号で
  評価し、初出強ピークを別扱い) — ただし TC-206-06 の「単発上限閾値ノイズを抑制」と両立困難
  (上と同じ判別不能問題に帰着) なため**非推奨**。
- テスト影響を `tests/test_changepoint.py` (純関数) と `tests/test_sequential_engine.py` (統合) で分けて捉える:
  **前者は完全無改変 green** を担保でき、後者の相 B 1 件のみが判断対象。

**この相互作用は requirements.md §前提 と testcases.md の回帰カテゴリで正式に扱う。**

### その他の技術的制約
- **決定論**: 位置ビンのキー化 (2θ 量子化) と dict 反復順・カウンタ更新順を安定化し、ビット同一を保つ。
- **強度閾値の適用点**: `new_peak_min_height_frac` は観測ピークの `find_peaks(min_height_frac=...)` 段で
  適用する設計余地。既存の `search_cfg.min_peak_height_frac` (現行 `_count_unmatched` が使用) との
  役割分担 (別ゲートか上書きか) を明確化する必要がある。
- **失敗フレームの扱い**: 非有限フレームで持続カウンタを据え置くか・リセットするか (warm start 継続との一貫性) を定義。
- **参照元**: `src/tsumugin/sequential/changepoint.py`, `src/tsumugin/sequential/engine.py`,
  `tests/test_sequential_engine.py`, `docs/implements/m3-operando/TASK-0024/note.md`, `CLAUDE.md`
