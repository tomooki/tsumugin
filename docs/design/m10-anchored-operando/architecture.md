# M10 アンカー基準双方向 operando 逐次解析 アーキテクチャ設計

仕様 (正): `docs/tsumugin_spec_v0.3.md` FR-330 (331〜338) / 要件: `docs/spec/m10-anchored-operando/requirements.md`

## 0. スコープと達成目標

M9 `insitu` 前方単一パスの脆さ (初期フレーム依存 + 転移域のセル汚染) を、**信頼できるフレーム
(アンカー) 起点の双方向解析 + IC ベース経路選定**で頑健化する。CaTeO3 cyclic で転移 onset を
crossover で確定し、現行 forward+consolidate より転移域 Rwp を下げ偽相を出さない (AC-1)。

**核心の設計判断 (ユーザー提案 + 検証で確定):**
1. アンカーは **2 段ゲート** (相同定信頼度 → Rietveld Rwp+validity 確認)。同定だけでは peak-rich 誤マッチを拾う。
2. 相集合が異なる前方/後方の比較は **Rwp でなく bic** (相数増加で Rwp は単調減少 → 偏り)。
3. 選定は per-frame 貪欲でなく **区間総 bic 最小の crossover 1 点** → 相分率が単調。
4. 物理妥当性に **結合距離・配位数** を追加 (誤構造の偶然フィット棄却)。

## 1. 設計原則 (M7/M8/M9 継承)

- **numpy-only コア + 遅延 import 境界**: オーケストレーション (アンカー/区間/crossover/bic) は numpy のみ。
  精密化は注入 `runner` (GSAS は内部)、結合距離/配位数は pymatgen 遅延 import。
- **P2 非破壊 / 提案≠適用**: 前方・後方の両トライアルを ledger 追記し、採用経路を「選択」で表現。
  棄却経路も保持 (代替閲覧)。削除/上書き API なし。
- **NFR-102 決定論**: 乱数なし。同一入力でビット同一経路。マルチスタート摂動種は固定。
- **既存型の再利用**: 出力は `SequentialRietveldResult` 互換 → 下流パラメトリック解析 (`insitu.parametric`) が
  無改修で動く。runner シグネチャは M9 `Runner = (frame, phases, initial_cells) -> AutoRietveldResult` を踏襲。

## 2. モジュール構成 — `tsumugin.insitu.anchor` (M10 新規)

| ファイル | 役割 | 主要シンボル |
|---|---|---|
| `anchor/model.py` | 不変 dataclass | `AnchorConfig`, `Anchor`, `Segment`, `SegmentPass`, `CrossoverChoice` |
| `anchor/extract.py` | アンカー抽出 (2 段ゲート) | `extract_anchors`, `anchor_confidence` |
| `anchor/segment.py` | 双方向区間解析 | `build_segments`, `refine_segment_forward`, `refine_segment_backward` |
| `anchor/select.py` | crossover 選定 (bic) | `select_crossover`, `segment_bic`, `assemble_path` |
| `anchor/engine.py` | オーケストレーション | `run_anchored_sequential` |

`autorietveld/validity.py` に **REQ-1012** の `check_bond_validity` を追加 (pymatgen 遅延 import)。
`insitu/__init__.py` に `run_anchored_sequential` / `AnchorConfig` を re-export。

## 3. 要素1 — アンカー抽出 (extract.py, FR-331)

```
extract_anchors(frames, base_phases, runner, identifier, cfg) -> tuple[Anchor, ...]
```

**段階 A (安価スクリーニング)**: 各フレームで相同定 (既存 `identify_phases`) を実行し合成信頼度:

```
anchor_confidence(ident) =
    w1 * norm(top.score)                      # Dara スコア (絶対品質)
  + w2 * clip(top.score - second.score, 0, m) # スコアマージン (一意性)
  - w3 * top.strain                           # 格子乖離 (小=良)
  - w4 * ident.unmatched.has_unknown          # 未知相ペナルティ
```

