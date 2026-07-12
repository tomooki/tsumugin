# M8-③ 拡張: MEM 駆動の構造モデル修正 (R5 判断層) 設計

作成: 2026-07-12
前提: M8 で 3 層分離 (① `refine_loop` / ② MCP 3 ツール / ③ `plugins/tsumugin/skills/analyze`) と
`ReviseStructure` 適用プリミティブは実装済み。XND で実 Dysnomia MEM (`tsumugin.mem.gsas` /
`mem.output` / `mem.mpf`) が実データで動作。**しかし MEM と ③ 判断層が未接続**であり、「MEM 密度を
読んで構造モデルを修正する」閉ループ (R5) が存在しない。本書はその接続機構を計画する。

## 0. 位置づけ — なぜ ③ か

MEM 密度からの構造修正 (欠損原子の追加・分割サイト・占有率是正・軽原子/水素位置) は、
architecture.md §4.2 の **`ReviseStructure` = ModelAction = ③ 専用 (R5 事前知識)** そのもの。
残差 (Rwp) からは原因が一意に定まらないが、**MEM 密度は「未モデル散乱がどこにあるか」を空間的に
可視化する**ため、③ (Claude/人間) の構造判断を決定的に助ける。規則 (①) は密度から原因を断定でき
ない (Dara 教訓) ので、①/② は **計器 (MEM 実行・密度→構造化提案) とアクチュエータ (CIF 編集)** に
徹し、**採否と結晶学判断は ③**。提案 ≠ 適用、構造編集はユーザー承認、受理は Rwp 改善 ∧ validity 維持。

## 1. 目標ワークフロー (MEM 駆動 model-fix 閉ループ)

```
auto_rietveld (収束モデル + gpx ハンドル)
   └▶ mem_density (実 Dysnomia MEM: 未モデル密度ピーク/断面/伝導経路/.grd)
        └▶ propose_structure_revisions (密度→ReviseStructure/AddPhase/SetMixedOccupancy 候補 + 具体 evidence)
             └▶ ③ Claude が結晶学解釈 (どのピーク=欠損原子/分割/占有是正か) ─ ユーザー承認 ─
                  └▶ edit_cif (具体編集を CIF に適用 → 新 CIF ハンドル)
                       └▶ refine_with_revisions(ReviseStructure(structure_path=新CIF)) → 再精密化
                            └▶ 受理: Rwp 改善 ∧ validity 維持 なら採用 / さもなくば revert (ledger)
                                 └▶ 収束 or 未モデル密度が閾値以下まで反復
```

MEM 密度の結晶学的読み (③ の判断ガイド、skill に明記):
- **正の未モデル密度ピーク (原子から遠い)** → 欠損原子。電子/核密度の大きさと probe から元素を推定
  (X 線=電子数、中性子=散乱長 b)。
- **陽イオン近傍の 2 つのピーク** → 分割サイト (静的無秩序)。
- **既存原子上の弱い/負の密度** → 占有率過大 (核密度負 = 水素 b<0 の徴候)。
- **チャンネル/空隙の拡散密度** → 部分占有の格子水/イオン (占有率をピーク積分から初期化)。

## 2. 層別実装計画

### ① 決定論コア (numpy, GSAS 非依存テスト)

**(a) `refine_loop/mem_diagnostics.py` (新規)** — MEM→構造化提案の橋渡し。
```python
def propose_structure_revisions_from_mem(
    mem: MEMDensityResult, *, phase: str, probe: str,
    unmodeled_distance: float = 0.8, occ_scale: float | None = None,
) -> tuple[ActionProposal, ...]
```
- 未モデル密度ピーク (最近接原子まで `unmodeled_distance` 以上) を `ReviseStructure`/`AddPhase` 候補へ。
- `evidence` に **具体値**を載せる: `frac` (ピーク分率座標)・`magnitude`・`suggested_element`
  (probe×density_magnitude ヒューリスティック)・`occupancy_estimate` (ピーク高/元素散乱能)。
- 既存原子上の負の核密度 → 占有率是正/水素 `SetMixedOccupancy` 候補。
- **提案のみ・safe=False**。決定論・安定順 (既存 `propose_next_actions` と同規約)。

**(b) `autorietveld/cif_edit.py` (新規)** — 具体編集を CIF に適用する決定論ヘルパ (テキスト/numpy)。
```python
@dataclass(frozen=True) class AtomEdit:            # add | move | set_occupancy | remove
    op: str; label: str; element: str | None; frac: tuple|None; occ: float|None; uiso: float|None
def apply_atom_edits(cif_path: str, edits: Sequence[AtomEdit], out_path: str) -> str
```
- `reference.cif`/`autorietveld.cif_normalize` の CIF パーサ資産を再利用し、`_atom_site_*` ループへ
  行を追加/更新/削除して新 CIF を書く (元 CIF 不変・P2)。特殊位置・対称は編集しない (座標そのまま)。
- これで `ReviseStructure` が **具体編集から駆動可能 + 単体テスト可能**になる (③ の手編集を不要に)。

