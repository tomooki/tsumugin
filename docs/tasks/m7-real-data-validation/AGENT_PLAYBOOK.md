# AI エージェント自動 Rietveld 解析 指示書 (AGENT_PLAYBOOK)

M7 成果物2。AI エージェントが `tsumugin.autorietveld` を用いて粉末回折 (X線/中性子) の
単相・多相 Rietveld 解析を全自動で行うための指示書。GSAS-II チュートリアル T1–T4 と同等の
Rwp/GOF/物理的妥当性を再現することを目標とする。

## 0. 前提

- 実行環境に GSAS-II (GSASIIscriptable) が導入されていること (未導入なら `GSASUnavailableError`)。
- 入力: 観測データファイル・装置パラメータファイル・相構造 (CIF または GSAS `.EXP`)。
- 出力: `AutoRietveldResult` (段階別 Rwp/GOF・最終格子・物理妥当性レポート・.gpx)。

## 1. 入力の集め方 (エージェントの判断基準)

エージェントは以下を特定して `HistogramSpec` / `PhaseSpec` を組み立てる。

### 1.1 放射源 `Radiation` の判定

| 手掛かり | Radiation |
|---|---|
| 装置ファイル `HTYPE PXC*` / CuKα・実験室 | `XRAY_LAB` |
| 放射光 (11BM 等)・短波長 (<0.7Å)・`.fxye` | `XRAY_SYNCHROTRON` |
| 装置ファイル `HTYPE PNC*` / 一定波長中性子 (D1a, λ=1.909 等) | `NEUTRON_CW` |
| `.instprm` に `difC`/`alpha`/`beta`/`sig-*` (飛行時間) / POWGEN 等 | `NEUTRON_TOF` |

### 1.2 ジオメトリ `Geometry` の判定

- 反射配置 (Bragg-Brentano, 実験室粉末回折計) → `BRAGG_BRENTANO` (試料変位 Shift を解放)
- 透過/毛細管/デバイシェラー (中性子・放射光キャピラリ) → `DEBYE_SCHERRER` (試料 X,Y 変位)

### 1.3 データ形式 `data_format`

- GSAS STD (`.xra`/`.raw`/`.gsa`/`.cwn`) → `"GSAS"`
- APS 11BM 等の `.fxye` → `"FXYE"`
- 2〜3 列テキスト → `"XYE"`

### 1.4 相構造 `PhaseSpec`

- CIF があれば `format_hint="CIF"`。GSAS `.EXP` 相なら `format_hint="EXP"`。
- CIF が無い場合: 元素一覧から `tsumugin.reference.identify_phases` / Materials Project で候補構造を得る。
- **混合占有サイト** (例 Fe/Al 同席) がある場合は `mixed_occupancy_groups` に
  同席原子ラベルの組を渡す (例 `(("Fe1","Al1"), ("Al2","Fe2"))`)。占有率和=1 制約と
  Uiso 等価制約が自動生成される。
- **温度差**: 複数ヒストグラムが異なる測定温度なら各 `HistogramSpec.temperature` を設定
  (静水圧歪み Dij で格子差を吸収)。

## 2. 呼び出しパターン

```python
from tsumugin.autorietveld import HistogramSpec, PhaseSpec, Radiation, Geometry
from tsumugin.autorietveld.engine import run_auto_rietveld

result = run_auto_rietveld(histograms, phases)   # レシピは自動生成
print(result.final_rwp, result.final_gof, result.validity.passed)
for s in result.stage_results:
    print(s.label, s.rwp, s.gof, "reverted" if s.reverted else "")
```

### 2.1 単相・実験室 X線 (T1 fluoroapatite 型)

```python
h = HistogramSpec(data_path="FAP.XRA", instrument_path="INST_XRY.PRM",
                  radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                  data_format="GSAS")
p = PhaseSpec(structure_path="FAP.EXP", phase_name="fap", format_hint="EXP")
result = run_auto_rietveld([h], [p])
# 期待: Rwp ~9.8% (チュートリアル 10.38%)
```

### 2.2 単相・CW 中性子 + 混合占有 (T2 garnet 型)

```python
h = HistogramSpec(data_path="garnet.raw", instrument_path="inst_d1a.prm",
                  radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER)
p = PhaseSpec(structure_path="garnet.cif", phase_name="garnet",
              mixed_occupancy_groups=(("Fe1","Al1"), ("Al2","Fe2")))
result = run_auto_rietveld([h], [p])
# 期待: Rwp ~4.3% (チュートリアル 5.18%), 占有率各サイト和=1
```

