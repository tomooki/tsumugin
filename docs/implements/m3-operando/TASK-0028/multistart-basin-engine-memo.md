# multistart-basin-engine TDD開発完了記録

**要件名**: m3-operando / **タスクID**: TASK-0028 / **機能名**: multistart-basin-engine

## 確認すべきドキュメント

- `docs/tasks/m3-operando/TASK-0028.md`
- `docs/implements/m3-operando/TASK-0028/multistart-basin-engine-requirements.md`
- `docs/implements/m3-operando/TASK-0028/multistart-basin-engine-testcases.md`
- `docs/implements/m3-operando/TASK-0028/multistart-basin-engine-refactor-phase.md`
- `docs/implements/m3-operando/TASK-0028/note.md`

## 🎯 最終結果 (2026-07-04)

- **実装率**: 100% (18/18 テストケース、定義 TC-B01〜B03 / TC-E01〜E07 / TC-A01〜A02 / TC-BV01〜BV06 と 1:1)
- **テスト成功率**: 100% (スコープ内 18/18 green)
- **全体回帰**: 541 collected = **538 passed + 3 skipped / 0 failed** (ベースライン 523 + 新規 18、無退行)
  - skip 3 件は既存の環境条件付き skip (`tests/test_gpx_export.py` ×2 / `tests/test_gsasii_backend.py` ×1 —
    GSAS-II インストール済のため「未インストール経路」が対象外)。スコープ外・想定内。
- **品質判定**: ✅ 合格 (高品質 — 完全達成)
- **TODO更新**: ✅ 完了マーク追加 (`docs/tasks/m3-operando/TASK-0028.md` 完了条件 6 項目 checkbox 更新)
- **Lint**: `uvx ruff check src tests` clean / ファイルサイズ: engine.py 282 行・basin.py 174 行 (< 500)
- **テスト実行時間**: 全体 15.5s (< 30s)。2 秒超はスコープ外 `tests/test_gsasii_backend.py` の
  実バックエンドテスト 1 件 (2.10s) のみ (既存・本タスク無関係)。

## 💡 重要な技術学習

### 実装パターン

- **初期値スケール正規化 + union-find の basin クラスタ**: chi2 最小解をアンカーに格子=相対比 /
  scale=対数比 / 占有率=差分でベクトル化し、L∞ 相対距離 strict `<` tol を `_UnionFind`
  (search/clustering.py の再利用) で連結。代表 = chi2 最小 (同点 start index 小)、出力 evidence 昇順 —
  すべて安定順で決定論 (NFR-102)。
- **薄いオーケストレータ + フェーズ分解**: `MultistartEngine.run()` は「1 摂動列生成 → 2 direct refine
  (`_refine_starts` に抽出) → 3 basin クラスタ → 4 傍証判定・昇格 → 5 全滅縮退 → 6 結果集約」の
  6 フェーズ構成。refine ループは純関数 (map 置換可能 / REQ-005) で将来の並列化を阻害しない。
- **発散の縮退化**: バックエンド失敗は例外でなく chi2=inf → `math.isfinite` で除外し `n_diverged`
  カウント。全滅は `warnings` + 空 basins (元仮説維持)。例外を投げない (CLAUDE.md 不変条件)。
- **positional → start index 再マップ**: 発散除外で詰めた生存列を cluster_basins に渡し、
  member を `surviving_indices` で元 start index へ戻す (`_remap_basins`)。frozen dataclass は再構築。

### テスト設計

- **初期値依存 FakeBackend** (`InitialValueFakeBackend`): `model.phases[0].lattice.a` の閾値 (split) で
  2 吸引域へ写像し双峰を決定論的に再現。収束 phases を吸引域固定値へスナップして同一 basin の
  距離を 0 に畳む。発散注入 (diverge_starts / diverge_all) と呼び出し記録 (calls) を同一スタブに集約。
- **境界の較正テスト**: tol 直下/ちょうど/直上の 3 点で strict `<` を固定 (TC-BV01) — 🟡 だった
  距離式の意味づけをテストで 🔵 に確定する手法。
- **決定論はビット同一 `==`**: frozen dataclass の構造比較で basins/member_starts/promoted を一括検証。

### 品質保証

- **スコープ内/外の分離**: 全体回帰で新規 18 件 + 既存 523 件の無退行を確認。環境条件付き skip は
  失敗と区別して記録。
- **Refactor は機能不変の等価変形のみ**: run() フェーズ分解 (`_refine_starts` 抽出) と `_record` の
  型精密化 (`Mapping[str, object]`)。basin.py は YAGNI で変更不要判断。テスト無改変で green 維持。
- **セキュリティ/パフォーマンスレビュー**: 純インメモリ計算で脆弱性なし / O(n²) クラスタは n=8 規模で
  軽量、refine が支配項 (詳細は refactor-phase.md)。

## ⚠️ 注意点・修正が必要な項目

- なし (スコープ内テスト失敗 0、未実装要件 0)。
- 後続 TASK-0032 (FR-313 判別) が `MultistartEngine.run` を区間端点で必須適用する —
  `BasinInfo` / `MultistartResult` / `run` シグネチャは interfaces.py L143-191 契約どおり固定済み。

---
*既存のメモ内容から重要な情報を統合し、重複・詳細な経過記録は削除*
