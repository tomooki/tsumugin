# TASK-0027 TDD テストケース定義 — multistart/perturb (決定論摂動列)

**機能名**: multistart-perturb / **タスクID**: TASK-0027 / **要件名**: m3-operando
**フェーズ**: Phase 2 / **作成日**: 2026-07-04
**テスト先**: `tests/test_multistart_perturb.py` (新規)。実装 `src/tsumugin/multistart/perturb.py` と 1:1 対応。
既存テストファイルは**無改変**で回帰維持 (ベースライン 505 collected / 502 passed + @gsas 3 skip)。

> 全パスはプロジェクトルート相対。**【信頼性凡例】** 🔵 資料依拠ほぼ推測なし / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12 (uv 管理, src layout)。
  - **選択理由**: 既存コードベースが Python。摂動は `PhaseInstance`/`LatticeParams` の非破壊変換で表現、
    格子/対数グリッドは numpy/`math` で算出。🔵
  - **テストに適した機能**: `pytest.approx` による浮動小数近似、`dataclasses.FrozenInstanceError` による
    不変性検証、`==` によるビット同一 (決定論) 検証、`math.log10` による対数域検証。
- **テストフレームワーク**: pytest (>=8) + pytest-cov。
  - **選択理由**: 既存 `tests/` が全て pytest。設定は `pyproject.toml [tool.pytest.ini_options]`。🔵
  - **テスト実行環境**: `uv run pytest tests/test_multistart_perturb.py` (単体) / `uv run pytest` (全体回帰) /
    `uv run pytest --cov=tsumugin`。依存導入は `uv sync --extra gsas`。本タスクのコアは GSAS-II 非依存
    (`gsas` マーカー不要)。🔵
- 🔵 信頼性: `pyproject.toml` / `tests/test_simulated_backend.py` / `CLAUDE.md` に依拠。

### テストヘルパ (テスト内に用意)

```python
from tsumugin.model import PhaseInstance, LatticeParams

def _phase(ref="A", a=5.0, b=5.0, c=5.0, scale=1.0, occ=None):
    """基準 PhaseInstance を組む。occ は {site: 占有率}。"""
    return PhaseInstance(
        phase_ref=ref,
        lattice=LatticeParams(a=a, b=b, c=c),
        scale=scale,
        occupancies=(occ or {}),
    )
```

---

## 1. 正常系テストケース（基本的な動作）

### T-N01: generate_starts が n_starts 組を返す (相数保存)
- **何をテストするか**: `generate_starts((phase,), config=MultistartConfig(n_starts=8))` が長さ 8 の tuple を返し、
  各要素が入力と同じ相数 (1) を持つこと。
  - **期待される動作**: 戻り値は `tuple[tuple[PhaseInstance, ...], ...]`、外側 len==n_starts、内側 len==len(phases)。
- **入力値**: `phases=(_phase(),)`, `config=MultistartConfig(n_starts=8)`
  - **入力データの意味**: 既定 N=8 (FR-231) の基本ケース。単相。
- **期待される結果**: `len(starts) == 8`、全 `i` で `len(starts[i]) == 1`。
  - **期待結果の理由**: N 本の start × 各 start は元の相群と同数の相 (D1 / interfaces.py L165-169)。
- **テストの目的**: 出力の構造 (本数・相数保存) の確認。
  - **確認ポイント**: 相数・相順が全 start で保存される。
- 🔵 信頼性: requirements 2.3 / interfaces.py L165-169 / architecture.md D1 に依拠。

### T-N02: 摂動列が決定論 — 2 回生成でビット同一 (TC-201-01)
- **何をテストするか**: 同一 `(phases, config)` で `generate_starts` を 2 回呼び、全 start の格子/scale/占有率が
  ビット一致すること (乱数不使用の保証)。
  - **期待される動作**: `starts_a == starts_b` (dataclass の構造的等価、全数値 `==`)。
- **入力値**: `phases=(_phase(a=5.0,b=5.1,c=5.2, scale=1.0, occ={"Fe":0.8}),)`,
  `config=MultistartConfig(n_starts=8)`。2 回呼ぶ。
  - **入力データの意味**: 非対称格子 + 占有率あり = 3 摂動全てが効く代表入力。