### 2.3 X線 + 中性子 joint (T3 PbSO4 型)

```python
hx = HistogramSpec(data_path="PBSO4.XRA", instrument_path="INST_XRY.PRM",
                   radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                   temperature=295.0)
hn = HistogramSpec(data_path="PBSO4.CWN", instrument_path="inst_d1a.prm",
                   radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER,
                   temperature=10.0)
p = PhaseSpec(structure_path="PbSO4.cif", phase_name="PbSO4")
result = run_auto_rietveld([hx, hn], [p])
# 期待: 合計 Rwp ~6.7% (チュートリアル 6.71%)
```

### 2.4 多相 + TOF (T4 NAC+CaF2 型)

```python
# 放射光 (11BM, FXYE) + TOF×2 (POWGEN, .gsa)。データリミットが必須。
hx = HistogramSpec(data_path="11BM_NAC.fxye", instrument_path="11bm_gsas.prm",
                   radiation=Radiation.XRAY_SYNCHROTRON, geometry=Geometry.DEBYE_SCHERRER,
                   data_format="FXYE", two_theta_limits=(2.5, 32.0), temperature=298.0)
ht1 = HistogramSpec(data_path="PG3_22048.gsa", instrument_path="POWGEN_1066.instprm",
                    radiation=Radiation.NEUTRON_TOF, geometry=Geometry.DEBYE_SCHERRER,
                    data_format="GSAS", two_theta_limits=(11750.0, 103794.0), temperature=298.0)
ht2 = HistogramSpec(data_path="PG3_22049.gsa", instrument_path="POWGEN_2665.instprm",
                    radiation=Radiation.NEUTRON_TOF, geometry=Geometry.DEBYE_SCHERRER, data_format="GSAS")
phases = [PhaseSpec(structure_path="NAC.cif", phase_name="NAC"),
          PhaseSpec(structure_path="CaF2.cif", phase_name="CaF2")]
# 多相は相分率(和=1)を分離して先に→格子→座標→Uiso→size/歪みを最後、と自動で並べ替わる。
result = run_auto_rietveld([hx, ht1, ht2], phases)
# 期待: Rwp ~13% (48% 平坦から収束)。TOF プロファイル初期化の手動調整で更に改善余地 (→tutorial 6.83%)
```

**重要**: `two_theta_limits` は各ヒストグラムの実効レンジ (放射光/CW は 2θ 度、TOF は TOF μs)。
低d/高角のノイズ領域を除外しないと平坦化する。範囲はデータのピーク可視域から決める。

## 3. 自動段階解放レシピ (エージェントが理解すべきアルゴリズム)

`build_recipe` が入力から段階列を自動生成する。普遍系列とアダプタ:

1. **S0 scale + 背景** (Chebyshev 既定 6 項)
2. **S1 格子 + 試料変位** (Bragg-Brentano→Shift / Debye-Scherrer→X,Y。多相→相分率和=1、温度差→Dij)
3. 混合占有の有無で分岐:
   - **混合占有あり**: 占有率(和=1) → Uiso(等価) → プロファイル+size/strain → 一般位置座標。
     *占有率が中性子散乱長コントラストを介して強く効くため早期に解放する。*
   - **混合占有なし**: プロファイル+size/strain → 座標 → Uiso。

各段階後に Rwp を確認し、**悪化したら直前状態へ revert して当該段階なしで継続**する
(ガードレール)。精密化失敗は Rwp=inf に変換され同様に revert される。

## 4. アルゴリズム上の要点 (T1–T4 実測で確立した教訓)

これらは自動化を成功させる鍵で、`autorietveld` に組み込み済み。エージェントは背景を理解しておく:

1. **背景項数**: 実験室 X 線は背景が支配的。初期 3 項では S1 で 19% 止まり、6 項で 13.7% まで
   下がる。既定 6 項。残差が大きければ増項を検討。
2. **原子フラグの累積**: GSAS-II の原子精密化フラグは「置換」型。座標(X)の後に Uiso(U) を
   `{"all":"U"}` で張ると X が消える。エンジンは per-atom で X/U/F を和集合累積する。
3. **座標は自由座標を持つ原子のみ**: 対称性で完全固定された特殊位置 (例 garnet 16a/24d,
   自由座標 0) の座標解放はセル発散を招く。`GetCSxinel` で判定し、Pnma 4c (自由座標 x,z) は
   精密化、固定位置は除外する。
4. **混合占有には制約が必須**: 占有率を無拘束で解放すると発散 (T2 で Rwp 99%)。
   占有率和=1 (`add_EqnConstr`) + Uiso 等価 (`add_EquivConstr`) で安定化し 4.3% を達成。
