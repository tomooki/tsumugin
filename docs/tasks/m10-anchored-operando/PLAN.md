# M10 アンカー基準双方向 operando 解析 タスク分割 (kairo-tasks)

仕様 FR-330 / 要件 `docs/spec/m10-anchored-operando/requirements.md` / 設計
`docs/design/m10-anchored-operando/architecture.md`。ブランチ: `milestone/m10-anchored-operando`。
全タスク TDD (Red→Green→Refactor)、モデル指定 Opus、タスク 1 件 = 1 コミット。

## 依存グラフ

```
T1 model ─┬─ T2 extract ─┐
          ├─ T3 segment ─┼─ T5 engine ── T7 実データ検証 ── T8 review/PR
          └─ T4 select ──┘
             T6 validity (並行, T5 が利用)
```

## タスク

### T1 — `anchor/model.py` (dataclass 群)
- **成果**: `AnchorConfig` (anchor_confidence_min, anchor_rwp_max, 重み w1..w4, bic_tie, bond_tol_lo/hi,
  hysteresis_frames, 期待配位数マップ), `Anchor` (frame_index, phases, cell, rwp, confidence),
  `Segment` (left/right anchor idx, inner range, one_sided), `SegmentPass` (方向, per-frame 結果),
  `CrossoverChoice` (k, total_bic_fwd/bwd, onset, monotonic)。全 frozen + `with_updates`。
- **テスト**: 不変性・既定値・決定論的等価 (REQ-1019)。
- **AC**: numpy 非依存 import、ruff green。

### T2 — `anchor/extract.py` (アンカー抽出 2 段ゲート, FR-331)
- **成果**: `anchor_confidence(ident, cfg)` (Dara スコア + マージン − strain − 未知相),
  `extract_anchors(frames, base_phases, runner, identifier, cfg)` (段階 A スクリーニング → 段階 B
  Rietveld+validity 確認 → 確定/fallback/後方互換)。
- **テスト** (stub runner/identifier): REQ-1001 信頼度閾値、REQ-1002 2 段ゲート (高信頼だが Rwp 高 →
  棄却)、REQ-1003 fallback (確定 0 → 最小 Rwp 1 個)、REQ-1004 `phase_id=None` → frame 0。
- **AC**: 単相域が高信頼アンカー・転移域は非アンカーになる合成ケースが green。

### T3 — `anchor/segment.py` (双方向区間解析, FR-333)
- **成果**: `build_segments(anchors, n)` (フレーム順 + 端点片側), `refine_segment_forward/backward`
  (L/R 相集合で warm-start 逐次, runner 注入)。
- **テスト** (stub runner): REQ-1005/1006 warm-start 方向・相集合、REQ-1007 独立 2 回精密化、
  REQ-1008 端点片側区間。
- **AC**: 各内側フレームが前方・後方の 2 パスを持つ。

### T4 — `anchor/select.py` (crossover 選定, FR-334)
- **成果**: `segment_bic(pass_)`, `select_crossover(seg, fwd, bwd, cfg)` (同一相集合→Rwp 毎フレーム /
  異相集合→総 bic 最小 crossover 全探索 + 単調 tie-break), `assemble_path(...)` (経路連結 + onset)。
- **テスト** (stub): REQ-1009 相集合差で bic 使用、REQ-1010 crossover が転移点に一致、REQ-1011 単調
  tie-break、**bic vs Rwp 対比回帰** (Rwp 最小=全域 2 相 / bic 最小=転移後のみ; 設計判断①を固定)。
- **AC**: 合成 (前方 1 相 bic 高 / 後方 2 相 転移後のみ低) で k* = 転移フレーム。

### T5 — `anchor/engine.py` (オーケストレーション, FR-337)
- **成果**: `run_anchored_sequential(...)` → 抽出→区間→双方向→選定→組立→ledger→
  `SequentialRietveldResult`。`insitu.__init__` re-export。
- **テスト** (stub runner, numpy): エンドツーエンド決定論 (REQ-1019)、ledger 追記+verify (REQ-1016)、
  REQ-1017 出力型互換 (parametric が読める)、AC-3 単相系列→M9 相当に縮退。
- **AC**: insitu 全テスト green・ledger.verify()==True。

### T6 — `autorietveld/validity.py` 拡張 (結合距離/配位数, FR-335)
- **成果**: `check_bond_validity(structure_path, refined_cell, cfg)` (pymatgen `CrystalNN` 遅延 import),
  既存 `check_validity` と合成する `ValidityReport`。
- **テスト**: `@pytest.mark.gsas` or pymatgen gate — 妥当構造 pass / 結合距離潰れ (格子 0.5x) fail /
  pymatgen 不在 skip (REQ-1013 WHERE)。
- **AC**: 決定論、pymatgen 不在で graceful skip。

### T7 — 実データ検証 (`@pytest.mark.gsas`, AC-1/2/3)
- **成果**: CaTeO3 14 フレームを `run_anchored_sequential` で解析するスクリプト + 検証。
  alpha 単相域/delta 支配域がアンカー、転移を crossover で確定。**forward+consolidate と Rwp/偽相を比較**。
- **テスト**: gated 実データ (onset フレーム・転移域 Rwp・偽相なし)。
- **AC**: 転移域 Rwp が現行以下、偽相 (Ca3TeO6) が出ない、onset が物理的に妥当。

### T8 — `/code-review` ループ → PR
- **成果**: 差分に `/code-review`、MEDIUM/LOW まで修正 (誤検出/設計判断のみ理由付き見送り)、
  新規指摘が出るまでループ。PR 作成・セルフレビュー。CLAUDE.md アーキ表 + M ステータス更新。
- **AC**: レビュー収束、テスト green、`__all__` 昇順維持。マージはユーザー判断。

## リスクと緩和

| リスク | 緩和 |
|---|---|
| アンカーが転移両側に取れない (信頼度閾値が厳しすぎ) | fallback (REQ-1003) + 閾値を実データで校正。単相域は必ず高信頼 |
| bic の n_parm 計上がバックエンド間で不一致 | 既存 `_frame_bic`/`_bic_value` を単一ソースに再利用 (新規実装しない) |
| crossover が長区間で drift | 初版は固定アンカー。中間アンカー再帰細分化は M-later (スコープ外明記) |
| pymatgen 依存増 | 遅延 import + gate。不在で bic+既存 validity に縮退 (REQ-1013) |
| 計算コスト 2N | 区間独立を保ち並列 executor 余地を残す (本 M10 は逐次) |

## 検証コマンド

```
uv run pytest tests/insitu/anchor -q          # 決定論コア
uv run pytest -m gsas tests/insitu/anchor     # 実データ (GSAS+MP)
uvx ruff check src/tsumugin/insitu/anchor src/tsumugin/autorietveld/validity.py
```
