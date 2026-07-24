# Issue #130: FR-313 discrimination の ② 露出 + 実データ GSAS 接続 (route X) — 設計

## 決定 (ユーザー確定)

**route X「backend に実 CIF を読ませる」**。discrimination 本体 (`operando/discrimination.py`) は
一切変えない。`PhaseInstance` に実構造参照を非破壊追加し、`GSASIIBackend` を実 CIF 分岐させる。

### 根拠 (調査で確定)

- `discriminate_interval` は `RefinementBackend` Protocol に完全抽象化 — `backend.refine(
  RefinementModel, max_cycles)` しか呼ばず GSAS 固有依存ゼロ。
- `GSASIIBackend` は実 GSAS-II を駆動する本物のブリッジだが、`_add_phases` (gsasii.py:312) が
  `_write_cif` で **P mmm・Ni 1 原子の CIF を毎回でっち上げる**。これは `PhaseInstance` が
  構造 (原子・空間群・CIF パス) を持たない設計の副産物。
- ⇒ でっち上げは必然でない。実構造を渡せる経路を与えればやめられる。`run_auto_rietveld` への
  載せ替え (旧 b2) は不要。

## 実装方針

### L1: `PhaseInstance.structure_ref: str | None = None`

末尾・既定 None・非破壊 (REQ-404 と同型、`lifecycle` フィールドと同じ規律)。CIF パスを保持。
`SimulatedBackend` は無視する (hkl_table を `phase_ref` で引くため影響ゼロ = 後方互換)。

### L2: `GSASIIBackend._add_phases` の実 CIF 分岐

```
structure_ref があれば:
    g2ph = gpx.add_phase(structure_ref, ...)   # 実 CIF (原子/空間群/参照セル)
    格子 (a/b/c/α/β/γ) を phase.lattice で上書き  # discrimination の warm-start 格子を反映
なければ:
    従来の _write_cif でっち上げ (SimulatedBackend 相当の格子/scale のみ判別)
```

cell+scale の解放フラグ設定・`_read_back` は現状のまま (実多原子相でも cell/scale は汎用的に
読める)。格子上書きは GSAS の cell 設定 API 経由 (`_apply_cell` ヘルパ)。

### L3: マーシャリング (numpy 層・非 gsas)

- `PhaseInstance.to_dict`/`from_dict` + `LatticeParams.to_dict`/`from_dict` (往復同型、
  `PhaseSpec.to_dict` パターン)。`structure_ref`/`occupancies`/`wt_frac` を含む。
- `FixedPhaseSpec.to_dict`/`from_dict` (`operando/cell_phases.py`)。
- `FrameSeries` の JSON 構築経路 (現状ゼロ): (a) 生 `two_theta`/`intensities` 配列 JSON、
  (b) データファイル群を `reference.io.load_pattern` で行スタックする新ローダ
  `frame_series_from_files`。

### L4: ② `discriminate` ツール (mcp/discriminate_tools.py 新設)

JSON 引数と「どの ② 出力から来るか」(到達可能性):
- `series`: {two_theta, intensities} 直渡し **or** {data_paths, data_format} ローダ経由
- `initial_phases`: [PhaseInstance dict] (相ごと structure_ref = CIF パス)
- `fixed_phases`: [FixedPhaseSpec dict] (既定 [])
- `frame_range`: [start, end]
- `config`: {close_threshold, high_r_threshold, seq_max_cycles, multistart{n_starts},
  physical_problem{...} | null, nested_arbitration{...} | null}
- `wavelength`: GSASIIBackend 波長 (既定値)
- 出力: DiscriminationResult → dict (verdict/delta_evidence/adjudicated_by/
  nested_delta_evidence/escalations/warnings + 両仮説の要約)。Hypothesis/MultistartResult/
  ArbitrationResult は既存 `*_to_dict` 再利用を先に確認、無ければ最小 summary dict に畳む
  (大配列は境界を跨がせない — §4.5)。
- **例外を送出しない**: `{"error","error_type"}` へ縮退 (② 不変条件)。空/不正入力を
  「正常」と答えない。

### L5: ③ 手順書

`skills/insitu` (進める) / `skills/operando-diagnose` (疑う) に「固溶体 vs 二相をいつ・どう
判別するか」を追記 (discriminate ツール + 各引数の出所)。両 PLAYBOOK 同期。

### L6: テスト

- numpy 層 (marshaling/ローダ): 非 gsas 単体、往復同型・決定論。
- `@pytest.mark.gsas` 新モジュール: 実 CIF (PbSO4 testdata) + `GSASIIBackend` 駆動の
  discrimination が実際に走り verdict を返すカナリア。structure_ref 分岐が実 CIF を読むこと。
- 変異実証: `PhaseInstance.structure_ref` 非破壊 (既存呼び出しビット同一) + `SimulatedBackend`
  無視。

## スコープ外 (宣言)

- **別空間群の 2 相反応** (端成分が異構造): discrimination の既存前提「端成分は `phase_ref`
  共有 = 同構造・別格子」を継承。異構造 2 相は元々スコープ外。
- **判別中の原子座標/占有率精密化**: FR-313 は格子連続性 vs 相共存の比較なので cell+scale
  解放が正しい DOF (原子解放はしない)。

## 到達可能性 (★不変条件)

`discriminate` の各引数は ③ が JSON で構成可能 (data_paths はファイルパス、initial_phases は
相同定/ユーザー入力、config は既定+調整)。LAYER1_FEATURES の nested 非露出宣言を
「`discriminate` で ② 露出済み (物理尤度 nested はそのオプトイン引数)」へ更新。

## 進め方

修正TDD → PR → code-review → 自動マージ。段階コミット L1→L6。実 GSAS は 1 フレーム秒オーダー
→ 区間×2仮説×multistart で分オーダー (gated 前提・カナリアは小グリッド/少フレーム)。
