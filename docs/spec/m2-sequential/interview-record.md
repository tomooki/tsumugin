# m2-sequential ヒアリング記録

**作成日**: 2026-07-03
**実施形態**: 自律実行モード — 質問は行わず、仕様書・CLAUDE.md・M0/M1 実装・推奨案で確定。
以下は論点と自律確定の根拠。

## 自律確定した論点

### Q1: 作業規模
**確定**: フル機能開発。**根拠**: M2 は 4 サブシステム (シーケンシャル/高温/永続化/2モード) を
含むコアマイルストーンで、FR 番号付き仕様が既にある 🔵。

### Q2: シーケンシャルの入力界面
**確定**: `FrameSeries` 相当の軽量入力 (共通 2θ グリッド + フレームごと強度配列 + 軸値配列) を
新設し、§4 の Dataset/Frame/HistogramRef (ファイル参照ベース) への接続は M3 のデータ I/O
(FR-501) と併せて行う。**根拠**: M2 のテストは合成データ (ndarray) で完結する。ファイル I/O を
持ち込むと FR-501 の先取りになりスコープが膨らむ 🟡。

### Q3: トラジェクトリ出力形式
**確定**: 構造化データ (dataclass) + CSV (stdlib)。parquet は見送り (pyarrow 依存を追加しない)。
**根拠**: FR-306/324 は「parquet/CSV」— コア依存 numpy のみの方針 (CLAUDE.md) から CSV を既定に。
parquet が必要になったら optional extra で M-later 🟡。

### Q4: ledger/snapshot 永続化フォーマット
**確定**: 追記専用 JSONL (1 行 = 1 エントリ、ハッシュチェーンは in-memory 実装の
`_canonical_json`/`_compute_hash` を再利用)。SQLite/HDF5 の Project Store (§3) は M3+ で検討。
**根拠**: NFR-105 の本質は「追記専用+ハッシュチェーン+verify」。JSONL は追記が原子的で
git 差分にも優しく、依存ゼロ 🟡。

### Q5: changepoint 複合指標の合成方法
**確定**: 3 指標 (Rwp 跳ね・格子微分・新規未マッチピーク数) をそれぞれロバスト z スコア化
(中央値/MAD) し、いずれかが閾値 (既定 5.0) を超えたら changepoint。**根拠**: FR-303 は指標の
列挙のみで合成式は未規定。外れ値検出の標準手法を推奨案として採用、閾値は SearchConfig 同様
設定可能にして曖昧さを設定へ逃がす 🟡。

### Q6: 転移温度 onset/midpoint の推定式
**確定**: 相分率 (または存在指標) の温度プロファイルに対し、midpoint = 50% 交差の線形補間、
onset = ベースラインからの離脱点 (10% 交差)、σ = 隣接フレーム間隔から評価。
**根拠**: FR-323 は onset/midpoint±σ の出力のみ規定。シグモイドフィットは M-later、
M2 は補間ベースの決定論推定 🟡。

### Q7: Review Queue の実装範囲
**確定**: 追記型のキュー (エントリ = 種別/frame/hypothesis_id/根拠/resolved フラグ)。
resolve は「解決済みマーク追記」で表現 (エントリ削除はしない)。UI 表示は M-later。
**根拠**: FR-403「Review Queue に通知(ブロックしない)」+ P2 追記原則 🔵/🟡。

### Q8: agent モードの自動 accept 条件
**確定**: (a) ランキング 1 位、(b) close_competitor=False、(c) unknown_phase_flag=False、
(d) escalated=False のとき自動 accept。いずれか欠けたら暫定裁定 (best を provisional 記録) +
Review Queue。**根拠**: FR-402「evidence・化学妥当性・マルチスタート結果を根拠に」のうち
M2 で利用可能な材料 (ChemPlausibility は M4、マルチスタートは M3) で構成 🔵/🟡。

### Q9: EDGE-002 失敗フレームの継承元
**確定**: 最後に成功したフレームの phases から warm start (失敗フレームの phases は使わない)。
**根拠**: §14「逐次解析の誤り伝播」リスクの最小緩和。cold restart は M3 の定期 restart で拡張 🟡。

## 残課題 (実装時確定 / 後続)

- changepoint 閾値 5.0・ヒステリシス N=3 の較正は合成ベンチで確定 (テストで固定)
- native sequential (GSAS-II) の実装は M-later (インターフェースのみ)
- Review Queue の Web UI 統合は M3+ (FR-421)

## 信頼性レベル分布 (要件定義書全体)

- 🔵 青信号: 24 件 / 🟡 黄信号: 14 件 / 🔴 赤信号: 0 件

## 関連文書

- [requirements.md](requirements.md) / [user-stories.md](user-stories.md) /
  [acceptance-criteria.md](acceptance-criteria.md)