- **期待される結果**: `starts_a == starts_b` (frozen dataclass 同士の `==`)。各 `i,j` で
  `starts_a[i][j].lattice.a == starts_b[i][j].lattice.a`、`.scale ==`、`.occupancies ==`。
  - **期待結果の理由**: 摂動は start index の純関数で乱数を含まない (NFR-102 / REQ-402 / TC-201-01)。
- **テストの目的**: 決定論・再現性 (ビット同一) の確認。**完了条件 1 / TC-201-01 の中核**。
  - **確認ポイント**: `random`/`np.random` 由来のブレがゼロ。dataclass の `==` が全フィールドを比較。
- 🔵 信頼性: acceptance-criteria TC-201-01 / requirements 3 / REQ-402 / NFR-102 に依拠。

### T-N03: i=0 が無摂動 (基準と同値) (TC-201-07)
- **何をテストするか**: 任意の N で `starts[0]` が入力 `phases` と同値であること (i=0 無摂動)。
  - **期待される動作**: `starts[0] == phases` (相ごとに格子/scale/占有率が基準と一致)。
- **入力値**: `phases=(_phase(a=5.0, scale=1.0, occ={"Fe":0.8}),)`, `config=MultistartConfig(n_starts=8)`
  - **入力データの意味**: i=0 の恒等性を単相で検証。
- **期待される結果**: `starts[0][0].lattice.a == 5.0`, `starts[0][0].scale == 1.0`,
  `starts[0][0].occupancies == {"Fe": 0.8}` (基準そのもの)。`starts[0] == phases` も可。
  - **期待結果の理由**: D1「i=0 は無摂動 (基準解)」/ interfaces.py L168。
- **テストの目的**: 基準解が start 集合に必ず含まれることの確認。
  - **確認ポイント**: δ=0/offset=0/lhs=0 が i=0 に割り当たる。基準値がビット一致 (近似でなく `==`)。
- 🔵 信頼性: acceptance-criteria TC-201-07 / architecture.md D1 L60 / interfaces.py L168 に依拠。

### T-N04: 格子摂動が ±lattice_frac の等間隔グリッド範囲内 (TC-201-01)
- **何をテストするか**: i≥1 の各 start で格子 a/b/c が基準の `[1-frac, 1+frac]` 倍の範囲内にあり、
  i によって異なる (グリッド上の点) こと。
  - **期待される動作**: `(1-frac) <= starts[i][0].lattice.a / base_a <= (1+frac)` が全 i で成立。
- **入力値**: `phases=(_phase(a=5.0,b=5.0,c=5.0),)`,
  `config=MultistartConfig(n_starts=8, spec=PerturbationSpec(lattice_frac=0.02))`
  - **入力データの意味**: lattice_frac=0.02 (既定) の代表。base_a=5.0。
- **期待される結果**: 全 `i` で `4.9 <= starts[i][0].lattice.a <= 5.1` (5.0×[0.98,1.02])。
  少なくとも 2 つの異なる i で `lattice.a` が異なる (グリッドが縮退しない)。角度は 90.0 のまま (非摂動)。
  - **期待結果の理由**: D1「格子 ±frac の等間隔グリッド」。摂動は相対スケール `a*(1+δ)`。
- **テストの目的**: 格子摂動の範囲と分散の確認。**TC-201-01 の格子部分**。
  - **確認ポイント**: 相対幅として正しく効く。b/c も同様。alpha/beta/gamma は不変。
- 🔵 信頼性: acceptance-criteria TC-201-01 / requirements 2.3・3 / architecture.md D1 に依拠。

### T-N05: scale 摂動が対数一様グリッドの範囲内 (TC-201-01)
- **何をテストするか**: i≥1 の各 start で `log10(scale_pert / base_scale)` が
  `[-scale_log_range, +scale_log_range]` 内にあること (対数域)。
  - **期待される動作**: `abs(log10(starts[i][0].scale / base_scale)) <= scale_log_range` が全 i で成立。
- **入力値**: `phases=(_phase(scale=2.0),)`,
  `config=MultistartConfig(n_starts=8, spec=PerturbationSpec(scale_log_range=0.5))`
  - **入力データの意味**: base_scale=2.0、scale_log_range=0.5 (既定)。10^±0.5=×0.316〜×3.16。