**(c) 任意: `ReviseStructure` に `atom_edits` 経路** — `edits={"structure_path": new}` に加え、
`ReviseStructure(phase, atom_edits=(...))` で apply 時に `apply_atom_edits` を呼び新 CIF を生成する
糖衣 (GSAS 非依存)。既存 `structure_path` 差し替え経路は温存 (後方互換)。

### ② 薄い MCP (計器 + アクチュエータ; SDK 非依存実処理 + 遅延 import)

MCP_TOOLS に **3 ツール追加** (実 MEM 系; M5 シミュレート `run_mem` とは別物):

| ツール | 入力 | 出力 |
|---|---|---|
| `mem_density` | gpx ハンドル (auto_rietveld 由来) + probe/dmin/grid | 密度 min/max・**未モデル密度ピーク[] (frac/mag/nearest/distance)**・.grd パス・任意 断面/伝導経路最小密度 |
| `propose_structure_revisions` | mem_density ハンドル + phase | `ActionProposal[]` (ReviseStructure/AddPhase, 具体 evidence: frac/element/occ) |
| `edit_cif` | CIF ハンドル + `AtomEdit[]` | 新 CIF ハンドル (→ refine_with_revisions が ReviseStructure で参照) |

- `mem_density` は `mem.gsas.run_dysnomia_mem` を遅延 import で駆動 (Dysnomia 未導入は
  `MEMUnavailableError` を MCP エラー dict へ; 既存 `run_mem` 縮退規約と同型)。
- 閉ループ丸ごとは出さない (③ が回す; §0 反転回避)。非破壊/認可境界は既存 MCP と同一。

### ③ Claude Code プラグイン (R5 判断層)

**`plugins/tsumugin/skills/mem-model-fix/SKILL.md` (新規)** + `/mem-fix` command。
- 手順: 収束モデルを受け → `mem_density` → `propose_structure_revisions` → **密度の結晶学的読み
  (§1 の表)** で欠損原子/分割/占有を判断 → **ユーザー承認** → `edit_cif` →
  `refine_with_revisions(ReviseStructure)` → 受理判定 (Rwp∧validity) → 反復。
- 権限境界 (architecture.md §4.5 厳守): **構造編集は必ずユーザー承認**。密度解釈の根拠 (どのピークを
  何と読んだか・元素/占有の推定根拠) を提示してから編集。
- 既存 `analyze` skill に「Rwp 停滞・validity fail のとき mem-model-fix を呼ぶ」導線を 1 行追加。
- Codex 等へは AGENT_PLAYBOOK に同手順を移植 (ポータブル)。

## 3. 段階計画 (Kairo/TDD)

- **Phase A — ① cif_edit**: `apply_atom_edits` (add/move/occ/remove) + `AtomEdit`。純テキスト/numpy
  テスト (CIF 往復・原子追加/占有更新・元 CIF 不変)。
- **Phase B — ① mem_diagnostics**: `propose_structure_revisions_from_mem` + evidence 具体化。
  純テスト (モック `MEMDensityResult` → 期待 ReviseStructure/element/occ、決定論順)。
- **Phase C — ② MCP 3 ツール**: `mem_density`/`propose_structure_revisions`/`edit_cif` +
  gpx/CIF ハンドル管理。決定論スタブ e2e + Dysnomia 未導入縮退。gated 実 MEM 契約テスト。
- **Phase D — ③ skill/command**: `mem-model-fix` SKILL + `/mem-fix` + `analyze` からの導線。
  乾式レビュー + MCP 契約テスト。
- **Phase E — 実データ検証**: NaCuHCF で「未モデル核密度 → 候補提示 → (承認) → CIF 編集 → 再精密化」
  を 1 サイクル通し、Rwp∧validity で受理/棄却を確認 (今回の MEM 解析で局在未モデル密度が無い事を
  逆に「修正不要」判定として検証; 局在ピークを持つ別データで加点例)。

## 4. 不変条件 (M8 継承)

- **提案 ≠ 適用**: ①/② は提案・計器・アクチュエータのみ。採否と結晶学判断は ③。
- **構造編集はユーザー承認** (③ の権限境界)。**受理は Rwp 改善 ∧ `validity.passed` 維持** (過剰適合ガード)。
- **P2 非破壊**: CIF 編集は新ファイル生成 (元不変)、gpx はコピー、ledger 追記 + snapshot revert。
- **コア import は numpy のみ** (GSAS/Dysnomia は `mem.gsas`/MCP 内遅延、LLM は ③ = ライブラリ外)。
- **決定論** (NFR-102): mem_diagnostics/cif_edit はビット同一。MEM は同一 gpx で決定論。

## 5. スコープ外 (M-later)

- 原子座標の大域探索・空間群自動決定 (`ReviseStructure` の入力として外部ソルバへ委譲)。
- MEM 密度からの元素種の自動確定 (③ の化学判断 + `chem` 降格に委ねる; ②は候補提示のみ)。
- MPF (`mem.mpf`) との統合自動反復 (まず 1 サイクル手動確認を優先)。
