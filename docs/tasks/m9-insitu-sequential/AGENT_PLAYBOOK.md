# AI エージェント 高温 in situ 逐次 Rietveld 自動解析 指示書 (M9 AGENT_PLAYBOOK)

M9 成果物。AI エージェントが `tsumugin.insitu` を用いて温度/時間系列の粉末回折を逐次 Rietveld
自動解析するための指示書。GSAS-II "Parametric sequential fitting" チュートリアルと Jana2020
"CaTeO3 cyclic" 相当の解析 (格子 vs 温度・相転移・新相自動同定) を全自動で行うことを目標とする。
M7 (`AGENT_PLAYBOOK.md`) の単一フレーム自動 Rietveld を前提とし、その系列版を扱う。

## 0. 前提

- GSAS-II (GSASIIscriptable) が導入されていること (未導入なら該当関数が失敗 = refine_failed)。
- 新相自動同定は Materials Project キー (環境変数 `MATERIALS_PROJECT_API`) が必要。
- 入力: 各温度/時間点の観測データ + 装置パラメータ + 初期既知相 (CIF/EXP)。
- 出力: `SequentialRietveldResult` (フレーム別 Rwp/格子/相分率・変化点・自動出現相・ledger)。

## 1. 入力の組み立て

各フレームを `FrameSpec` に、初期既知相を `PhaseSpec` にする。

```python
from tsumugin.insitu import FrameSpec, SequentialConfig, PhaseIdConfig, run_sequential_rietveld
from tsumugin.autorietveld import PhaseSpec

frames = [
    FrameSpec(data_path="NB-LM01MO_030.XRDML", axis_value=30.0, data_format="XRDML"),
    FrameSpec(data_path="NB-LM01MO_060.XRDML", axis_value=60.0, data_format="XRDML"),
    # ... 全フレーム (軸値は温度 K or 時間)
]
alpha = PhaseSpec(structure_path="alpha_CaTeO3_H2O.cif", phase_name="alpha")
```

- **data_format**: XRDML (Panalytical 実験室 X 線) / FXYE (11BM 放射光) / GSAS / XYE。
- **axis_value**: 温度 (K) または時間。転移温度推定・熱膨張回帰に使う。cyclic (昇温→降温) は
  各フレームの実測温度を入れる (index でも可だが物理量は温度で解釈)。
- **装置パラメータ**: 既定 runner は data_path 隣接の `.instprm`/`.prm` を規約とする。系列共通の
  instprm を使う場合はその隣接規約に合わせるか、runner を注入する。

## 2. 呼び出しパターン

### 2.1 新相なしの逐次 (T-seq: CuCr₂O₄+CuO 型, 放射光)

```python
# 二相とも既知。ウォームスタート逐次のみ (相転移は 2 次 = 新相出現なし)。
config = SequentialConfig(warm_start=True, two_theta_limits=(4.5, 40.0))
result = run_sequential_rietveld(frames, [cuc r2o4, cuo], config=config)
# 期待: 各フレーム wRp 13–17% (チュートリアル同等)。b/c 比の収束を parametric で追う。
```
> 放射光 (Debye-Scherrer) は runner を注入して Radiation.XRAY_SYNCHROTRON/Geometry.DEBYE_SCHERRER
> にする (既定 runner は実験室 X 線 Bragg-Brentano)。

### 2.2 新相自動同定つき逐次 (T-cyc: CaTeO3 alpha→delta 型, 実験室 X 線)

```python
# 初期相 alpha のみ与える。delta は系列途中で自動同定・追加。
pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.02, top_k=1)
config = SequentialConfig(warm_start=True, phase_id=pid, changepoint_window=3)
result = run_sequential_rietveld(frames, [alpha], config=config, workdir="work/")
# 期待: 各フレーム wRp ~9%。delta (無水 CaTeO3) が転移フレームで appearances に出現。
for ap in result.appearances:
    print(ap.frame_index, ap.phase_name, ap.rwp_before, "->", ap.rwp_after, ap.evidence)
```

## 3. アルゴリズム (エージェントが理解すべき挙動)

1. **フレーム 0**: M7 フル段階解放で初期相を確立 (`run_auto_rietveld`)。
2. **フレーム i>0 (ウォームスタート)**: 直前フレームの精密化格子を `initial_cells` で引き継ぐ。
   格子が温度で滑らかにドリフトするため大域最適近傍から開始でき収束が速く安定 (チュートリアルの
   "copy results to next histogram" に相当)。