- **期待される結果**: 全 `i` で `abs(math.log10(starts[i][0].scale / 2.0)) <= 0.5 + 1e-9`。
  scale は常に正 (`> 0`)。少なくとも 2 つの異なる i で scale が異なる。
  - **期待結果の理由**: D1「scale の対数一様グリッド」。`scale * 10^offset`。
- **テストの目的**: scale 摂動が対数空間で範囲内に収まることの確認。**TC-201-01 の scale 部分**。
  - **確認ポイント**: 対数一様 (線形一様でない)。scale が負や 0 にならない。
- 🔵 信頼性: acceptance-criteria TC-201-01 / requirements 2.3 / architecture.md D1 に依拠。

### T-N06: 占有率摂動が [0,1] 内で occupancy_delta 幅 (TC-201-01)
- **何をテストするか**: i≥1 の各 start で占有率が `[0.0, 1.0]` 内に収まり (クリップ)、
  基準からの差が `occupancy_delta` 程度に収まること。
  - **期待される動作**: 全 site 値が `0.0 <= v <= 1.0`、`abs(v - base) <= occupancy_delta + 1e-9`。
- **入力値**: `phases=(_phase(occ={"Fe":0.5, "O":0.9}),)`,
  `config=MultistartConfig(n_starts=8, spec=PerturbationSpec(occupancy_delta=0.1))`
  - **入力データの意味**: 中央値 0.5 と上端寄り 0.9。occupancy_delta=0.1 (既定)。
- **期待される結果**: 全 `i`・全 site で `0.0 <= v <= 1.0` かつ `abs(v - base) <= 0.1 + 1e-9`。
  占有率のキー集合は基準と同一 (site 数・名保存)。
  - **期待結果の理由**: D1「占有率は固定ラテン超方格テーブル」。物理範囲 [0,1] クリップ (requirements 4.2)。
- **テストの目的**: 占有率摂動の範囲・クリップ・site 保存の確認。**TC-201-01 の占有率部分**。
  - **確認ポイント**: LHS 幅を超えない。site キーが失われない。
- 🔵 信頼性: acceptance-criteria TC-201-01 / requirements 2.3・4.2 / architecture.md D1 に依拠 (幅は 🟡)。

### T-N07: 多相 phases で各相に摂動が適用される (完了条件 4)
- **何をテストするか**: `phases=(A, B)` の 2 相入力で、i≥1 の各 start が A/B 両相に摂動を持つこと。
  - **期待される動作**: 各 start は 2 相を保持し、i≥1 では両相とも基準と異なる (少なくとも 1 パラメータ)。
- **入力値**: `phases=(_phase("A", a=5.0, scale=1.0), _phase("B", a=8.0, scale=0.5))`,
  `config=MultistartConfig(n_starts=4)`
  - **入力データの意味**: 異なる格子/scale の 2 相 = 多相摂動の代表。
- **期待される結果**: 全 `i` で `len(starts[i]) == 2`、`starts[i][0].phase_ref == "A"`,
  `starts[i][1].phase_ref == "B"` (相順保存)。ある i≥1 で A・B ともに基準と異なる摂動を持つ。
  i=0 では両相とも基準 (`starts[0][0].lattice.a == 5.0`, `starts[0][1].lattice.a == 8.0`)。
  - **期待結果の理由**: 完了条件「多相 phases でも各相に摂動適用」/ D1 の LHS は相ごと独立摂動。
- **テストの目的**: 多相での摂動適用と相順・phase_ref 保存の確認。
  - **確認ポイント**: 相ごとに決定論的だが独立な摂動 (全相同一値でない方が望ましい 🟡)。
- 🟡 信頼性: TASK-0027 完了条件 4 / architecture.md D1 に依拠 (相ごとオフセット式は 🟡 設計裁量)。

### T-N08: PerturbationSpec の既定値・明示値・フィールド保持
- **何をテストするか**: `PerturbationSpec` が既定値と明示値で生成でき各フィールドを保持すること。
  - **期待される動作**: 既定 → (0.02, 0.5, 0.1)、明示 → 指定値。