5. **占有率は Uiso より先** (中性子): Fe/Al は中性子散乱長が大きく異なる。占有率を先に
   合わせないと Uiso が誤差を吸収し収束が悪化する。
6. **size/微小歪みは高分解能ヒストグラム優先**: joint で低分解能中性子にも張ると過剰母数化
   で希釈 (T3 で 8.4%)。X線/放射光限定にすると 6.7% (純中性子時のみ中性子に張る)。
7. **温度差は Dij で吸収**: joint で測定温度が異なる場合、格子を共有したまま per-histogram の
   静水圧歪み Dij を解放して実効格子差を吸収する。
8. **TOF は装置プロファイルを精密化しない**: TOF (sig/alpha/beta) はキャリブレーション依存の
   ため解放せず、ピーク形状は最後の size/微小歪みで処理する (difC/Zero は固定)。
9. **データリミットが TOF/放射光多相では必須**: ノイズ領域 (放射光の高角、TOF の低d端) を
   `two_theta_limits` で除外しないと最小二乗がノイズに支配され**平坦化** (nvar が凍結し格子以降が
   噛まない)。T4 では 11BM を 2.5–32°、TOF 22048 を d≈0.52Å 以上に制限して 48% 平坦 → 収束。
10. **多相 (二相以上) は解放順序が単相と異なる**: 相分率 (各ヒストグラム和=1) を格子と**分離して
    先に**解放し、size/微小歪みを**最後**に解放する。相分率を格子と同時に解放すると噛まず、
    size/歪みを座標より先に張ると座標段階が悪化して revert する (T4 実測)。
11. **size/微小歪みは低分解能 CW 中性子のみ除外**: 多ヒストグラムでは低分解能 CW 中性子 (D1a 等)
    を外し、X線/放射光・**TOF (高分解能)** に張る。TOF は試料ピーク幅情報を持つため必須 (T4)。
12. **X 線は Lorentzian (X,Y) + Zero が必須** (M9 CaTeO3 実測): 実験室/放射光 X 線は Lorentzian 成分が
    支配的で、U,V,W (Gaussian) のみでは実測ピーク形状に合わず高止まりする (43% 止まり)。recipe は
    X 線データに対し U,V,W の後で **X,Y,Zero を別段階 (`profile_lorentzian`, revert ガード) で解放**する
    (同段階に混ぜると悪化時 U,V,W ごと revert され T3/T4 が回帰するため分離)。中性子/TOF はスキップ。
13. **実験室 X 線は背景項を多く** (M9): 背景が複雑で 6 項では不足。`make_gsas_runner(background_coeffs=24)`
    等で 20+ 項にする (CaTeO3 で 6→24 が Rwp を大きく下げた)。**Kα2 除去済データ (HighScore 等) は Kα1
    単色 instprm** を使う (Kα2 satellite の phantom が最大の系統残差)。

## 5. 結果の読み方と合否判定

- `result.final_rwp` / `result.final_gof`: 最終フィット品質。目標はチュートリアル値 ±マージン。
- `result.validity.passed`: 物理的妥当性 (格子 参照±0.5%、Uiso∈(0,0.1]、占有率∈[0,1]、
  制約和=1、収束) を全て満たすか。
- `result.validity.checks`: 項目別 (項目名, 合否, 詳細) — 不合格項目の特定に使う。
- `result.refined_cells`: 相ごとの精密化格子。文献値との照合に使う。
- `result.stage_results[*].reverted`: revert が起きた段階 (その段階のパラメータは寄与せず)。

## 6. 失敗時の対処 (エージェントの意思決定)

| 症状 | 原因候補 | 対処 |
|---|---|---|
| S1 以降 Rwp が下がらない | 構造モデル (特に O 位置) の誤り・空間群設定 | CIF の原子位置を確認。DFT 緩和格子ずれは Dij/歪みで吸収 |
| 占有率が [0,1] 外・発散 | 混合占有の制約未設定 | `mixed_occupancy_groups` を指定 (和=1/Uiso等価が自動生成) |
| 座標段階でセル発散 (revert) | 特殊位置の座標解放 | 自動で一般/部分特殊位置のみ解放。CIF の site symmetry を確認 |
| joint で Rwp が単相より悪い | 低分解能側への過剰母数化 | size/strain は自動で高分解能側限定。温度差なら temperature を設定 |
| 非収束 (converged=False) | 段階不足・母数過多 | max_cyc を増やす。妥当性 warnings を確認 |
| TOF で Rwp 高止まり | データ範囲 (低 d 雑音)・プロファイル | `two_theta_limits` で範囲制限。TOF は sig/X/Y を解放 |