3. **変化点判定**: Rwp 履歴・格子履歴の robust z ジャンプで `detect_changepoint` が発火。加えて
   現フレーム Rwp が系列内最小 × `trigger_rwp_ratio` (既定 1.25) を超えたら新相探索を試みる
   (短系列で変化点窓 warm-up 前でも捉える頑健トリガ)。
4. **新相自動同定**: 変化点/Rwp ジャンプで `identify_and_materialize_phase` が MP から Ca-Te-O 相を
   同定し (既知相は除外)、上位候補を CIF に物質化。相集合に足して同フレームを再精密化する。
   **候補は `min_identify_score` (既定 0.0) で事前に足切りされる** — Dara スコアが負の候補
   (= その相を入れると未説明強度がむしろ増える = 残差を説明していない) は Rietveld を回すまでも
   なく落とす。**この閾値を下げてはならない**: 後段の選択が「最小 Rwp」であるため、これが無いと
   大分率で残差を舐める偽相が正解相に勝つ (実測 Ca3TeO6/CaTe3O8 が delta CaTeO3 に勝った)。
   足切りは ledger `m9_phaseid_skipped` に候補名/スコア付きで残る — **期待した相が追加されない
   時はまずここを読む** (スコアが負なら閾値でなくモデル/セルの問題)。
5. **受理基準 (過剰適合ガード)**: (1) 新相の相分率 > `frac_min` ∧ (2) Rwp が `rwp_eps` 超改善 ∧
   (3) validity.passed 維持。3 条件全てで採用。外れれば可逆に棄却 (提案≠適用)。以降のフレームは
   拡張相集合を引き継ぐ。
6. **決定論**: runner 固定・種固定で `SequentialRietveldResult` はビット同一・ledger `verify()` True。

## 4. パラメトリック解析 (物理量抽出)

```python
from tsumugin.insitu import analyze_phase, lattice_baseline, pseudo_variable_series

# 格子 vs 温度の熱膨張 + 相分率シグモイドの転移温度
pa = analyze_phase(result, "alpha", component="a")
print(pa.baseline.coefficients)      # [切片, 熱膨張勾配, ...]
print(pa.baseline.outlier_frames)    # 転移候補フレーム
print(pa.transition)                 # onset/midpoint±σ (appearing/disappearing 自動判定)

# 擬変数 (2 次転移の追跡, 例 CuCr₂O₄ の b/c 比収束)
axes, bc = pseudo_variable_series(result, "phase", lambda c: c[1] / c[2])
```

## 5. 結果の読み方と合否判定

- `result.frames[*].rwp` / `.gof`: フレーム別フィット品質。目標はチュートリアル値 ± マージン。
- `result.frames[*].changepoint` / `.changepoint_reasons`: 変化点フレームと発火指標。
- `result.appearances`: 自動同定・採用された新相 (`formula`/`source`/`rwp_before→after`/`evidence`)。
- `result.frames[*].phase_fractions`: 相分率トラジェクトリ (転移の定量)。
- `result.frames[*].refine_failed`: 失敗フレーム (直前成功フレームから warm start 継続)。
- `result.gpx_dir` / `result.frames[*].gpx_path`: **フレーム 1 枚ごとの精密化成果物**
  (2026-08-20 規定「全解析で gpx を全部保存する」)。棄却された相追加トライアル
  (`f0180_trial_<候補相>.gpx`) と整合の再精密化も同じ run ディレクトリに残り、
  `manifest.jsonl` が役割・相・Rwp の索引になる。**Rwp の表では切れない疑い**
  (段の無言 no-op・相分率 ~0 の棄却理由・偽相) は、この fit を開いて確かめる。
  `gpx_dir` を渡せば置き場所を指定でき、`save_gpx=false` で止められる (診断目的では止めない)。

## 6. 失敗時の対処

| 症状 | 原因候補 | 対処 |
|---|---|---|
| 転移後フレームで Rwp 高止まり | 新相が未追加 (MP キー未設定/元素系不足) | `MATERIALS_PROJECT_API` 設定・`elements` に想定元素を追加・CIF を直接 initial に足す |
| 新相が誤検出 (化学的に不自然) | 受理基準は残差説明力のみ判定 | ③ が化学的妥当性で退ける・`hull_cutoff_ev` を厳しく・`frac_min` を上げる |
| ウォームスタートで格子が発散 | 前フレームが崩壊格子を引き継ぎ | `run_auto_rietveld` の格子崩壊ガードが revert。warm_start=False で切り分け |
| 変化点が発火しない (短系列) | 変化点窓 warm-up | `changepoint_window` を小さく (3)・`trigger_rwp_ratio` を下げる |
| 放射光/中性子で Rwp 悪い | 既定 runner が実験室 X 線 | runner を注入し Radiation/Geometry を合わせる |