- **入力値**: `PerturbationSpec()` / `PerturbationSpec(lattice_frac=0.05, scale_log_range=1.0, occupancy_delta=0.2)`
  - **入力データの意味**: 既定値が interfaces.py L131-133 と一致するか、任意値を保持するか。
- **期待される結果**: 既定 → `lattice_frac==0.02`, `scale_log_range==0.5`, `occupancy_delta==0.1`。
  明示 → 各値を保持。
  - **期待結果の理由**: interfaces.py L126-133 の既定値契約。
- **テストの目的**: 設定 dataclass の既定・保持の確認。
  - **確認ポイント**: 既定値が設計と一致。
- 🔵 信頼性: interfaces.py L126-133 / requirements 2.1 に依拠。

### T-N09: MultistartConfig の既定値・ネスト既定・フィールド保持
- **何をテストするか**: `MultistartConfig` が既定値 (n_starts=8, spec=PerturbationSpec(), basin_rel_tol=1e-2,
  ms_max_cycles=15) で生成でき、ネストした `spec` 既定を持つこと。
  - **期待される動作**: 既定 → 4 フィールドが interfaces.py L136-141 と一致。
- **入力値**: `MultistartConfig()` / `MultistartConfig(n_starts=16, spec=PerturbationSpec(lattice_frac=0.05))`
  - **入力データの意味**: 既定と、n_starts 上限 16 (FR-231) + カスタム spec。
- **期待される結果**: 既定 → `n_starts==8`, `basin_rel_tol==1e-2`, `ms_max_cycles==15`,
  `spec.lattice_frac==0.02`。明示 → `n_starts==16`, `spec.lattice_frac==0.05`。
  - **期待結果の理由**: interfaces.py L135-141 の既定値契約。`basin_rel_tol`/`ms_max_cycles` は本タスクでは器のみ。
- **テストの目的**: 設定 dataclass のネスト既定・保持の確認。
  - **確認ポイント**: `spec` の既定が `PerturbationSpec()` (frozen 共有で安全)。
- 🔵 信頼性: interfaces.py L135-141 / requirements 2.2 に依拠。

### T-N10: 全 start が相互に異なる (摂動の分散、単一 basin 準備)
- **何をテストするか**: N=8 で生成した start 群が (i=0 基準を含めて) 相互に異なる初期値を持つこと
  (縮退して全部同じにならない)。
  - **期待される動作**: 少なくとも格子 or scale or 占有率のいずれかで各 start が区別可能。
- **入力値**: `phases=(_phase(a=5.0, scale=1.0, occ={"Fe":0.5}),)`, `config=MultistartConfig(n_starts=8)`
  - **入力データの意味**: 3 摂動全てが効く単相で分散を検証。
- **期待される結果**: `starts` の各要素をキー化した集合 (例: `(a, scale, tuple(sorted(occ.items())))`) の
  重複が過度でない (少なくとも i=0 と i=1 は異なる)。i≥1 は基準と異なる。
  - **期待結果の理由**: マルチスタートの意義は初期値分散。全同一だと単一 start と等価になる。
- **テストの目的**: 摂動グリッドが有効な分散を生む確認。
  - **確認ポイント**: グリッド刻みが 0 に潰れない (n_starts に対し適切に配分)。
- 🟡 信頼性: architecture.md D1 (グリッド分散) / requirements 1 から妥当推測 (具体分散量は 🟡)。

---

## 2. 異常系テストケース（エラーハンドリング / 頑健性）

### T-E01: 空 occupancies の相は占有率摂動をスキップ (クラッシュしない)
- **エラーケースの概要**: `occupancies == {}` の相に対し占有率摂動を試みても例外を出さず、空のまま返す。
  - **エラー処理の重要性**: 占有率を持たない相 (占有率フィット対象外) でもマルチスタートは動くべき。
- **入力値**: `phases=(_phase(occ={}),)`, `config=MultistartConfig(n_starts=8)`
  - **不正な理由**: 不正ではないが摂動対象が欠けた境界入力。
  - **実際の発生シナリオ**: 占有率を精密化しない相 (格子/scale のみ) の通常運用。
- **期待される結果**: 例外なし。全 start で `starts[i][0].occupancies == {}`。格子/scale は摂動される。
  - **システムの安全性**: 空 dict への操作で `KeyError`/`ZeroDivisionError` を起こさない。
