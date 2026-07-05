---
name: insitu
description: 高温/時間 in situ 粉末回折の逐次 (parametric sequential) 全自動 Rietveld 解析を閉ループで進める。MCP 3 ツール (sequential_rietveld / identify_and_add_phase / parametric_fit) を反復駆動し、温度/時間フレーム列をウォームスタートで逐次精密化、相転移で出現する新相を Materials Project から自動同定して相集合に追加、格子 vs 温度・転移温度を抽出する。初期相のみ与えれば新相は自動発見する。
---

# tsumugin: Agentic 高温 in situ 逐次 Rietveld 解析 (③ 判断層)

あなた (Claude) が**判断者 ③** として、温度/時間系列の粉末回折を逐次 Rietveld 精密化する閉ループ
解析を行う。M7 単一フレーム自動 Rietveld + M8 agentic 閉ループ + M6 相同定を統合した M9 の系列版。
**初期相のみ与えられ、系列途中で出現する新相 (例 CaTeO3 の脱水相 delta) は自動同定する**のが要点。

設計: `docs/design/m9-insitu-sequential/architecture.md`。

## 使う MCP ツール (②)

| ツール | 役割 | 入出力 |
|---|---|---|
| `sequential_rietveld` | 計器+アクチュエータ | frames + initial_phases spec (JSON) → フレーム別 Rwp/格子/相分率・変化点・自動出現相 |
| `identify_and_add_phase` | 計器 (相同定) | 残差/生パターン + elements + workdir → 物質化した PhaseSpec 候補 (CIF パス) + 根拠 |
| `parametric_fit` | 計器 (解析) | 系列結果 + parameter/axis → 熱膨張多項式係数・転移 onset/midpoint±σ |

閉ループ丸ごとは MCP に**無い**。回すのはあなた。

## 手順

1. **入力を組み立てる**: 各温度/時間点の観測ファイルを `FrameSpec` (data_path・axis_value=温度/時間・
   data_format ["XRDML"/"FXYE"/"GSAS"/"XYE"]) の列に、初期既知相を `PhaseSpec` (CIF) にする。
   放射源/ジオメトリは系列で共通 (実験室 X 線 Bragg-Brentano / 放射光 Debye-Scherrer)。
2. **新相自動同定を設定する**: `phase_id = {"elements": [既知+想定元素], "frac_min": 0.02, "top_k": 1}`。
   これで系列途中の変化点/Rwp ジャンプで Materials Project から新相を探し、**受理基準 (相分率有意 ∧
   Rwp 改善 ∧ 妥当性) を満たせば自動追加**する。`elements` を空にすると相追加を行わない。
3. **`sequential_rietveld` を呼ぶ**。フレーム別 Rwp/格子/相分率・変化点・`appearances` (自動追加相) を読む。
4. **結果を読み判断する**:
   - `appearances` に新相が出たら、その `formula`/`source`/`rwp_before→after`/`evidence` を確認し、
     **化学的に妥当か・未指数ピークを説明するか**をあなたが判断する。疑わしければユーザーに確認を求める。
   - 変化点フレーム (`changepoint=True`) の格子/相分率の跳ねを転移の物理と照合する。
   - Rwp がフレーム全域で目標帯 (チュートリアル値 ± マージン) に収まるか。
5. **必要なら手動で相を探す**: 自動追加が起きなかったが未指数ピークが残る変化点で、そのフレームの
   パターンを `identify_and_add_phase` に渡し、返る PhaseSpec 候補を `initial_phases` に足して
   `sequential_rietveld` を再実行する (相追加は**あなたの判断 + ユーザー承認**を挟む)。
6. **パラメトリック解析**: `parametric_fit(result, phase, component)` で格子 vs 温度の熱膨張係数、
   相分率シグモイドの転移温度 (onset/midpoint±σ) を抽出し報告する。b/c 比等の擬変数で 2 次転移も追う。
7. 全フレーム収束・転移特性を報告する。最良結果・相の出現/消失・転移温度・申し送り。

## 権限境界 (M8 §4.5 継承)

| 判断 | 決定論コア (自律) | ③ (あなた/ユーザー) |
|---|---|---|
| ウォームスタート・背景/母数解放・段階解放 | ✅ 自律 (Rwp∧validity で自己検証) | 監督 |
| 変化点検出・相同定候補の提示 | ✅ 提示 | — |
| **新相の採否** (相追加) | 🟡 受理基準で自律採用も可 (frac∧Rwp∧validity) | ✅ 化学妥当性を確認・疑わしきはユーザー承認 |
| 構造改訂・空間群・データリミット精密化 | ❌ | ✅ 判断・実行 |

**なぜ受理基準で自動採用が許されるか**: 相追加は「未指数ピークを説明し ∧ 相分率が有意 ∧ 全体 Rwp を
改善し ∧ 妥当性を壊さない」ときのみ受理し、外れれば可逆に棄却される (提案≠適用)。ただし化学的に
不自然な相 (元素系外・準安定すぎ) は ③ が退けるべき — 受理基準は残差の説明力しか見ないため。

## 前提

- GSAS-II (GSASIIscriptable) が導入されていること。未導入なら該当ツールが error を返す。
- 新相自動同定は Materials Project キー (環境変数 `MATERIALS_PROJECT_API`) が必要。未設定なら
  `identify_and_add_phase` が error を返すので、CIF を直接 `initial_phases` に足す運用に切り替える。
