# m3-operando 設計ヒアリング記録

**作成日**: 2026-07-03
**実施形態**: 自律実行モード — 質問は行わず、要件定義書・仕様書・M0〜M2 実装・推奨案で確定。

## 自律確定した設計判断

### D-Q1: マルチスタート各 start の精密化方式
**確定**: backend.refine 直呼び (direct)、staged フルは使わない。
**根拠**: FR-234「1 本あたりのコストは探索モード精密化と同等に抑える」🔵。

### D-Q2: basin クラスタリングの距離
**確定**: 収束解のパラメータを初期値スケールで無次元化した相対距離 < 1e-2 の union-find。
**根拠**: FR-232 は手法を規定しない。M1 clustering の union-find パターン再利用 🟡。
閾値は SearchConfig 同様に設定化して曖昧さを設定へ逃がす。

### D-Q3: 吸収補正の実装位置 (backend 内 vs ラッパ)
**確定**: SimulatedBackend のコンストラクタ引数 `absorption` として内蔵 + parse_param の
"global.*" 文法拡張 + RefinementResult.globals。ラッパ方式は LM ループへ μt を注入できず不可。
**根拠**: FR-317「フィット変数として精密化」には最適化ベクトルへの参加が必須 🔵。
GSASIIBackend は v1 では scale 畳み込み近似 (docstring 明記) 🟡。

### D-Q4: FR-313 仮説 B (二相) の格子の扱い
**確定**: 端成分格子は区間端点の単相フィット結果で初期化し**固定**、scale/wt_frac のみ解放。
**根拠**: 二相反応の物理 (端成分組成一定・分率変化) 🔵。格子も解放すると仮説 A との識別性が
落ち evidence 比較が縮退する 🟡。

### D-Q5: FR-316 の区間コスト
**確定**: 区間内の warm-start 逐次 direct refine の bic 和 (changepoint・木探索なし軽量版)。
区間コストはメモ化して貪欲挿入の再評価を回避。
**根拠**: FR-316「粗い格子スキャン→細密化」の計算量抑制 🔵。SequentialEngine フル再利用は
探索が混ざり過剰 🟡。

### D-Q6: 分割仮説の Hypothesis 表現
**確定**: 各 k の分割を 1 個の Hypothesis (id="seg-...", frame_range=全区間) とし、境界は
ledger payload と SegmentationResult.evidence_by_k に保持。
**根拠**: FR-316「分割自体も Hypothesis として保存」🔵。区間ごとの相構成は判別 (FR-313) 側の
仮説が持つため、分割仮説は境界情報が主 🟡。

### D-Q7: echem 同期の欠損政策
**確定**: 列欠損 = 明示エラー (列名提示)、行数不一致 = 短い方に合わせ欠損 None + 警告。
**根拠**: EDGE-003。M2 の温度チャネル欠損 (None+警告) と同一政策 🔵。

### D-Q8: Issue #4 の実装
**確定**: `_interpolate_crossing` を direction 対応にし、disappearing では 90% 交差を onset に。
既存テスト `test_transition_sigmoid_down_direction_disappearing` に onset 検証を追加、
既存の期待値変更は変更理由コメント付き。
**根拠**: Issue #4 対応案 🔵。

### D-Q9: Issue #5 の依存方向
**確定**: `tsumugin/_json.py` (無依存の葉モジュール) に `finite_or_none` を置き、
tree.py (センチネル判定は tree 内に残す)・webui/app.py・store/serialization.py が import。
**根拠**: store 最下層から search への逆依存回避 (tasknote 指摘) 🔵。

### D-Q10: 転移点 x/V±σ の算出
**確定**: 判別で確定した区間境界フレームの echem 値を線形補間、σ は隣接フレームの echem 差。
**根拠**: FR-314「転移点x/V±σ」🔵。算出式は M2 の転移温度推定 (Q6) と同型 🟡。

## 残課題 (実装時確定)

- penalty_beta=5.0 / basin_rel_tol=1e-2 / 摂動幅の既定は合成ベンチのテストで凍結 (§12-3 で再較正)
- GSASIIBackend の μt ネイティブ対応 (GSAS-II の吸収モデル利用) は M-later
- Ray 並列 (FR-234 実行系) は M-later — MultistartEngine.run の start ループが map 置換可能な
  構造であることをテストで担保

## 信頼性レベル分布 (設計文書全体)

- 🔵: 72 件 (63%) / 🟡: 43 件 (37%) / 🔴: 0 件

## 関連文書

- [architecture.md](architecture.md) / [dataflow.md](dataflow.md) / [interfaces.py](interfaces.py) /
  [要件定義](../../spec/m3-operando/requirements.md)
