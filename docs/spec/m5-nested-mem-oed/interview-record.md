# m5-nested-mem-oed ヒアリング記録

**作成日**: 2026-07-04
**実施形態**: 自律実行モード — 対話ヒアリングは行わず、仕様書 (§5 FR-121/122/123/124/125 /
§8 FR-430/431/432 / §9 FR-600〜606 / §11 NFR-102/103/105/107 / §12-5 較正ベンチ / §13 M5 / §15)・
M0〜M4 実装・推奨案で自己解決した。以下は論点と自律確定の根拠 (Q&A 形式)。

## 自律確定した論点

### Q1: 作業規模
**確定**: フル機能開発。
**根拠**: M5 は仕様最終マイルストーン。nested 裁定 (FR-121/122) / MEM (FR-600系) / OED (FR-430系) /
較正済み確率 (FR-124) が仕様に明記済み。M4 で `run_mem` 境界・`EvidenceResult.logz_err` フィールド・
`MEMUnavailableError` が既に用意され、接続点が確定している 🔵。

### Q2: nested の 2 段構え (bic 一次 + 競合のみ nested) の実装位置
**確定**: 木探索・枝刈りは既存 `HypothesisTreeSearch` (bic) を不変で再利用。生存仮説の `rank` 結果で
`close_competitor=True` (ΔBIC < 10) の競合群のみ `nested` で再裁定する上段を新設。フル nested は設定フラグ。
**根拠**: FR-122「木探索は bic、生き残った上位仮説間で evidence 差が閾値未満の競合のみ nested で再裁定する
2 段構え」🔵。既存 `rank(..., close_threshold=10.0)` の `close_competitor` フラグをそのまま裁定対象判定に
使えるため実装最小 🔵 (evidence/ranking.py)。

### Q3: nested バックエンドの外部依存方式
**確定**: dynesty / UltraNest を **optional extra `nested`** として追加。`NestedBackend` は SDK と
同様に「遅延 import + 未導入時 `NestedUnavailableError`」で縮退。コア import は numpy のみ維持。
**根拠**: CLAUDE.md「コア依存は numpy のみ・nested(dynesty/ultranest) は optional extra」🔵。
M4 の `MCPUnavailableError` / `WebUIUnavailableError` の「available + 専用例外」パターンと対称 🔵 (errors.py)。
dynesty/ultranest の選択は設定可 (REQ-303) とし実装時に既定を確定 🟡。

### Q4: nested の value 符号規約
**確定**: `nested` の `EvidenceResult.value` は他 IC 系と同一符号 (小さいほど良い、例 `-logZ`)。logZ 生値と
`logz_err` は付随情報として保持。
**根拠**: 既存 `rank` は value 昇順で並べ softmax(-value/2T) を計算する (evidence/ranking.py)。BIC/AIC/
Laplace と混在比較するため符号規約統一が不可欠 (CLAUDE.md「chi2/rwp のセマンティクスはバックエンド間で
統一」) 🟡。`logz_err` フィールドは M0 で既に定義済 (evidence/base.py) 🔵。

### Q5: Laplace evidence を M5 で実装する理由
**確定**: `laplace` バックエンドを M5 で実装。nested の時間上限超過時 (NFR-103) の代替として必須。
**根拠**: NFR-103「nested 裁定は 1 仮説 ≤ 30 分・超過時は打ち切り + Laplace 代替」🔵。FR-121 に laplace は
定義済だが M1 では bic/aic のみ実装だった。M5 で nested と対で実装するのが自然 🔵。Hessian 取得不能時は
BIC フォールバック 🟡 (縮退の穏当化)。

### Q6: MEM の入力元と密度種別
**確定**: MEM 入力は精密化済み仮説の F_obs (位相はモデル由来)。X線 → 電子密度、中性子 → 核密度。joint
精密化結果 (`JointVerificationResult`) を主入力元とする (適用ガード推奨条件が joint 済み単相/主相支配)。
**根拠**: FR-601「X線→電子密度、中性子→核密度」/ FR-605「joint 精密化済みかつ単相 or 主相支配的を推奨条件」🔵。
M4 で `verify_survivors` が joint 検証済み仮説を返す (joint/verification.py) ため接続点が確定 🔵。

### Q7: MEMBackend の外部依存方式
**確定**: `MEMBackend` Protocol + v1 実装は Dysnomia 連携 (外部バイナリラッパ・入出力ファイル自動生成/
実行/回収)。**optional extra `mem`**、未導入時は `MEMUnavailableError` (M4 で errors.py に定義済) へ縮退。
**根拠**: FR-602「v1 実装は Dysnomia 連携・将来の内製/他ソルバも同一 IF で交換可能」🔵。
リスク表「Dysnomia 外部依存 → MEMBackend 抽象化・未導入環境では MEM 機能を明示的に無効化」🔵。
`MEMUnavailableError` は M4 で先行定義済 (errors.py) 🔵。

