# Issue #130 実装タスク (route X, Fable 主導 TDD)

設計: `docs/design/discriminate-mcp/architecture.md`。仕様: FR-313 (固溶体 vs 二相判別) +
FR-500 (nested) の ② 露出。★不変条件: ①→②→③ 同 PR 露出。

- [x] **L1 PhaseInstance.structure_ref**: 実 CIF 参照の非破壊追加 (末尾/既定 None)。
      SimulatedBackend 無視を変異テストで実証。
- [x] **L2 GSASIIBackend 実 CIF 分岐**: structure_ref があれば add_phase 実 CIF + 格子上書き
      (`_apply_cell`)、無ければプレースホルダ。gsas カナリア (実原子 Pb/S/O≠Ni / 格子上書き /
      実 PbSO4 cell 収束)。
- [x] **L3 marshaling** (numpy): `_discriminate_spec` に PhaseInstance/LatticeParams/
      FixedPhaseSpec の from_dict/to_dict + FrameSeries JSON 構築 2 経路 (生配列 / data_paths
      loader スタック)。不正入力 ValueError。
- [x] **L4 ② discriminate ツール**: JSON→GSASIIBackend+FrameSeries+config→discriminate_interval
      →verdict dict。nested オプトイン。例外 error dict 縮退。MCP_TOOLS 35→36。
- [x] **L5 ③ operando-diagnose**: J10 (固溶体 vs 二相) + ツール表。plugin coverage guard で
      ②↔③ 到達強制。LAYER1_FEATURES nested を discriminate 露出済みへ更新。
- [x] **L6 GSAS end-to-end カナリア**: 実 PbSO4 CIF で discriminate ツール全鎖が完走
      (4.5s)・nested オプトインも走る。

## スコープ外 (宣言)

- 別空間群の 2 相反応 (端成分異構造): discrimination の phase_ref 共有前提を継承。
- 判別中の原子座標/占有率精密化: FR-313 は格子連続性 vs 相共存なので cell+scale が正しい DOF。
- discrimination の実データ GSAS **精度検証** (真の operando データでの verdict 正答性):
  本 PR は「実 CIF 経路が走る」ことの配線・カナリアまで。実データ判別精度は M-later
  (合成ベンチはある; 実測 operando データでの FR-313 正答性は別検証)。
