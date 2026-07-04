# TASK-0028 TDD Refactorフェーズ記録: multistart/basin + MultistartEngine (FR-230/232)

**要件名**: m3-operando / **タスクID**: TASK-0028 / **機能名**: multistart-basin-engine
**実施日**: 2026-07-04 / **対象**: `src/tsumugin/multistart/basin.py` / `src/tsumugin/multistart/engine.py`

> 本書のすべてのファイルパスはプロジェクトルートからの相対パス。

---

## 1. リファクタリング方針と実施内容

改善観点は「`MultistartEngine.run()` のフェーズ分解・可読性」(YAGNI 原則、変更不要判断可)。
機能的な変更は一切なし (テスト 18 件・既存テストとも無改変で全 green 維持)。

### 改善 1: `run()` のフェーズ分解 — direct refine ループを `_refine_starts()` へ抽出 🔵

- **改善内容**: `run()` に内包されていた direct refine ループ (~20 行: RefinementModel 構築 →
  `backend.refine` → ledger 記録 → 発散仕分け) をプライベートヘルパ
  `_refine_starts(starts, free_params, two_theta, intensity, weights)
  -> tuple[list[int], list[RefinementResult], int]` へ抽出。
- **設計方針**: `run()` が「フェーズ 1: 摂動列生成 → フェーズ 2: direct refine → フェーズ 3:
  basin クラスタ → フェーズ 4: 傍証判定・昇格 → フェーズ 5: 全滅縮退 → フェーズ 6: 結果集約」
  の読める薄いオーケストレータになる (note.md §1「薄いオーケストレータ」設計に整合)。
  各ブロックのコメントを【フェーズ n: ...】で統一し流れを明示。
- **単一責任**: `_refine_starts` は精密化と発散仕分けのみを担当。純関数ループ (map 置換可能 /
  REQ-005) の性質・ledger 記録順・発散判定 (`math.isfinite`) は完全に不変。
- 🔵 信頼性レベル: architecture.md D2 / REQ-005/102 / TC-E05・A01 の既存契約の等価変形。

```python
def _refine_starts(
    self,
    starts: Sequence[tuple[PhaseInstance, ...]],
    free_params: frozenset[str],
    two_theta: np.ndarray,
    intensity: np.ndarray,
    weights: np.ndarray | None,
) -> tuple[list[int], list[RefinementResult], int]:
    """【ヘルパー関数】: 各 start を direct refine し発散除外済みの生存解列を返す。"""
    surviving_indices: list[int] = []
    surviving_results: list[RefinementResult] = []
    n_diverged = 0
    for index, phases_i in enumerate(starts):
        model = RefinementModel(
            phases=phases_i,
            free_params=free_params,
            two_theta=two_theta,
            intensity=intensity,
            weights=weights,
        )
        result = self.backend.refine(model, max_cycles=self.config.ms_max_cycles)
        self._record("multistart.start", {"start": index, "chi2": result.chi2})
        if math.isfinite(result.chi2):
            surviving_indices.append(index)
            surviving_results.append(result)
        else:
            n_diverged += 1
    return surviving_indices, surviving_results, n_diverged
```

`run()` 側の呼び出し (フェーズ 2):

```python
# 【フェーズ 2: direct refine】: 各 start を独立に精密化し発散を除外・カウント (D2/REQ-102) 🔵
surviving_indices, surviving_results, n_diverged = self._refine_starts(
    starts, free_params, two_theta, intensity, weights
)
```

### 改善 2: `_record` の payload 型を `dict` → `Mapping[str, object]` へ 🔵

- **改善内容**: `Ledger.append(kind, payload: Mapping[str, Any])` の契約に合わせ、
  `_record(self, kind: str, payload: Mapping[str, object])` へ型を精密化
  (`collections.abc.Mapping` を import)。挙動不変・呼び出し側変更なし。
- 🔵 信頼性レベル: `src/tsumugin/store/ledger.py` L70 の実シグネチャに整合。

### 変更不要判断 (YAGNI) 🔵

- **`basin.py` は無変更**: 既に小さな純関数 (`_evidence_of` / `_normalized_vector` / `_distance` /
  `cluster_basins`) へ分解済みで 174 行 (< 500 行制限)。日本語コメント・信頼性レベルも整備済み。
- **テストは無改変**: `tests/test_multistart_engine.py` (18 件) は 1 行も変更していない。
- **`_remap_basins` / `_promote` / `_record` の構造も維持**: すでに単一責任で分割済み。
- 追加の抽象化 (基底クラス・戦略パターン等) は現時点の要求にないため導入しない (YAGNI)。

---

## 2. セキュリティレビュー結果 ✅ 重大な脆弱性なし

- **攻撃面**: 純粋なインメモリ数値計算のみ。ネットワーク・ファイル I/O・SQL・eval/exec・
  シリアライズなし → インジェクション/XSS/CSRF は該当外。
- **入力検証・縮退**: 発散 (chi2 非有限) は `math.isfinite` で例外化せず縮退 (REQ-102)。
  `basin.py` の `_TINY = 1e-12` が 0 除算・log 定義域を下限ガード。空入力は空タプル縮退。
- **非破壊性 (P2)**: 入力 `phases` は読み取りのみ (摂動は `generate_starts` が新 tuple を生成)。
  ledger は `append` のみ使用 (削除・上書き API なし / NFR-105、実行後 `verify()` True を TC-E06 で確認)。
- **依存**: コア依存は numpy のみ (REQ-403)。追加依存なし。

## 3. パフォーマンスレビュー結果 ✅ 重大な性能課題なし

- **basin クラスタ**: 全対距離 O(n²·d) + union-find (経路圧縮) — n = 生存 start 数 (既定 8、
  実用上も数十) で十分軽量。ベクトル化 (numpy 化) は現規模で利得なし (YAGNI)。
- **engine**: `backend.refine` × N が支配項 (設計どおり)。エンジン自身のオーバーヘッドは O(N)。
  純関数ループのため将来の map 並列化 (FR-234) を阻害しない。
- **テスト実行時間**: 18 件 0.73s、2 秒以上の遅いテストなし (`--durations` で確認)。

## 4. テスト実行結果 ✅ 全 green 維持

```
uv run pytest tests/test_multistart_engine.py -q  → 18 passed (リファクタ前後とも)
uvx ruff check src tests                          → All checks passed!
```

- リファクタ前 18 passed → 改善 1・2 適用後も 18 passed (機能不変を確認)。
- skip/xfail なし。テスト除外設定 (testPathIgnorePatterns 等) なし。
- 開発時生成ファイル (debug-*/temp-*/*.bak 等) なし (検出 0 件、削除対象なし)。

## 5. コメント改善内容

- `run()` の各ブロックコメントを【フェーズ 1〜6】へ統一し処理の流れを明示。
- `_refine_starts` に【ヘルパー関数】/【機能概要】/【改善内容】/【設計方針】/【単一責任】+
  信頼性レベル 🔵 + @param/@returns の docstring を付与。
- `_record` docstring に【改善内容】(型精密化の理由) を追記。

## 6. 品質判定 ✅ 高品質

```
- テスト結果: 18/18 green 継続 (機能不変)
- セキュリティ: 重大な脆弱性なし
- パフォーマンス: 重大な性能課題なし
- リファクタ品質: 目標達成 (run() フェーズ分解・可読性向上、YAGNI 遵守)
- ファイルサイズ: engine.py 282 行 / basin.py 174 行 (< 500 行制限)
- コード品質: ruff clean / 日本語コメント + 信頼性レベル整備
```

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-verify-complete m3-operando TASK-0028` で完全性検証を実行します。
