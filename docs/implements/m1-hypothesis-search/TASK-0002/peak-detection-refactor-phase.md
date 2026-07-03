# TASK-0002 観測ピーク検出 find_peaks — Refactor フェーズ記録

**機能名**: 観測ピーク検出 find_peaks
**タスクID**: TASK-0002 / **要件名**: m1-hypothesis-search
**作成日**: 2026-07-03
**対象実装**: `src/tsumugin/search/peaks.py`
**対象テスト**: `tests/test_peaks.py`（15 関数 / 収集 17 項目・変更なし）

---

## 1. 前提

Green 実装は既に refactor 級の品質（構造化日本語コメント・型注釈完備・エッジ縮退の明示ガード）で
書かれていた。本フェーズは観点（可読性・docstring・重複排除・型注釈・命名）を精査し、
YAGNI を守って**過剰な抽象化はせず**、明確な純利益のある最小変更のみ適用した。

## 2. 適用した改善

### 改善1: numpy イディオムの整理（可読性）🔵

- `np.nonzero(interior)[0] + 1` → `np.flatnonzero(interior) + 1`
- `flatnonzero` は 1 次元配列の非ゼロ位置を昇順で直接返すため、`nonzero(...)[0]` の
  タプル添字（`[0]`）ノイズが消える。挙動は完全同値（1 次元では返り値・順序とも一致）。
- リスク: なし（決定論・順序・件数すべて不変）。

### 改善2: docstring の Green フェーズ残滓を除去（docstring の質）🔵

- 旧 `【テスト対応】: ... 15 テストを通す最小実装。` は Green 期の記述で post-refactor では不正確。
- `【実装方針】` に統合し、`_count_local_maxima` との関係（後述）を明文化して置換。

## 3. 重複排除の判断（`_count_local_maxima` との関係確認）— **共通化しない** 🔵

局所極大マスク式
`(y[1:-1] > y[:-2]) & (y[1:-1] > y[2:]) & (y[1:-1] > min_height)` は
`tests/test_simulated_backend.py::_count_local_maxima` と同一。だが共通化は**行わない**:

1. **役割が異なる**: `_count_local_maxima` は `simulate` 出力を **find_peaks とは独立に**検証する
   count 専用オラクル。ここを find_peaks へ差し替えると `test_simulate_produces_one_maximum_...`
   が実装依存になり、テストのクロスチェック性（独立オラクル）が失われる。
2. **シグネチャが異なる**: 一方は絶対 `min_height` を取り `int` を返し、他方は `min_height_frac` を
   取り `tuple[Peak, ...]` を返す。共通化には不自然なラッパが必要。
3. **YAGNI**: 1 行のベクトル式を production へ抽出し test から import させるのは過剰。
   意図を docstring に明記して別実装のまま残す方が保守的。

→ 制約「テストの意味を変えない」にも合致（テスト側は無変更）。

## 4. 変更しなかった項目（過剰実装の回避）

- **命名 `x` / `y`**: 科学計算で軸を表す慣用。引数 `two_theta` / `intensity` から正規化した局所変数で、
  コメントも付く。冗長改名（`two_theta_f` 等）は可読性を下げるため据え置き。
- **`interior` 変数名**: 手本 `_count_local_maxima` と一致し、意味（内部点マスク）も通る。
- **型注釈 `np.ndarray`**: プロジェクト全体（simulated backend / 既存テスト）の慣用。
  `NDArray[np.float64]` 化は他モジュールと不整合になり YAGNI。
- **信頼性マーカー（🔵🟡🔴）・構造化コメント**: tsumiki TDD 規約の想定形式のため維持。

## 5. セキュリティレビュー 🔵

- **入力**: 外部信頼境界なし（内部数値コンポーネント）。文字列・パス・SQL・シリアライズ・
  ネットワーク・eval 等の攻撃面は皆無。SQLi/XSS/CSRF は非該当。
- **入力検証**: `np.asarray(dtype=float)` で正規化。`size < 3` と `max<=0` を早期ガードし、
  空配列 `max()`（ValueError）やゼロ/負閾値による比較破綻・ゼロ除算を回避。例外は送出せず縮退。
- **副作用**: 純関数（引数を破壊せず、`asarray` の新規配列で作業）。frozen dataclass で返り値も不変。
- **結論**: 重大な脆弱性なし。

## 6. パフォーマンスレビュー 🔵

- **時間計算量**: O(N)（N = グリッド点数）。マスク生成はベクトル化 3 比較、`flatnonzero` は O(N)。
- **空間計算量**: O(N)（float 正規化配列＋真偽マスク）。ピーク生成は検出数 K に比例（K ≪ N）。
- **ソート不要**: `two_theta` 昇順前提＋`flatnonzero` の昇順出力で position 昇順が自動保証。追加ソートなし。
- NFR-103（3 分 / 300 相）に対し本関数はボトルネックにならない。**重大な性能課題なし**。

## 7. テスト実行結果

- `uv run pytest`: **87 passed, 1 skipped**（skip は `@pytest.mark.gsas` の未導入自動 skip）。
  `tests/test_peaks.py` は 17 項目すべて green。実行 ≈ 5s（2 秒超の遅いテストなし）。
- `uvx ruff check src tests`: **All checks passed!**
- 実行時の `Error reading {cfgfile}`（cp932）は GSAS-II の既知・無害警告（CLAUDE.md 記載）。

## 8. 品質判定

```
✅ 高品質:
- テスト: 全 green 継続（87 passed / 1 skipped, peaks 17 項目 green）
- セキュリティ: 重大な脆弱性なし
- パフォーマンス: O(N)・追加ソートなし、重大な性能課題なし
- リファクタ品質: 可読性・docstring を純利益で改善、YAGNI 遵守（過剰抽象化なし）
- コード品質: ruff clean、69 行（500 行制限内）
- 重複排除: _count_local_maxima との関係を精査し「意図的に別実装」を明文化
```

## 9. 最終コード（`src/tsumugin/search/peaks.py`）

diff の要点のみ（全文はソース参照）:
- `np.nonzero(interior)[0] + 1` → `np.flatnonzero(interior) + 1`（＋説明コメント 1 行）
- docstring `【実装方針】` を `_count_local_maxima` 非共通化の理由込みに置換、`【テスト対応】` 行を削除。
