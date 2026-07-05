# M6 相同定 (Phase Identification) 実装計画

## 達成目標
未知の XRD パターン + そこに含まれ得る元素一覧から、含まれる相 (複数可) を同定する。

## 現状分析 (2026-07-04)
- `tsumugin.search` (tree/matcher/clustering/peaks/pruning) は**候補相を外部から受け取る**設計。
- `PhaseInstance` は格子 + 占有率のみで原子座標を持たず、`backends.gsasii` は全相を
  「P mmm・原点 Ni 1 原子」に簡約 (M0/M1 の割り切り) → 現状の相同定はピーク位置マッチのみ。
- **未実装の中核ギャップ = FR-100/101/103/105**: 相ライブラリ (MP/COD/ICSD/CIF 取り込み →
  実構造の強度付きパターン/ピーク生成)。これが「元素一覧 → 候補相供給」の欠落部分。

## 設計判断
- **強度計算源**: pymatgen `XRDCalculator` を採用 (GSAS-II 簡約でなく実構造の相対強度・hkl を
  決定論的に生成)。GSAS-II 非依存。既存の遅延 import 境界 (nested/mem/oed) と同型で隔離。
- **`PhaseInstance` は不変**: 参照相は自前のピークリスト (`ReferencePhase.peaks`) を持つ別値オブジェクト。
- **モジュール構成**:
  - `tsumugin.reference` — コア (numpy-only, 常時 import 可)。相ライブラリ data model +
    `ReferenceProvider` Protocol + `identify_phases` オーケストレーション。
  - `tsumugin.mp` — Materials Project 境界 (遅延 import: mp-api/pymatgen)。MP クエリ +
    XRD 生成 + StructureMatcher 重複排除 (FR-102) + hull フィルタ (FR-103)。`MPReferenceProvider`。
- **新 extra `mp`** (pymatgen + mp-api)、新 `MPUnavailableError`、env キー `MATERIALS_PROJECT_API`。

## 段階計画 (TDD: Red → Green → Refactor)
### Phase 1 (コア・ネットワーク/pymatgen 不要で完全テスト可能) ← 本セッション
- `reference/model.py`: `ReferencePhase` / `PhaseMatch` / `PhaseIdentification`
- `reference/provider.py`: `ReferenceProvider` Protocol
- `reference/engine.py`: `identify_phases()` — `find_peaks` + `match_score` + `unmatched_peaks` を
  土台にランキング + 未知相レポート + 元素系部分集合フィルタ + hull フィルタ (FR-103, None=保持)。
- Fake provider で 1:1 テスト。決定論 (score 降順・同点 phase_id 昇順)。

### Phase 2 (MP 境界)
- `mp/client.py`: `MPRestClient` (遅延 import mp_api.MPRester, `MATERIALS_PROJECT_API` 読込) + `MPClient` Protocol。
- `mp/xrd.py`: pymatgen `XRDCalculator` で構造 → `Peak` 列、`StructureMatcher` 重複排除。
- `mp/provider.py`: `MPReferenceProvider(ReferenceProvider)` — 元素系クエリ + hull + dedup + キャッシュ (FR-105)。
- extra `mp` 導入、`MPUnavailableError`。

### Phase 3 (実データ検証 + 統合) — 完了
- 公開 API (`tsumugin.__init__`) 統合済み (164 シンボル)。MP ライブ検証 (自己整合) 済み。

### Phase 4 (CIF 供給元 + 多相同定) — 完了
- `reference/cif.py`: `cif_to_reference_phases` (pymatgen CifParser → 構造 → XRD、複数ブロック対応)。
- `reference/providers.py`: `UserCIFProvider` (完全実装・キャッシュ・`from_files`)、
  `CODProvider`/`ICSDProvider` (**導線のみ** — `downloader` シーム注入で有効化、未注入は
  `NotImplementedError`。ICSD はライセンス要で `api_key` 保持)。
- `reference/mixture.py`: `ReferenceBackend` (`RefinementBackend`+`simulate`、参照ピークを
  ガウシアン描画 + スケールを重み付き最小二乗フィット、chi2/rwp は SimulatedBackend と統一) +
  `identify_phase_mixtures` (既存 `HypothesisTreeSearch` へ接続し多相仮説を返す)。
- `engine.py`: `filter_references` 共通化 (単相/多相で共有)。

### 残 (M6 further / M-later 候補)
- COD/ICSD の実 downloader 配線 (ネットワーク取得)。DFT 緩和補正 (FR-104)。
  パターンキャッシュ永続化 (FR-105 の永続層)。MCP ツール統合。GSAS-II チュートリアル実測検証。
