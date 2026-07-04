# TASK-0024 テストケース: thermal onset 意味論修正 (Issue #4)

**機能名**: thermal-onset-semantics / **タスクID**: TASK-0024 / **要件名**: m3-operando
**対象**: `src/tsumugin/sequential/thermal.py::estimate_transition` (onset の direction 依存化)
**対象テストファイル**: `tests/test_thermal.py` (既存・18 件に追加/改修) / **信頼性**: 🔵 (要件定義 §2 真理値表・数値検証・既存挙動)

> すべてのパスはプロジェクトルートからの相対パス。

## ⚠️ 期待順序の確定 (テスト設計の前提)

採用メカニズムは **disappearing の onset = 分率 90% 交差** (D-Q8 / interfaces.py L372-373)。
`SIGMOID_DOWN` (中心 400 K, 幅 15, 昇温) の実測交差は **90% ≈ 366.46 K < 50% = 400 K < 10% ≈ 433.54 K**。
よって **disappearing でも `onset(90%) < midpoint`** (遷移開始側=低温側)。
TASK-0024.md L12/L20・TC-208-01 の「disappearing: onset > midpoint」は 90% 交差メカニズムと矛盾する誤記のため、
**本テストは `onset < midpoint` で固定**する (`note.md` §⚠️ 矛盾フラグ / requirements §⚠️ 前提)。🔵

## テストケース総括

| 分類 | 件数 | ケースID |
|---|---|---|
| 1. 正常系 | 3 | TC-T-N01〜N03 |
| 2. 異常系 | 3 | TC-T-E01〜E03 |
| 3. 境界値 | 4 | TC-T-B01〜B04 |
| 4. 回帰 (無退行) | 3 | TC-T-R01〜R03 |
| **合計** | **13** | |

**新規/改修テストコード (`tests/test_thermal.py`, Red フェーズで作成)**:
TC-T-N02 (既存 disappearing テストへ onset 検証**追加**=理由コメント付き最小修正) / TC-T-N03 / TC-T-E01 / TC-T-B01 / TC-T-B02 / TC-T-B03 / TC-T-B04 = **7 件**。
**回帰確認 (既存テスト無改変 green で担保・新規コードなし)**: TC-T-N01 / TC-T-E02 / TC-T-E03 / TC-T-R01〜R03 = **6 件**。

---

## 1. 正常系テストケース（基本的な動作）

### TC-T-N01: appearing で onset=10% 交差 (低温側) かつ onset < midpoint
- **何をテストするか**: 増加シグモイド (0→1) で onset が分率 10% 交差 (低温側) となり `onset < midpoint` を満たすこと。
  - **期待される動作**: onset レベルは appearing で 0.10 のまま (現行維持)。onset ≈ 366.46 K < midpoint ≈ 400 K。
- **入力値**: `TEMPS_20` (300..490 K, 10 K 刻み), `SIGMOID_UP`, `phase_ref="phase_A"`
  - **入力データの意味**: 相が昇温で出現する代表遷移 (既存 `test_transition_sigmoid_up_midpoint_onset_sigma` と同一データ)。
- **期待される結果**: `est.direction == "appearing"`、`est.onset < est.midpoint`、`abs(est.midpoint - 400.0) <= 10.0`、`est.sigma > 0.0`
  - **期待結果の理由**: appearing の onset は不変 (10% 交差=低温側)。修正が appearing を退行させないことの担保。
- **テストの目的**: 修正が appearing の現行挙動を壊さないこと (無改変 green)。
  - **確認ポイント**: onset < midpoint が維持されること。
- 🔵 信頼性: 要件定義 §2 真理値表 / 既存 `tests/test_thermal.py::test_transition_sigmoid_up_midpoint_onset_sigma` (L134) に一致。

### TC-T-N02: disappearing で onset=90% 交差 (低温側) かつ onset < midpoint 【本タスクの核心・既存テストへ追加】
- **何をテストするか**: 減少シグモイド (1→0) で onset が分率 **90% 交差** (遷移開始側=低温側) となり `onset < midpoint` を満たすこと。
  - **期待される動作**: onset レベルが direction=="disappearing" で 0.90 に切り替わり、onset ≈ 366.46 K < midpoint ≈ 400 K。
- **入力値**: `TEMPS_20`, `SIGMOID_DOWN`, `phase_ref="phase_A"`
  - **入力データの意味**: 相が昇温で消滅する代表遷移。既存 `test_transition_sigmoid_down_direction_disappearing` (L155) は onset **未検証**なので**検証を追加**する (D-Q8 指定)。