## 7. 再現ベンチマーク

`tests/autorietveld/test_engine_t{1,2,3}.py` (`@pytest.mark.gsas`) が T1–T3 の合格基準を
検証する。データは `docs/benchmark/testdata/m7/` (取得手順は `docs/benchmark/README.md`)。

| 例 | tsumugin 自動 | チュートリアル |
|---|---|---|
| T1 fluoroapatite (単相ラボX線) | Rwp 9.83% / GOF 1.76 | 10.38% / 3.44 |
| T2 garnet (単相CW中性子+混合占有) | Rwp 4.33% / GOF 1.63 | 5.18% / 3.79 |
| T3 PbSO4 (X線+中性子 joint) | Rwp 6.66% / GOF 2.25 | 6.71% / 2.27 |
| T4 NAC+CaF2 (TOF+放射光 多相) | (Phase D 検証中) | 6.83% |

---

## 8. M8: MCP 3 ツール閉ループ (agentic 判断層)

M8 で「フィット結果を観測し次手を判断して再実行する」閉ループを 3 層に分離した
(`docs/design/m8-agentic-loop/architecture.md`)。エージェント (③ = Claude Code/Codex) は
**MCP 3 ツール**を反復駆動して解析を進める。ライブラリは LLM を呼び返さない (二重反転回避)。

### 8.1 閉ループの回し方

1. `auto_rietveld(histograms, phases, background_coeffs=6)` — spec を実行し構造化結果を得る
   (段階別/最終 Rwp・格子・validity・**spec ハンドル** = stateless echo)。
2. 結果 (Rwp 停滞・validity 項目・未指数ピーク等) と残差シグネチャから
   `propose_next_actions(result, features)` を呼び `ActionProposal[]` を得る (各提案に `safe` フラグ)。
3. **次手を自ら判断する**:
   - `safe=True` (SafeAction: 背景増項・パラメータ追加解放) は自明に採用してよい。
   - `safe=False` (ModelAction: リミット・相追加削除・構造改訂・混合占有割当) は**エージェントが
     判断**し、構造変更・相追加は**ユーザー承認**を挟む (§8.3 権限境界)。
4. 採った改訂を `refine_with_revisions(histograms, phases, actions, background_coeffs)` に渡して
   再実行し、`specs` ハンドルを次反復へ持ち回る。
5. 目標 Rwp 到達 / 改善停滞 / 予算上限で終了。

### 8.2 headless/CI 経路 (規則のみで回す)

構造判断が不要な範囲は `run_refinement_loop(histograms, phases, policy=RuleBasedPolicy())` で
決定論的に自律収束できる。SafeAction のみ自律適用し、ModelAction 提案は `open_proposals` に
申し送られる (③/人間へ)。受理基準は **Rwp 改善 ∧ validity 維持** (過剰適合ガード)。
種固定でビット同一・ledger `verify()` True (NFR-102/105)。

### 8.3 権限境界 (規則が担える範囲 — architecture.md §4.5)

| 判断 | 規則 (headless/RuleBasedPolicy) | ③ (Claude/人間) |
|---|---|---|
| 背景増項・パラメータ追加解放・停止 | ✅ 自律実行 (Rwp∧validity で自己検証) | 監督・上書き可 |
| 保守的初期リミット (`propose_initial_limits`) | 🟡 setup で提案+既定適用 | 採否・微調整 |
| mustrain/size の解放 | ✅ 解放して LSQ に探させる | 極端に鋭い相の初期値投入 |
| データリミット精密化・相追加/削除・混合占有割当 | ❌ 提案のみ (`safe=False`) | ✅ 判断・実行 |
| 構造改訂 (空間群/原子/原点)・事前知識 (R5) | ❌ | ✅ 判断・実行 |

**なぜ規則が構造判断をしないか**: 残差からは原因が一意に決まらない (同じ残差が複数原因と両立)。
規則は「間違えても revert される」安全・自己検証可・パラメトリックな手に厳格限定する。

### 8.4 Action の適用 (純変換)

各 `AnalysisAction` は `apply(AnalysisInput) -> AnalysisInput` の純変換で、spec を書き換える:
`SetLimits` は `two_theta_limits` を、`AddPhase(spec=...)` は相追加を、`ReviseStructure(phase,
{"structure_path": edited})` は ③ が編集した CIF への差し替えを表す。JSON 往復は
`refine_loop.serialization` (`action_to_dict`/`action_from_dict`)。