`confidence >= anchor_confidence_min` を候補に。**段階 B (確認)**: 候補を `runner` で実構造 Rietveld し
`Rwp <= anchor_rwp_max ∧ check_validity.passed` のみ確定。0 個なら Rwp 最小フレーム 1 個を fallback
(REQ-1003)、`phase_id=None` なら frame 0 のみ (REQ-1004 後方互換)。

**設計注**: 段階 A の相集合が段階 B の warm-start 相集合になる (アンカーは自身の相集合を持つ)。単相域は
自然に高信頼 → 単相アンカー、転移直後の delta 支配域は delta を含む相集合でアンカー化。

## 4. 要素2 — 双方向区間解析 (segment.py, FR-333)

```
build_segments(anchors, n_frames) -> tuple[Segment, ...]   # フレーム順・端点片側含む
refine_segment_forward(seg, frames, anchorL, runner)  -> SegmentPass  # L→R, L 相集合で warm
refine_segment_backward(seg, frames, anchorR, runner) -> SegmentPass  # R→L, R 相集合で warm
```

- 各区間 `[L, R]` の**内側フレーム** (L+1 .. R−1) を 2 方向で独立に warm-start 逐次精密化。アンカー
  フレーム自体は段階 B の結果を採用 (再精密化しない)。
- 端点区間: 最初のアンカー以前は後方のみ、最後のアンカー以降は前方のみ (REQ-1008)。
- warm-start は M9 と同じ `initial_cells` 注入。相集合はアンカーのものを固定 (区間内で新相探索はしない —
  相の出現は**隣接アンカーの相集合差**として表現され、crossover で位置が決まる)。
- 前方/後方は共有状態なし → 並列化可 (本 M10 は逐次、結果同一; REQ-1007)。

```
        anchor L (alpha)                          anchor R (alpha+delta)
        │  →→→ forward pass (alpha のみ) →→→                │
        │                ←←← backward pass (alpha+delta) ←←←│
frames: L  ·    ·    ·    ·    [crossover k]   ·    ·    ·   R
        └── L..k: 前方採用 ──┘└──── k+1..R: 後方採用 ────┘
```

## 5. 要素3 — crossover 選定 (select.py, FR-334)

```
select_crossover(seg, fwd: SegmentPass, bwd: SegmentPass, cfg) -> CrossoverChoice
```

- **相集合が同一**の区間: フレーム毎に Rwp (or gof) 最小を採用 (パラメータ数同一 → 公平)。crossover 概念なし。
- **相集合が異なる**区間: 各フレームの bic を前方/後方で算出。区間総 bic を最小化する crossover k を全探索:

```
total_bic(k) = Σ_{j=L+1..k} bic_fwd(j) + Σ_{j=k+1..R-1} bic_bwd(j)
k* = argmin_k total_bic(k)            # k ∈ [L, R-1]
```

- **bic**: 既存 `_frame_bic` (operando/segmentation) 相当を再利用。`bic = n_obs·ln(χ²/n_obs) + n_parm·ln(n_obs)`。
  相数の多い後方フィットは n_parm 増で罰され、真に説明力がある転移後のみ後方が勝つ。
- **単調性 tie-break** (REQ-1011): 総 bic が `bic_tie` 以内で並ぶ複数 k のうち、採用経路の新相分率が
  frame 順で単調増加になる k を選ぶ。
- **物理妥当性** (REQ-1013): 僅差時は crossover 近傍フレームで `check_bond_validity` pass を要求。

`assemble_path` が L..k を fwd から・k+1..R を bwd から連結し `FrameRietveldResult` 列を構成。crossover が
相集合変化を含めば onset を `PhaseAppearance` に記録 (FR-336)。birth/death はヒステリシス (REQ-1015)。

## 6. 要素4 — 物理妥当性ゲート (validity.py 拡張, FR-335)

```
check_bond_validity(structure_path, refined_cell, cfg) -> ValidityReport   # pymatgen 遅延 import
```

- 精密化格子を CIF 構造に適用 (M9 `structure_to_cif` 経路) → pymatgen `Structure` → `CrystalNN` で
  近接解析。**最近接結合距離** ∈ [共有結合半径和 × `bond_tol_lo`, × `bond_tol_hi`]、**配位数** ∈ 期待範囲。