- **期待される結果**: `est.direction == "disappearing"`、`est.onset < est.midpoint`、`est.midpoint == pytest.approx(400.0, abs=10.0)`、`est.sigma > 0.0`、`math.isfinite(est.onset)`
  - **期待結果の理由**: disappearing の 90% 交差は 366.46 K (低温側)。旧挙動 (10% 交差=433.54 K で onset>midpoint) が解消され、onset が遷移開始側を指す (Issue #4 の目的)。
- **テストの目的**: onset 意味論修正の中核 (disappearing で onset が遷移開始側=低温側になること) の固定。
  - **確認ポイント**: 追加 assertion は理由コメント (`# Issue #4: disappearing の onset は 90% 交差=遷移開始側で onset<midpoint`) を付す。既存の direction/midpoint/sigma assertion は無改変。
- 🔵 信頼性: 要件定義 §1/§2 / D-Q8 (L44-48) / interfaces.py L372-373 / 数値検証に直接依拠。

### TC-T-N03: disappearing の onset が 90% 交差の具体値 (旧 10% 交差でないこと)
- **何をテストするか**: disappearing の onset が **90% 交差温度 ≈ 366.46 K** に一致し、修正前の 10% 交差 (≈ 433.54 K) を返さないこと。
  - **期待される動作**: `est.onset == pytest.approx(366.46, abs=1.0)` かつ `est.onset != pytest.approx(433.54, abs=1.0)`。
- **入力値**: `TEMPS_20`, `SIGMOID_DOWN`, `phase_ref="phase_A"`
  - **入力データの意味**: onset が「10%→90% 交差」へ切り替わったことを具体値で明示的に固定 (回帰防止)。
- **期待される結果**: `est.onset == pytest.approx(366.46, abs=1.0)`、`est.onset < est.midpoint`
  - **期待結果の理由**: 90% 交差 (0.90) の線形補間温度が 366.46 K であることを数値検証で確認済み。旧値 433.54 K でないことが修正の証拠。
- **テストの目的**: 意味論修正が「値レベル」で正しく適用されたことの固定 (誤って 10% のままだと検出)。
  - **確認ポイント**: appearing の 10% 交差 (366.46 K) と disappearing の 90% 交差 (366.46 K) が偶然同値になる対称データのため、`direction` と併せて「90% レベルを使ったこと」を保証する (旧実装では disappearing onset=433.54 になり本テストが落ちる)。
- 🔵 信頼性: 要件定義 §2 具体値表 / 数値検証 (90% 交差=366.46 K) に一致。

---

## 2. 異常系テストケース（縮退の非例外化）

### TC-T-E01: disappearing で 90% 未達 (浅い遷移) は例外化せず None へ縮退
- **エラーケースの概要**: 減少するが 90% (0.90) も 50% (0.50) も横切らない浅い遷移 (例 1.0→0.92)。onset/midpoint とも交差なし。
  - **エラー処理の重要性**: 交差が無い場合に偽の onset/midpoint を出さず、非有限を漏らさず `None` へ縮退する必要がある (M1 教訓)。
- **入力値**: `temperatures=TEMPS_20`, `fractions=[1.0 - 0.004*i for i in range(20)]` (1.0→0.924、90%/50% 未達), `phase_ref="A"`
  - **不正な理由**: 明瞭な相転移でない (分率が 0.9 を割らない)。midpoint 交差が無いため遷移未確定。
  - **実際の発生シナリオ**: 相がわずかに減るだけで消滅しない区間、ノイズ的な微減。
- **期待される結果**: `estimate_transition(...) is None`
  - **システムの安全性**: midpoint (50%) 交差が無い時点で `None` (既存 L195-196 の縮退経路)。onset レベル変更は midpoint 縮退の前段を変えない。
- **テストの目的**: onset レベル変更が「交差なし→None」縮退を壊さないことの確認。
  - **品質保証の観点**: 非例外化・非有限漏洩なしの維持。
- 🟡 信頼性: 要件定義 §4 エッジ (90% 未達→None) / 既存 `_interpolate_crossing` の None 経路からの妥当な設計。

### TC-T-E02: 定数分率は None を返す (onset レベル変更の影響なし)
- **エラーケースの概要**: 全フレーム 0.5 の定数分率 (遷移なし)。
  - **エラー処理の重要性**: 50% 交差が起きないため遷移なしとして `None`。onset レベル選択に到達しない。
- **入力値**: `TEMPS_20`, `[0.5]*20`, `phase_ref="A"`
  - **不正な理由**: 相が全区間で安定 (等温セグメント)、遷移が存在しない。
  - **実際の発生シナリオ**: 相構成が変化しない安定加熱区間。
- **期待される結果**: `estimate_transition(...) is None`
  - **システムの安全性**: 既存挙動 (L195-196) 不変。偽の転移温度を出さない。
- **テストの目的**: 修正が「定数分率→None」を退行させないこと (既存 `test_transition_constant_fraction_returns_none` L244 の無改変 green)。
  - **品質保証の観点**: false-positive 抑制の維持。
- 🔵 信頼性: 既存 `tests/test_thermal.py::test_transition_constant_fraction_returns_none` / 要件定義 §4 に一致。

### TC-T-E03: 空入力・単一フレームは None を返す (無改変)
- **エラーケースの概要**: 空トラジェクトリ / 単一フレーム (隣接対が作れない)。
  - **エラー処理の重要性**: 補間に必要な点数 (>=2) 不足を `None` へ一元化。
- **入力値**: `([], [], phase_ref="A")` と `([400.0], [0.5], phase_ref="A")`
  - **不正な理由**: 点数 < 2 で線形補間不能。
  - **実際の発生シナリオ**: 端末フレーム・空データ。
- **期待される結果**: 両者とも `None`
  - **システムの安全性**: 既存 L189-191 の縮退不変。onset レベル選択に到達しない。
- **テストの目的**: 修正が点数不足縮退を壊さないこと (既存 `test_transition_empty_or_single_frame_returns_none` L259 の無改変 green)。
  - **品質保証の観点**: 縮退の一貫性維持。
- 🔵 信頼性: 既存 `tests/test_thermal.py::test_transition_empty_or_single_frame_returns_none` に一致。

---

## 3. 境界値テストケース（端点一致・direction 境界・決定論・非有限）

### TC-T-B01: disappearing で分率がちょうど 90% (0.90) の端点一致でも一意な onset
- **境界値の意味**: あるフレームの分率が正確に 0.90 のとき、`_interpolate_crossing` の符号積 `<= 0` (端点一致含む) で一意に交差を採り 0 除算しないこと。
  - **境界値での動作保証**: 端点一致でも重複補間・NaN を生じない。
- **入力値**: `temperatures=[300.0, 350.0, 400.0, 450.0, 500.0]`, `fractions=[1.0, 0.9, 0.5, 0.1, 0.0]`, `phase_ref="A"`
  - **境界値選択の根拠**: index 1 の分率が丁度 0.90 (disappearing onset レベル)、index 2 が丁度 0.50 (midpoint)。端点一致の罠を突く。
  - **実際の使用場面**: 分率がグリッド上で丁度 90%/50% になるフレーム。
- **期待される結果**: `est is not None`、`est.direction == "disappearing"`、`est.onset == pytest.approx(350.0)`、`est.midpoint == pytest.approx(400.0)`、`est.onset < est.midpoint`、`math.isfinite(est.onset)`
  - **境界での正確性**: 90% 端点一致 → onset=350 K、50% 端点一致 → midpoint=400 K。0 除算なし。
  - **一貫した動作**: 既存 `test_transition_crossing_on_grid_point` (L332, 50% 端点一致) と同型で disappearing の 90% を担保。
- **テストの目的**: 端点一致時の disappearing onset 補間の堅牢性。
  - **堅牢性の確認**: 平坦対除外・符号積判定が 90% レベルでも正しく効く。
- 🟡 信頼性: 既存 `_interpolate_crossing` の端点一致契約 (L159-168) からの妥当な設計 / 要件定義 §4 エッジに依拠。

### TC-T-B02: direction 判定境界 (fractions[-1] == fractions[0]) は appearing 側 → onset 10% レベル
- **境界値の意味**: `direction = "appearing" if fractions[-1] >= fractions[0] else "disappearing"` の**等号境界**。始終端の分率が等しいとき appearing に倒れ、onset レベルは 10% になること。
  - **境界値での動作保証**: direction 判定の tie-break が onset レベル選択に一貫して反映される。
- **入力値**: `temperatures=[300.0, 350.0, 400.0, 450.0, 500.0]`, `fractions=[0.0, 0.5, 1.0, 0.5, 0.0]` (始終端 0.0 で等号) の増加区間を含むデータ, `phase_ref="A"`
  - **境界値選択の根拠**: `fractions[-1]==fractions[0]==0.0` で direction 判定が等号境界に当たる。前半上昇で 50%/10% 交差を持つ。
  - **実際の使用場面**: 出現後に再消滅する山型分率 (始終端が同値)。
- **期待される結果**: `est is not None`、`est.direction == "appearing"` (等号は appearing 側)、`est.onset < est.midpoint` (10% レベルを使用)
  - **境界での正確性**: 等号で appearing に確定し、onset は 10% 交差 (前半の低温側)。
  - **一貫した動作**: 既存 direction 判定 (L200-202) を変えないため、tie-break は現行どおり。
- **テストの目的**: onset レベル選択が direction 判定に厳密に従い、等号境界で分岐がぶれないことの固定。
  - **堅牢性の確認**: 修正で direction 判定を変えていないこと。
- 🟡 信頼性: 既存 direction 判定式 (L200-202) / 要件定義 §2 真理値表からの妥当な設計。

### TC-T-B03: disappearing で決定論ビット同一 (== 比較)
- **境界値の意味**: 純関数・決定論 (NFR-102) の境界検証。onset レベル選択を含め同一入力 2 回で `TransitionEstimate` が `==` (ビット同一)。
  - **境界値での動作保証**: onset の direction 依存化が非決定を持ち込まない。
- **入力値**: `TEMPS_20`, `SIGMOID_DOWN`, `phase_ref="A"` を 2 回
  - **境界値選択の根拠**: 決定論は「ほぼ同じ」不可 (pytest.approx 禁止)、`==` 比較。disappearing 経路 (90% 交差) の丸め揺らぎゼロを検証。
  - **実際の使用場面**: 監査・再現性 (同一データの再解析)。
- **期待される結果**: `est1 == est2` (frozen dataclass の全フィールド一致: onset/midpoint/sigma/direction/phase_ref)
  - **境界での正確性**: グローバル状態を持たない純関数。onset レベル選択も決定的。
  - **一貫した動作**: 既存 `test_transition_deterministic_bit_identical` (L369, appearing) の disappearing 版。
- **テストの目的**: disappearing 経路の決定論確認。
  - **堅牢性の確認**: 隠れ状態・順序依存なし。
- 🔵 信頼性: 要件定義 §3 (決定論 NFR-102) / 既存 `test_transition_deterministic_bit_identical` に一致。

### TC-T-B04: 非有限漏洩なし (onset/midpoint/sigma が有限 or onset=None)
- **境界値の意味**: onset レベル変更後も inf/nan を下流へ漏らさない (M1 教訓 / CLAUDE.md)。
  - **境界値での動作保証**: 有限値は `math.isfinite`、交差なしは `None` (両方向)。
- **入力値**: `TEMPS_20`, `SIGMOID_DOWN` / `SIGMOID_UP` (パラメータ化), `phase_ref="A"`
  - **境界値選択の根拠**: disappearing/appearing 双方で onset の有限性/None を検査。
  - **実際の使用場面**: JSON 配信・CSV 出力前の値純化前提 (非有限は禁止)。
- **期待される結果**: `est.onset is None or math.isfinite(est.onset)`、`math.isfinite(est.midpoint)`、`est.sigma is None or math.isfinite(est.sigma)`
  - **境界での正確性**: onset は有限 or None のみ。inf/nan を返さない。
  - **一貫した動作**: 既存の非有限漏洩検査方針を disappearing onset にも適用。
- **テストの目的**: 意味論修正が非有限漏洩を持ち込まないことの担保。
  - **堅牢性の確認**: 90% 交差経路でも inf/nan なし。
- 🔵 信頼性: 要件定義 §3 (非有限漏洩なし) / CLAUDE.md / 既存 `math.isfinite` 検査方針に一致。

---

## 4. 回帰テストケース（無退行・公開 API 非破壊）

> TC-T-R01〜R03 は**新規コードを書かず既存テストの無改変 green** で担保する (最小修正の証明)。

### TC-T-R01: 既存 thermal テスト 18 件が意味論修正後の期待値で green
- **何をテストするか**: `tests/test_thermal.py` の appearing/縮退/決定論/frozen 系が**無改変で green**、追加/改修は TC-T-N02 の onset 検証のみ。
- **期待される結果**: `uv run pytest tests/test_thermal.py` が全 green。appearing 系 (`test_transition_sigmoid_up_midpoint_onset_sigma` L134 / `test_transition_onset_before_midpoint_and_sigma_positive` L351)、`test_transition_crossing_on_grid_point` (L332)、`test_transition_deterministic_bit_identical` (L369)、baseline 系 (TB-*) は無改変で pass。
- **テストの目的**: onset レベルの direction 依存化が appearing・baseline を退行させないこと (TC-208-02)。
  - **確認ポイント**: 期待値変更は disappearing テストへの onset assertion 追加 (理由コメント付き) 1 点のみ。
- 🔵 信頼性: 既存 `tests/test_thermal.py` (18 件) / TC-208-02 / 要件定義 §3 に一致。

### TC-T-R02: e2e の appearing 経路 (onset <= midpoint) が無改変 green
- **何をテストするか**: `tests/test_m2_e2e.py::test_e2e_transition_temperature_estimated` (L403、相 B が 0→1 の **appearing**) が `estimate.onset <= estimate.midpoint`・`direction=="appearing"` を無改変で pass。
- **期待される結果**: appearing の onset は 10% 交差 (低温側) で不変のため、`onset <= midpoint` が維持され全 green。
- **テストの目的**: 統合経路 (公開 API 経由) で appearing 挙動が不変であることの担保。
  - **確認ポイント**: disappearing 修正が appearing の統合結線に波及しないこと。
- 🔵 信頼性: 既存 `tests/test_m2_e2e.py::test_e2e_transition_temperature_estimated` に一致。

### TC-T-R03: 公開 API 署名不変 (__all__ / TransitionEstimate フィールド)
- **何をテストするか**: `TransitionEstimate` のフィールド (`phase_ref/onset/midpoint/sigma/direction`) と `estimate_transition` の引数署名が不変、`__init__.py::__all__` / `sequential/__init__.py` の re-export が無変更 (`onset` フィールド名を維持)。
- **期待される結果**: `tests/test_m2_e2e.py` のシンボル同一性/`__all__` 昇順テスト、frozen テスト (`test_transition_estimate_is_frozen` L276) が無改変で green。
- **テストの目的**: 意味論のみの変更で公開 API を破壊しないこと (P2 / REQ-404 / interview Q9 の「命名変更回避」)。
  - **確認ポイント**: `onset` を `crossing_10pct` 等へ改名していないこと。フィールド追加/削除なし。
- 🔵 信頼性: 要件定義 §3 (公開 API 非破壊) / interview Q9 / 既存シンボルテストに一致。

---

## 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12
  - **言語選択の理由**: プロジェクト全体が Python >= 3.12 (uv 管理, src layout)。対象 `sequential/thermal.py` も Python + numpy。
  - **テストに適した機能**: `math.exp` でシグモイド合成データを生成、`pytest.approx` で交差温度近似、`==` で決定論、`math.isfinite` で非有限検査。
- **テストフレームワーク**: pytest >= 8 (+ pytest-cov)
  - **フレームワーク選択の理由**: 既存 29 テストファイルすべてが pytest。対象は既存 `tests/test_thermal.py` に追加/改修。
  - **テスト実行環境**: `uv run pytest tests/test_thermal.py` (単体) / `uv run pytest` (全体回帰、`uv sync --extra gsas` 前提)。
- 🔵 信頼性: `pyproject.toml` / `docs/spec/m3-operando/note.md` テスト要件 / 既存 `tests/test_thermal.py` に一致。

## テストケース実装時の指針（Python / pytest）

```python
import math
import pytest
from tsumugin.sequential.thermal import estimate_transition, TransitionEstimate

TEMPS_20 = [300.0 + 10.0 * i for i in range(20)]
SIGMOID_UP = [1.0 / (1.0 + math.exp(-(t - 400.0) / 15.0)) for t in TEMPS_20]
SIGMOID_DOWN = [1.0 / (1.0 + math.exp((t - 400.0) / 15.0)) for t in TEMPS_20]


def test_transition_disappearing_onset_is_transition_start_side():
    # 【テスト目的】: disappearing で onset=90% 交差 (遷移開始側=低温側) かつ onset<midpoint (TC-T-N02/N03) 🔵
    # 【テスト内容】: 減少シグモイド (1→0) で estimate_transition を呼び onset の意味論を検証
    # 【期待される動作】: onset ≈ 366.46 K (90% 交差)、onset < midpoint ≈ 400 K、direction="disappearing"
    est = estimate_transition(TEMPS_20, SIGMOID_DOWN, phase_ref="phase_A")
    assert est is not None                                    # 【検証項目】: 遷移が検出される 🔵
    assert est.direction == "disappearing"                   # 【検証項目】: 減少基調は消滅方向 🔵
    # Issue #4: disappearing の onset は 90% 交差 (遷移開始側)。旧実装の 10% 交差 (≈433 K, onset>midpoint) を解消。
    assert est.onset == pytest.approx(366.46, abs=1.0)       # 【検証項目】: onset=90% 交差=低温側 🔵
    assert est.onset < est.midpoint                          # 【検証項目】: onset は遷移開始側 (< midpoint) 🔵
    assert est.midpoint == pytest.approx(400.0, abs=10.0)    # 【検証項目】: midpoint は方向非依存 🔵
    assert est.sigma > 0.0 and math.isfinite(est.onset)      # 【検証項目】: σ>0・非有限漏洩なし 🔵


def test_transition_appearing_onset_unchanged():
    # 【テスト目的】: appearing の onset=10% 交差・onset<midpoint が無改変で維持 (TC-T-N01) 🔵
    est = estimate_transition(TEMPS_20, SIGMOID_UP, phase_ref="phase_A")
    assert est is not None and est.direction == "appearing"  # 【検証項目】: 出現方向 🔵
    assert est.onset < est.midpoint                          # 【検証項目】: appearing onset は低温側 (不変) 🔵


def test_transition_disappearing_ninety_pct_grid_point():
    # 【テスト目的】: disappearing の 90% 端点一致でも一意な onset・0 除算なし (TC-T-B01) 🟡
    est = estimate_transition(
        [300.0, 350.0, 400.0, 450.0, 500.0], [1.0, 0.9, 0.5, 0.1, 0.0], phase_ref="A"
    )
    assert est is not None and est.direction == "disappearing"
    assert est.onset == pytest.approx(350.0)                 # 【検証項目】: 90% 端点一致 onset=350 K 🟡
    assert est.midpoint == pytest.approx(400.0)              # 【検証項目】: 50% 端点一致 midpoint=400 K 🟡
    assert est.onset < est.midpoint and math.isfinite(est.onset)


def test_transition_disappearing_deterministic():
    # 【テスト目的】: disappearing 経路の決定論ビット同一 (TC-T-B03) 🔵
    e1 = estimate_transition(TEMPS_20, SIGMOID_DOWN, phase_ref="A")
    e2 = estimate_transition(TEMPS_20, SIGMOID_DOWN, phase_ref="A")
    assert e1 == e2                                          # 【検証項目】: 2 回呼び出しが == (決定論) 🔵
```

## 要件定義との対応関係

- **参照した機能概要**: 要件定義 §1 (disappearing の onset を 90% 交差=遷移開始側へ / appearing は 10% 維持)
- **参照した入力・出力仕様**: 要件定義 §2 (direction 別 onset レベル真理値表・具体温度値 366.46 K)
- **参照した制約条件**: 要件定義 §3 (最小修正・API 非破壊・決定論・非有限漏洩なし・無退行)
- **参照した使用例**: 要件定義 §4 (appearing/disappearing 基本パターン、90% 未達→None、端点一致、決定論)
- **参照した note**: `note.md` §0 (絶対制約)・§⚠️ (矛盾フラグ)・§5 (テスト影響評価)

---

## 品質判定

```
✅ 高品質:
- テストケース分類: 正常系(3)・異常系(3)・境界値(4)・回帰(3) を網羅 (計 13)
- 期待値定義: 全ケース具体値で明確 (onset=366.46 K / midpoint=400 K / direction / None 縮退)
- 技術選択: Python 3.12 + pytest (既存 tests/test_thermal.py と一致) で確定
- 実装可能性: 確実 (onset レベルの direction 依存化 1 点。既存データ SIGMOID_UP/DOWN を再利用)
- 信頼性レベル: 🔵 11/13 (要件定義 §2 / D-Q8 / interfaces.py L372-373 / 数値検証に直接依拠)、🟡 2/13 (端点一致・direction 境界の妥当設計)
- 特記: disappearing の期待順序は 90% 交差メカニズム + 数値検証に基づき onset<midpoint で固定。
        TASK-0024.md/TC-208-01 の「onset>midpoint」は誤記として差し戻し (note §⚠️ / requirements §⚠️)。
- 既存テストへの実質変更は「disappearing テストへの onset assertion 追加 (理由コメント付き)」1 点に限定。
```