- **テストの目的**: 占有率なし相での頑健性確認。
  - **品質保証の観点**: 部分的に摂動対象を欠く入力でも決定論的に動く。
- 🟡 信頼性: requirements 4.2 (空 occupancies 挙動) からの妥当推測。

### T-E02: 占有率 [0,1] 境界のクリップ (上端 1.0 / 下端 0.0)
- **エラーケースの概要**: 基準占有率が 1.0 or 0.0 近傍のとき、LHS 加算で範囲外に出る値を [0,1] にクリップ。
  - **エラー処理の重要性**: 占有率は物理的に [0,1]。範囲外値は精密化を不正にする。
- **入力値**: `phases=(_phase(occ={"Fe":1.0, "O":0.0}),)`,
  `config=MultistartConfig(n_starts=8, spec=PerturbationSpec(occupancy_delta=0.1))`
  - **不正な理由**: 摂動を加えると 1.0+δ>1 や 0.0-δ<0 が発生しうる境界。
  - **実際の発生シナリオ**: 完全占有 site (occ=1.0) や空孔 site (occ=0.0)。
- **期待される結果**: 全 start・全 site で `0.0 <= v <= 1.0` を厳守 (`min(max(v,0.0),1.0)` 相当)。
  1.0 の site は最大でも 1.0、0.0 の site は最小でも 0.0。
  - **システムの安全性**: 非物理的占有率を後続 refine へ流さない。
- **テストの目的**: 占有率クリップ境界の正確性確認。
  - **品質保証の観点**: 境界占有率で沈黙して範囲外値を返さない。
- 🟡 信頼性: requirements 4.2 / architecture.md D1 (占有率 [0,1]) からの妥当推測 (クリップは requirements 明記)。

---

## 3. 境界値テストケース（最小値・境界・null・回帰）

### T-B01: N=1 縮退 — 基準 1 組のみ (TC-201-07 / EDGE-101)
- **境界値の意味**: `n_starts=1` はマルチスタートの最小本数。摂動なし 1 本 (基準解のみ、basin=1 相当)。
  - **境界値での動作保証**: N-1=0 の 0 除算を回避し、基準をそのまま返す。
- **入力値**: `phases=(_phase(a=5.0, scale=1.0, occ={"Fe":0.8}),)`, `config=MultistartConfig(n_starts=1)`
  - **境界値選択の根拠**: EDGE-101 の N=1 縮退。グリッド分母が退化する最小ケース。
  - **実際の使用場面**: マルチスタートを実質無効化 (単一初期値) する設定。
- **期待される結果**: `len(starts) == 1`、`starts[0] == phases` (基準と同値、摂動なし)。例外なし。
  - **境界での正確性**: 0 除算・空グリッドを起こさず基準 1 組を返す。
  - **一貫した動作**: i=0 無摂動の原則が N=1 でも保たれる。
- **テストの目的**: N=1 縮退の確認。**完了条件 3 / TC-201-07 / EDGE-101**。
  - **堅牢性の確認**: 最小本数で破綻しない。
- 🔵 信頼性: acceptance-criteria TC-201-07 / requirements EDGE-101 / architecture.md D1 に依拠。

### T-B02: 入力 phases が非破壊 (呼び出し後も不変) (P2 / REQ-404)
- **境界値の意味**: 非破壊性の境界。`generate_starts` が入力を書き換えない。
  - **境界値での動作保証**: 入力 `phases` / `LatticeParams` / `occupancies` が呼び出し前後で不変。
- **入力値**: `base = _phase(a=5.0, scale=1.0, occ={"Fe":0.8})`, `phases=(base,)` を保持し
  `generate_starts(phases, config=MultistartConfig(n_starts=8))` 実行後に `base` を再検査。
  - **境界値選択の根拠**: frozen dataclass でも `occupancies` dict の in-place 変更は起こりうる (誤実装の罠)。
  - **実際の使用場面**: 同一 `phases` を複数回・複数 config で使い回す運用。
- **期待される結果**: 実行後も `base.lattice.a == 5.0`, `base.scale == 1.0`, `base.occupancies == {"Fe":0.8}`。
  `starts[0][0]` が `base` と同値だが、i≥1 の摂動が `base` に波及しない。
  - **境界での正確性**: 新インスタンス生成 (with_updates / 新 dict) で入力から独立。
  - **一貫した動作**: 呼び出し回数に依らず入力が保たれる。
