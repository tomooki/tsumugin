# M9 高温 in situ 逐次 Rietveld 自動解析 要件定義 (EARS)

対象: `tsumugin.insitu` (逐次実構造 Rietveld + 相同定→PhaseSpec 物質化 + パラメトリック解析) +
`autorietveld` 拡張 (initial_cells) + `reference.io` (XRDML) + MCP 3 ツール + Claude Code plugin。
仕様書 (正) `docs/tsumugin_spec_v0.3.md` の FR-301〜323 (シーケンシャル) / FR-100〜117 (相同定) に対応。

## 1. ユーザーストーリー

- 研究者として、高温/時間 in situ 粉末回折の温度系列を**初期相だけ指定すれば全自動で逐次
  Rietveld 精密化**し、途中で出現する相 (脱水相・高温多形) を自動で見つけて追加してほしい。
- 各温度の格子・相分率と**相転移温度**を自動抽出し、チュートリアル同等の Rwp を達成してほしい。
- 判断 (新相の採否・構造改訂) は AI エージェントと人間の介入点を明示した閉ループで進めたい。

## 2. 機能要件 (EARS)

### 2.1 逐次実構造 Rietveld (通常)
- **REQ-901** `run_sequential_rietveld` は、フレーム列と初期相を受け取ったとき、先頭から単一パスで
  各フレームを実構造 Rietveld 精密化し `SequentialRietveldResult` を返さねばならない。
- **REQ-902** システムは、フレーム i>0 のとき、直前成功フレームの精密化格子を次フレームの初期格子に
  引き継が (ウォームスタート) ねばならない (`warm_start=True` 時)。
- **REQ-903** システムは、精密化失敗フレームを例外化せず `refine_failed=True` (rwp/gof=inf) で伝播し、
  直前成功フレームからウォームスタートを継続せねばならない。

### 2.2 変化点と新相自動同定
- **REQ-904** システムは、Rwp/格子履歴の robust z ジャンプ、または現フレーム Rwp が系列内最小の
  `trigger_rwp_ratio` 倍超のとき、新相探索を試みねばならない (`phase_id` 有効時)。
- **REQ-905** システムは、新相探索で Materials Project から候補相を同定し、既知相を除外した上位候補を
  CIF に物質化して `PhaseSpec` を生成せねばならない (相同定→精密化の配線)。
- **REQ-906** システムは、新相を追加して再精密化し、**(1) 新相の相分率 > `frac_min` ∧ (2) Rwp が
  `rwp_eps` 超改善 ∧ (3) validity.passed 維持** を全て満たすときのみ採用せねばならない (過剰適合ガード)。
- **REQ-907** システムは、受理基準を満たさない相追加を可逆に棄却し (相集合据え置き)、試行を ledger に
  記録せねばならない (提案≠適用)。
- **WHERE** MP キー未設定/pymatgen 不在のとき、システムは相追加を error として飛ばし残りの逐次解析を
  継続せねばならない (`@pytest.mark.gsas` と同様の gate)。

### 2.3 パラメトリック解析
- **REQ-908** `analyze_phase`/`lattice_baseline` は、相の格子成分を軸 (温度) に対して多項式回帰し
  熱膨張係数と逸脱フレーム (転移候補) を返さねばならない (`sequential.thermal` 再利用)。
- **REQ-909** `transition_from_fractions` は、相分率シグモイドから転移 onset/midpoint±σ を推定し、
  交差が無い/点数不足なら None を返さねばならない。

### 2.4 入出力・境界
- **REQ-910** `reference.io.parse_xrdml/load_xrdml` は Panalytical XRDML を `(two_theta, intensity)` に
  読まねばならない。`load_pattern` は data_format でローダーを選ばねばならない。
- **REQ-911** `autorietveld.run_auto_rietveld` は `initial_cells` (相名→絶対格子) を受け取り、精密化前に
  各相の初期格子を設定せねばならない (ウォームスタート; 既定 None で従来動作)。
- **REQ-912** MCP は `sequential_rietveld`/`identify_and_add_phase`/`parametric_fit` の 3 ツールを
  素の型 dict で公開せねばならない (SDK 非依存、閉ループ丸ごとは出さない)。

## 3. 非機能要件 (仕様継承)
- **NFR-102 再現性**: runner 固定・種固定で `SequentialRietveldResult` はビット同一。
- **NFR-105**: ledger は追記専用ハッシュチェーン (`verify()` True)。
- **P2 非破壊**: 相追加/棄却は可逆。削除・上書き API を実装しない。
- **コア numpy-only**: `insitu.model`/`parametric`/`phaseid` の numpy 部は numpy のみ。GSAS は
  `engine` の runner 内、MP/pymatgen は `phaseid` の遅延 import 境界内。

## 4. 合格基準 (実データ検証)
- **AC-1** T-seq CuCr₂O₄+CuO (17 フレーム, 11BM 放射光): 各フレーム wRp ≤ 17% (チュートリアル帯)。
- **AC-2** T-cyc CaTeO3 (14 フレーム, 実験室 X 線): 各フレーム wRp ≲ 10%、**delta 無水相が転移
  フレームで `appearances` に自動出現** (MP キー設定時)。
- **AC-3** 全 numpy コア (XRDML/model/parametric/phaseid/engine 制御ロジック/MCP) は GSAS/MP 非依存に
  決定論テストで green。実データは `@pytest.mark.gsas` (+ MP gate)。
