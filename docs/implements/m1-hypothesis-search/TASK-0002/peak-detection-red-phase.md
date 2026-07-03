# TASK-0002 観測ピーク検出 find_peaks — Red フェーズ記録

**機能名**: 観測ピーク検出 find_peaks
**タスクID**: TASK-0002 / **要件名**: m1-hypothesis-search
**作成日**: 2026-07-03
**テストファイル**: `tests/test_peaks.py`（新規）
**対象実装**: `src/tsumugin/search/peaks.py`（未実装 = Red）

---

## 1. 作成したテストケース一覧（15 件 / 収集 17 項目）

- 正常系（6）: N01 検出数=真の件数一致 / N02 位置±1グリッド以内 / N03 多相でピーク数増加 /
  N04 height=実測強度かつ閾値超過 / N05 昇順・不変タプル・frozen / N06 決定論（2回一致）。
- 異常系（4, EDGE-003）: E01 全ゼロ→空・例外なし / E02 一定値→空 / E03 全負値(max≤0)→空 /
  E04 単調増加（端点除外）→空。
- 境界値（5）: B01 配列長<3→空（parametrize ×3）/ B02 内部単一極大→1件 /
  B03 閾値上昇で微小ピーク脱落 / B04 高さ=閾値は厳密`>`で除外 / B05 プラトー頂点は不検出。

信頼性分布: 🔵 6 件 / 🟡 9 件 / 🔴 0 件。

## 2. テスト設計方針

- 書式は `tests/test_simulated_backend.py` を範とし、`_phase()` / `_grid()`（`np.arange(15.0,80.0,0.02)`）/
  `_backend()`（`SimulatedBackend(peak_fwhm=0.2)`）のモジュールレベルヘルパを共有。
- 教師データは決定論的合成バックエンドで生成し、`backend.peak_positions` を真のピーク位置とする。
- 数値比較は `pytest.approx`。frozen 検証は `dataclasses.FrozenInstanceError` を `pytest.raises` で確認。
- ruff line-length 100 を遵守。

## 3. 期待される失敗内容

```
$ uv run pytest tests/test_peaks.py
ERROR collecting tests/test_peaks.py
E   ModuleNotFoundError: No module named 'tsumugin.search.peaks'
!!! Interrupted: 1 error during collection !!!
```

`tsumugin.search.peaks`（`Peak` / `find_peaks`）が未実装のため、モジュール import が
collection 時に失敗し、全テスト（15 関数 / 17 項目）が失敗状態になる。既存テストは未変更。

## 4. Green フェーズで実装すべき内容

- `src/tsumugin/search/peaks.py` を numpy のみで新規実装。
  - `@dataclass(frozen=True) class Peak: position: float; height: float`
  - `find_peaks(two_theta, intensity, *, min_height_frac=0.05) -> tuple[Peak, ...]`
- 手順: float 正規化 → `min_height = min_height_frac * y.max()`（`y.max()<=0`・空配列を安全処理）→
  `interior = (y[1:-1] > y[:-2]) & (y[1:-1] > y[2:]) & (y[1:-1] > min_height)`（端点除外・厳密`>`）→
  `Peak(position=x[i], height=y[i])` を position 昇順の不変タプルで返す。失敗は例外化せず空タプル `()`。
- `src/tsumugin/search/__init__.py` の `__all__` に `Peak` / `find_peaks` を追加。