- **テストの目的**: 非破壊性 (P2 / REQ-404) の確認。
  - **堅牢性の確認**: 副作用ゼロの純関数であること。
- 🔵 信頼性: requirements 3 (非破壊) / CLAUDE.md P2 / REQ-404 に依拠。

### T-B03: PerturbationSpec / MultistartConfig が frozen (再代入で FrozenInstanceError)
- **境界値の意味**: 不変値オブジェクトへの再代入拒否。
  - **境界値での動作保証**: frozen 属性の書き換え不可。
- **入力値**: `spec.lattice_frac = 0.1` / `config.n_starts = 2` への代入。
  - **境界値選択の根拠**: CLAUDE.md「frozen dataclass + with_updates」規約の遵守確認。
  - **実際の使用場面**: 設定の誤った mutation を型システムで防ぐ。
- **期待される結果**: いずれも `pytest.raises(dataclasses.FrozenInstanceError)`。
  - **境界での正確性**: `@dataclass(frozen=True)` が効いている。
- **テストの目的**: 設定 dataclass の不変性確認。
  - **堅牢性の確認**: 状態の不変性 (P2) を保つ。
- 🔵 信頼性: CLAUDE.md (frozen 規約) / interfaces.py L126・135 / 既存 frozen 検証パターンに依拠。

### T-B04: n_starts=2 の最小非退化グリッド (i=0 基準 + i=1 摂動)
- **境界値の意味**: 摂動が発生する最小本数 (N=2)。グリッド端点 2 点。
  - **境界値での動作保証**: N=2 で i=0 基準・i=1 摂動が明確に分かれる。
- **入力値**: `phases=(_phase(a=5.0, scale=1.0),)`, `config=MultistartConfig(n_starts=2)`
  - **境界値選択の根拠**: N=1 (縮退) と N=8 (通常) の間の最小摂動ケース。分母 N-1=1。
  - **実際の使用場面**: 軽量マルチスタート (2 本) 設定。
- **期待される結果**: `len(starts)==2`、`starts[0]==phases` (基準)、`starts[1]` は摂動あり
  (格子 or scale が基準と異なる、範囲内)。
  - **境界での正確性**: N-1=1 の分母で 0 除算せず、グリッド 2 点が生成される。
  - **一貫した動作**: i=0 基準の原則が N=2 でも保たれる。
- **テストの目的**: 最小摂動本数での境界動作確認。
  - **堅牢性の確認**: グリッド端点処理が N の小さい側で破綻しない。
- 🟡 信頼性: architecture.md D1 (等間隔グリッド) / EDGE-101 の隣接ケースから妥当推測。

### T-B05: 全体回帰 — 既存 505 collected を無退行維持
- **境界値の意味**: 新規モジュール追加が既存資産を壊さないゲート。
  - **境界値での動作保証**: 既存テスト無改変で全 green、collected 数は新規分のみ増加。
- **入力値**: `uv run pytest` (全体)。
  - **境界値選択の根拠**: `multistart/` は純新規モジュールで既存 API に触れない (フィールド追加なし)。
  - **実際の使用場面**: TASK-0027 完了ゲート。
- **期待される結果**: ベースライン **505 collected** (502 passed + @gsas 3 skip) が維持され、
  新規 `tests/test_multistart_perturb.py` 分だけ collected/passed が増える。既存テストファイル無改変。
  - **境界での正確性**: import 追加・`multistart/__init__.py` 新設が既存 collection を壊さない。
  - **一貫した動作**: 既存 502 passed が引き続き green。
- **テストの目的**: 非破壊 (純新規追加) の最終確認。
  - **堅牢性の確認**: 既存資産無退行。
- 🔵 信頼性: CLAUDE.md 不変条件 / REQ-404 / note.md ベースライン計測 (505) に依拠。

### T-B06: scale の対数一様性 (中央 index が基準近傍・端が対数域端)
- **境界値の意味**: 対数グリッドの中央/端の境界。線形一様でなく対数一様であることの確認。
  - **境界値での動作保証**: グリッドが log10 空間で等間隔配置される。