## 7. MCP 3 ツール閉ループ (③ = Claude Code/Codex)

`plugins/tsumugin/skills/insitu/SKILL.md` の手順を参照。エージェントは
`sequential_rietveld` → 結果を読む → (未指数残れば) `identify_and_add_phase` で候補を探し承認の上追加 →
再実行 → `parametric_fit` で転移特性、を反復駆動する。新相追加はユーザー承認を挟む (権限境界)。

## 7′. 電気化学制約 (FR-318, 電気化学 operando のみ)

skill 手順 3″ と同一 (安全上の指示は skill と本書で同内容を保つ):

- `alkali_budget` (MPR + 活物質質量 + 式量 + x₀) → per-frame 総アルカリ量目標。出力 `targets` を
  `charge_constraint.targets` へそのまま渡す。
- **モードは diagnose 既定で始める** (拘束せず `alkali_x_xrd` vs `alkali_x_echem` 乖離を出力)。
- **`soft` (ChemComp restraint) は使わない** — 現行 GSAS-II の headless 精密化では restraint
  penalty が最小二乗に取り込まれない (実測バグ; 自動で diagnose に縮退し警告)。
- **`lock_fractions` は明示 opt-in・ユーザー合意事項**: 2 相では相分率が完全決定され XRD は分率に
  寄与しなくなる (Rwp が一致度の検定量に変わる)。
- **sign は自分で正しく選ぶ — データからは検証できない** (state は積算電荷由来のため電極
  取り違えの自動検出は原理的に不可能)。既定 +1 = 正極規約。負極なら sign=-1 (明示確認警告)。
- **`x_total` が null のフレーム (echem 範囲外) は拘束されない** (外挿の捏造禁止)。
- **U/Uiso は精密化しない** (占有率と縮退し導出組成を汚染)。初期 Uiso 妥当帯 [1e-3, 0.05] Å² の
  事前警告に対処してから回す。
- アンカー A/B の ΔRwp 超過 → **x₀ 校正の提案** (`fr318_x0_calibration_proposal`, applied=False)。
  **提案≠適用** — 採用はユーザー承認。⚠ 提案が出るのは**占有率が実際に精密化された (esd 付き)
  アンカーのみ** — 既定は CIF 固定値 (`x_model`) で校正根拠にならない。校正するには anchor 相の
  PhaseSpec に `free_occupancy_labels` を設定 (Uiso は固定のまま)。
- Na/K ハイブリッドでは**電子数 = 総アルカリ (Na+K 和)** しか拘束できない — `site_labels` に
  両元素サイトを列挙し合算。分配は XRD 側精密化。

## 8. 再現ベンチマーク

`tests/insitu/test_engine_gsas.py` (`@pytest.mark.gsas`) が実データの合格基準を検証する。
データは `docs/benchmark/testdata/m9/`。

| 例 | tsumugin 自動 | チュートリアル |
|---|---|---|
| T-cyc CaTeO3 alpha (frame0, 実験室X線 XRDML) | **Rwp 13.4% / GOF 1.44** | wRp ~9.4% |
| T-seq CuCr₂O₄+CuO (17 フレーム, 放射光, 新相なし) | (検証中) | wRp 13–17% |
| T-cyc 全 14 フレーム + delta 自動同定 | (MP キー gate) | wRp ~8.7–9.5% |

**実験室 X 線 in situ の Rwp 収束で確立した設定** (CaTeO3 で 70%→13% 収束):
1. **Jana→CIF は標準セッティング** (`docs/benchmark/testdata/m9/jana_to_cif.py`)。非標準設定は GSAS 拒否。
2. **HighScore 処理 XRDML は Kα1 単色** instprm を使う (Kα2 除去済; Kα2 satellite が最大の系統残差)。
3. **背景 24 項** (`make_gsas_runner(background_coeffs=24)`; 実験室 X 線は背景複雑)。
4. **X 線は Lorentzian X,Y + Zero を追加解放** (recipe が自動; U,V,W のみでは 43% 止まり)。