- pymatgen 不在は skip → bic + 既存 `check_validity` のみ (REQ-1013 WHERE, gate)。
- 既存 `check_validity` (格子範囲/Uiso/占有率/制約) と合成し `ValidityReport` を返す。

## 7. 要素5 — オーケストレーション (engine.py, FR-337)

```
run_anchored_sequential(frames, base_phases, *, runner, identifier=None, cfg=AnchorConfig(),
                        workdir=None, ledger=None) -> SequentialRietveldResult
```

1. `extract_anchors` → 確定アンカー列 (フレーム順)
2. `build_segments` → 区間列 (端点片側含む)
3. 各区間: `refine_segment_forward` + `refine_segment_backward` (独立)
4. `select_crossover` → 採用経路 + onset
5. `assemble_path` → `FrameRietveldResult` 列 + `PhaseAppearance` 列
6. ledger 追記 (両トライアル + 選定理由) → `SequentialRietveldResult` 返却

**`_consolidate_phase_cells` の位置づけ**: M10 アンカー方式に**包含**される (支配フレームのアンカー =
delta アンカー、その相集合/セルが後方パスの warm-start 種)。M9 `run_sequential_rietveld` は
`backward_propagation` 経路として残置 (後方互換)。M10 は独立エントリポイントとして追加し、実データで
優位を確認後に既定経路化を検討 (段階移行)。

## 8. データフロー

```
frames + base_phases
   │  identify_phases (段階A) ──┐
   ▼                            ▼
extract_anchors ── runner (段階B: Rietveld+validity) ── 確定アンカー
   │
   ▼
build_segments ─→ [L,R] 区間列
   │
   ├─ refine_segment_forward  (runner, L 相集合) ─┐
   ├─ refine_segment_backward (runner, R 相集合) ─┤ (独立/並列可)
   ▼                                              ▼
select_crossover (bic + 単調性 + check_bond_validity)
   │
   ▼
assemble_path → FrameRietveldResult 列 + appearances + ledger
   │
   ▼
SequentialRietveldResult ─→ insitu.parametric (無改修再利用)
```

## 9. 段階計画 (TDD, Opus)

1. **model.py** — dataclass 群 (numpy 非依存) + 決定論テスト
2. **extract.py** — `anchor_confidence` + 2 段ゲート (stub runner/identifier) + テスト
3. **segment.py** — 区間構成 + 双方向パス (stub runner) + テスト
4. **select.py** — bic + crossover 全探索 + 単調 tie-break (stub) + テスト
5. **validity.py 拡張** — `check_bond_validity` (pymatgen 遅延) + gated テスト
6. **engine.py** — オーケストレーション統合 + numpy 決定論テスト
7. **実データ検証** — CaTeO3 14 フレーム (`@pytest.mark.gsas`) + forward+consolidate 比較
8. **`/code-review` ループ** → PR

## 10. テスト戦略

- **決定論コア** (model/extract/select 選定ロジック/bic 比較): stub runner + stub identifier で相集合差・
  crossover・単調性・fallback・後方互換を network/GSAS なしに green (NFR-M10-2)。
- **crossover の正しさ**: 前方 (1 相, bic 高) / 後方 (2 相, 転移後のみ bic 低) の合成列で k* が転移点に
  一致するテスト (M9 `test_consolidation_*` の設計を踏襲)。
- **bic vs Rwp の差**: 同じ列で「Rwp 最小」なら全域 2 相を選ぶが「bic 最小」なら転移後のみ、を対比する
  回帰テスト (①の設計判断を固定)。
- **gated**: `check_bond_validity` (pymatgen) と実データ engine (GSAS+MP) は mark で skip 可。

## 11. スコープ外 (M-later)

- 区間並列 executor (決定論逐次で実装, 並列と同一結果)。
- 端点マルチスタートの座標摂動 (格子摂動のみ)。
- 3 相同時 crossover・非単調 (往復) 転移の一般化。
- アンカー再帰細分化 (区間が長く drift する場合の中間アンカー追加) — 初版は固定アンカー。