- **入力値**: `phases=(_phase(scale=1.0),)`,
  `config=MultistartConfig(n_starts=9, spec=PerturbationSpec(scale_log_range=1.0))` (奇数 N で中央 index あり)
  - **境界値選択の根拠**: N=9 なら i の分布に中央点が存在。log10 域 [-1,1] = ×0.1〜×10。
  - **実際の使用場面**: 広い scale 不確かさ (対数域 1.0) の探索。
- **期待される結果**: 全 i で `abs(log10(scale_i / 1.0)) <= 1.0 + 1e-9`。
  offset の集合が log10 空間で概ね等間隔 (隣接 offset 差がほぼ一定) 🟡。
  - **境界での正確性**: `scale * 10^offset` の対数配置。線形 (`scale*(1+x)`) でない。
  - **一貫した動作**: 端 index で対数域端に到達、中央付近で基準 (1.0) 近傍。
- **テストの目的**: scale 摂動の対数一様性 (D1) の確認。
  - **堅牢性の確認**: 対数グリッドの端点・中央が正しい。
- 🟡 信頼性: architecture.md D1 (対数一様グリッド) / requirements 2.3 に依拠 (等間隔の具体配置は 🟡)。

---

## テストケースサマリー

| 分類 | 件数 | テストID |
|---|---|---|
| 正常系 (基本動作) | 10 | T-N01〜T-N10 |
| 異常系 (頑健性) | 2 | T-E01〜T-E02 |
| 境界値 (境界・null・回帰) | 6 | T-B01〜T-B06 |
| **合計** | **18** | |

### 受け入れ基準 (TC-201 系) への対応

| AC | 内容 | 対応テスト |
|---|---|---|
| TC-201-01 | N=8 摂動列が決定論 (2 回生成ビット同一)、格子±幅/scale 対数一様/占有率 LHS の範囲内 | T-N02 (決定論), T-N04 (格子), T-N05 (scale), T-N06 (占有率), T-N01 (構造) |
| TC-201-07 | N=1 縮退 (摂動なし 1 本) | T-B01, T-N03 (i=0 無摂動) |
| 完了条件: 多相各相摂動 | 多相 phases でも各相に摂動適用 | T-N07 |
| 完了条件: [0,1] クリップ | 占有率 [0,1] クリップ | T-N06, T-E02 |
| P2/REQ-404 非破壊 | 入力 phases 不変・既存無退行 | T-B02, T-B05 |
| (TASK-0028 で主対象) | TC-201-02〜06 (basin 収束/双峰/昇格/発散除外/metrics) | 本タスク対象外 (摂動列供給のみ) |

### 要件定義との対応関係
- **参照した機能概要**: requirements.md §1 (決定論的初期値摂動列生成 / FR-230 マルチスタート)
- **参照した入力・出力仕様**: requirements.md §2.1〜2.4 (PerturbationSpec / MultistartConfig /
  generate_starts / データフロー)
- **参照した制約条件**: requirements.md §3 (乱数不使用・ビット同一・範囲/クリップ・非破壊・無退行 505・numpy のみ)
- **参照した使用例**: requirements.md §4 (単相/多相/決定論/N=1 縮退/占有率境界)

### 品質判定
```
✅ 高品質:
- テストケース分類: 正常系 10 / 異常系 2 / 境界値 6 で網羅 (構造・決定論・3 摂動の範囲・多相・
  N=1 縮退・非破壊・クリップ・frozen・回帰)
- 期待値定義: 各ケースで具体値・許容幅・比較演算子を明記 (== / <= / approx / raises / log10 域)
- 技術選択: Python 3.12 + pytest 確定 (既存資産準拠)
- 実装可能性: frozen dataclass + index 純関数グリッド + with_updates 非破壊生成で確実に実現
- 信頼性レベル: 🔵 が主 (受け入れ基準 TC-201-01/07 と 1:1)。🟡 は摂動幅具体値・相ごとオフセット式・
  対数グリッド配置・占有率境界に限定
```
**信頼性分布**: 🔵 11 / 🟡 7 / 🔴 0。

**次のお勧めステップ**: `/tsumiki:tdd-red m3-operando TASK-0027` で Red フェーズ (失敗テスト作成) を開始します。