### Q8: MEM-Rietveld 反復の非破壊保存
**確定**: MPF 型反復 (MEM 密度 → F_calc 更新 → 再精密化) は既定オフ。各サイクルは既存 `SnapshotStore` へ
子スナップショットとして追記。削除・上書きなし。
**根拠**: FR-603「各サイクルは仮説の子スナップショットとして保存・既定オフ・最大反復数/収束判定を設定」🔵。
§15-3「MEM-Rietveld 反復の自動運転は既定オフを維持・条件付き auto は将来判断」🔵。P2 非破壊 (CLAUDE.md) 🔵。

### Q9: MEM 適用ガードの思想
**確定**: 推奨条件 (joint 済み単相/主相支配) を満たさない多相/低統計データは**信頼性警告のみ**。除外・
中止はしない。
**根拠**: FR-605「多相・低統計データへの適用時は信頼性警告を表示 (除外はしない — Dara 教訓と同じ思想)」🔵。
M4 の ChemPlausibility「降格のみ・除外しない」と同型の不変条件 🔵。

### Q10: M4 の run_mem 境界の実体化
**確定**: M4 の `mcp/mem.py::run_mem_boundary` を MEMBackend へ委譲するよう接続。M4 の placeholder 契約
(`placeholder=True` の dict スキーマ `{"status","milestone","tool"}`) と後方互換を保つ。MEMBackend 未導入時は
`MEMUnavailableError` を MCP エラー dict へ変換。
**根拠**: 指示「M4 の run_mem MCP ツール境界を実体化」🔵。M4 `run_mem_boundary` は既に「明示エラー /
将来互換プレースホルダ」の 2 経路を持つ (mcp/mem.py) ため、実処理を MEMBackend 委譲へ差し替えるのみ 🔵。

### Q11: OED の実装範囲
**確定**: 僅差競合時の判別測定提案 (高統計再測定・追加温度点・joint 用中性子測定・組成分析) を情報利得順の
JSON スキーマで生成。PyBOED 獲得関数への接続は境界のみ・**v1 は提案生成のみ**。外部依存は optional extra
`oed`、未導入時 `OEDUnavailableError`。提案は非破壊 (ledger 追記のみ)。
**根拠**: FR-431「判別測定提案を情報利得順で提案する JSON スキーマ」/ FR-432「PyBOED 獲得関数への接続・
v1 は提案生成のみ」🔵。提案は非破壊 (P2)、僅差競合発動は `rank.close_competitor` を再利用 🔵。

### Q12: 較正ベンチの実装範囲
**確定**: reliability diagram / ECE の較正評価ユーティリティを実装。**bic と nested を別系列で評価**。
正解ラベル付きベンチデータ (予測確率, 真偽) を入力とし決定論的に reliability 曲線 + ECE を返す。
**根拠**: FR-124「backend 間で確率の意味が異なることをレポートに明記」/ §12-5「reliability diagram / ECE・
bic と nested の確率較正を別々に評価」🔵。§13 M5 の「較正済み確率」🔵。ベンチデータ生成/公開運用は M-later 🟡。

### Q13: nested 事前分布の自動構成
**確定**: 事前分布は精密化 restraint (格子シフト上限・占有率拘束等) から自動構成し、手動上書き可。
**根拠**: FR-125「事前分布は精密化 restraint から自動構成し手動上書き可」🔵。§15-5「nested の事前分布
自動構成は M5 で失敗モード検証の上で確定 (実装時確定)」— M5 の実装時課題として明記されている 🔵。

## 残課題 (実装時確定 / 後続)

- nested の閾値 (ΔBIC 再裁定閾値・温度較正パラメータ) は較正ベンチ (§12-5) で数値較正 — M5 はテストで
  既定値 (ΔBIC=10, T=1.0) を凍結
- dynesty vs UltraNest の既定選択・サンプラ設定 (live points 等) は導入時に固定
- Dysnomia の入出力ファイル契約 (拡張子・フォーマット) は実バイナリで contract test 確立時に固定 (NFR-106)
- nested 事前分布自動構成の失敗モード (restraint 欠落・特異事前) は §15-5 に従い実装時検証で確定
- OED の情報利得推定 (v1 は簡易近似) の精緻化・PyBOED 獲得関数実行は M-later
- 較正ベンチの正解ラベル付きデータセット生成・公開運用は M-later (§13「ベンチ公開」の公開部)

## 信頼性レベル分布 (要件定義書全体)

- 🔵 青信号: REQ 33 / NFR 5 / EDGE 11 相当 — 仕様・既存実装に直接依拠
- 🟡 黄信号: REQ 5 / NFR 0 / EDGE 3 相当 — 妥当な推測 (根拠併記)
- 🔴 赤信号: 0 件
- **総括**: 仕様書 (FR-121/122/124/125・FR-600系・FR-430系) が具体的で、M4 で接続点 (run_mem 境界・
  logz_err フィールド・MEMUnavailableError・close_competitor) が先行整備済のため 🔵 が支配的。設計裁量部
  (value 符号規約・Laplace フォールバック・nested サンプラ選択・OED 情報利得近似) が 🟡。

## 関連文書

- [requirements.md](requirements.md) / [user-stories.md](user-stories.md) /
  [acceptance-criteria.md](acceptance-criteria.md)
