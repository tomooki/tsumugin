# プロファイル物理性ガード 設計ヒアリング記録

**作成日**: 2026-07-09

## 設計判断 (DD)

### DD-1: ValidityReport を再利用する (新型を作らない) 🔵
`check_profile_physicality` の返り値は既存 `ValidityReport(passed, checks, warnings)`。
`passed` を hard (revert)、`warnings` を soft に割り当てることで、engine の最終 `validity` へ自然にマージでき、
新しいデータ型を増やさない。

### DD-2: hard / soft の切り分けは「解放フラグ」で行う 🔵
REQ-102 の誤 revert 防止。個別係数の符号違反 (X<0 等) と幅関数正値性は、当該パラメータ群に
refined=True が1つ以上あるときのみ hard。未解放の初期 instprm 由来違反は warning に留める。
これにより装置由来の近似 instprm で健全段階が巻き戻る事故を防ぐ。

### DD-3 (改訂): hard は「真の発散」のみ・CW 係数は soft 🔵
当初 `H_G²(θ)` 区間最小 > 0 を hard にしたが、GSAS `getFWHM` がガウス分散を `max(0.001,·)` でクランプ
するため H_G²<0 は非物理でなく、実 T1 は U=-1.96,Y=-3.13 の良好フィットに収束する (区間最小 hard だと
Rwp 9.83→12.85% に誤 revert)。よって **hard = 真の発散のみ**: 解放済値の NaN/inf (全放射源)・TOF σ²<0
(GSAS はクランプせず NaN 化)・TOF alpha/beta-0≤0 (1/α,1/β 発散)。CW 係数・SH/L は区間最小/符号を
**soft 警告**として計算・記録する (診断・validity 用)。区間最小の 3 点評価 (端点+頂点) は soft 警告と
TOF hard の根拠計算として存置。これは材料非依存かつ GSAS 実挙動に忠実で「過度な一般化」を避ける。

### DD-4: レンジは engine が GSAS `getdata("x")` から供給、純関数は単位非依存 🔵
CW は 2θ° の min/max、TOF は TOF μs を `d≈(t-Zero)/difC` で d 換算。純関数は radiation で
レンジの意味を解釈するだけで GSAS に触れない。取得不能は None → レンジ依存判定のみ skip。

### DD-5: engine 変更は最小 (_cells_physical と同格の 1 ガード) 🔵
accept/revert 構造不変 (REQ-403)。「非物理 → rwp=inf」への変換を1行足すだけで、既存の
スナップショット復元経路がそのまま revert を実行する。

### DD-6: alpha/beta は strict > 0、sig/X/Y/SH-L は tol 付き非負 🔵
`1/alpha`,`1/beta` は 0 で発散するため strict-pos (val > 0)。それ以外の非負制約は数値ノイズ用に
`sign_tol` (既定 1e-3) の負側許容を持たせ、収束近傍の微小負で誤 revert しない。

## 未確定 → 既定で確定した事項
- SH/L soft 上限 = 0.1 (revert 無関係の警告閾値なので安全側に緩く設定, 後から調整可)。
- sign_tol = 1e-3 (Uiso の uiso_neg_tol=1e-4 より緩め: プロファイルは桁が大きいため)。

## 関連文書
- [architecture.md](architecture.md) / [dataflow.md](dataflow.md) / [interfaces.py](interfaces.py)
- [requirements.md](../../spec/profile-physicality-guard/requirements.md)
