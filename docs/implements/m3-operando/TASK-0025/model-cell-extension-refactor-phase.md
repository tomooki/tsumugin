# TDD Refactor フェーズ: model 拡張 (TASK-0025)

## 実施日時

2026-07-04

## 対象

- 実装: `src/tsumugin/model/cell.py` (CellLayer / BeamConfig / CellConfig / MuCalculator / XraylibMuCalculator)
- テスト: `tests/test_model_m3.py` (N-06 / B-06 の期待値修正)
- 文書: `docs/implements/m3-operando/TASK-0025/note.md` (asdict 挙動の記述訂正)

## リファクタリングの主眼: `_LayerTuple` equality ハックの除去

### 問題 (Green フェーズの技術的負債)

Green フェーズは `CellConfig.layers` に `_LayerTuple(tuple)` サブクラスを導入していた。これは
`__eq__` を override して **tuple と list を同一視** (`_LayerTuple((x,)) == [x]` を True に) するもので、
`__post_init__` で `object.__setattr__` により layers を `_LayerTuple` へ差し替えていた。

導入理由は、テストが同時に以下 2 つを要求していたためと記録されていた:
1. `config.layers == (CellLayer(...),)` … tuple 等価
2. `dataclasses.asdict(config)["layers"] == [ {...} ]` … list 等価

### 根本原因: テスト定義の矛盾

`dataclasses.asdict` は **CPython 仕様上 tuple 型を保持する** (list へ変換しない)。
`_asdict_inner` が `(list, tuple)` 分岐で `type(obj)(...)` を用いて同じ型を再生成するため、
plain tuple を渡せば結果も plain tuple になる。実測でも確認済み:

```
>>> dataclasses.asdict(CellConfig(geometry="transmission",
...     layers=(CellLayer("window","Be",0.5),)))["layers"]
({'role': 'window', 'material': 'Be', 'thickness_mm': 0.5, 'density': None},)  # tuple
```

したがって「asdict で layers が list になる」を期待する N-06 / B-06 は **Python 仕様に反する誤ったテスト定義**
であり、`_LayerTuple` はこの誤った期待に実装を歪めて合わせるハックだった。tuple が list と `==` になる挙動は
`==` の型契約 (対称性・Liskov) を壊すため保守上も有害。

### 改善内容

1. **`src/tsumugin/model/cell.py`**
   - `_LayerTuple` クラスを **完全削除** (`__eq__` / `__ne__` / `__hash__` override, `__slots__` 含む)。
   - `CellConfig.__post_init__` (layers を `_LayerTuple` へ寄せる正規化) を **削除**。
   - `layers: tuple[CellLayer, ...] = ()` を**素の tuple のまま**に戻した (interfaces.py L59-67 契約どおり)。
   - docstring に【シリアライズ契約】節を追加: asdict は tuple 型を保持する / equality ハックは設けない旨を明記。

2. **`tests/test_model_m3.py`** (テスト定義の誤りを Python 仕様に合わせて訂正、理由コメント付き)
   - N-06 `test_cell_config_asdict_serializes_nested_to_json_native`:
     `d["layers"] == [ {...} ]` → `d["layers"] == ( {...}, )` (tuple 期待)。
     コメントに「dataclasses.asdict は tuple を list へ変換せず tuple のまま再帰生成する (Python 仕様)」を明記。
   - B-06 `test_cell_config_empty_layers_asdict`:
     `"layers": []` → `"layers": ()` (空 tuple 期待)。同旨の理由コメントを付与。
   - 信頼性レベルを 🟡 → 🔵 に更新 (標準ライブラリの確定挙動に依拠するため)。

3. **`note.md`**: 「asdict が tuple を dict/list へ展開」という誤記述を「tuple は tuple のまま保持」に訂正。

### 対称性の保証

除去後、`CellConfig.layers` は plain tuple。`tuple == list` は常に False という Python の標準契約が回復し、
`==` の対称性 (`a == b` ⇔ `b == a`) を壊す実装は残っていない。`_LayerTuple` の全参照はコードベースから消滅
(grep 0 件)。

## セキュリティレビュー

- 純データ層 (dataclass のみ)。外部入力・IO・SQL・シリアライズ eval なし。脆弱性の新規混入なし。
- `XraylibMuCalculator.mu_t` は fail-loud (`NotImplementedError`) を維持し、沈黙した誤値を返さない。

## パフォーマンスレビュー

- `__post_init__` での tuple 再生成 (O(n) コピー) と `_LayerTuple.__eq__` の per-compare な `list()` 変換が
  **消滅**し、生成・比較ともに標準 dataclass/tuple の実装に戻り、わずかに高速化・軽量化。
- 計算量・メモリ上の懸念なし (層数は小さい)。

## テスト実行結果

- `uv run pytest tests/test_model_m3.py -q` → **21 passed** (正常系 10 / 異常系 4 / 境界値 7)。
- `uvx ruff check src/tsumugin/model tests/test_model_m3.py` → **All checks passed** (line-length 100)。
- 遅いテスト (2 秒以上) なし。
- 開発時生成ファイル (debug-*/temp-*/*.bak 等) なし。テスト skip / 除外設定なし。

## 品質判定

✅ 高品質:
- テスト全継続成功 (21/21)
- 重大なセキュリティ脆弱性なし
- 重大な性能課題なし (むしろハック除去で改善)
- リファクタ目標達成 (`_LayerTuple` ハック除去・== 対称性回復・素 tuple 復帰)
- コード品質向上 (cell.py 129→98 行、ハック・post_init 消滅)
- ドキュメント整合 (テスト理由コメント・docstring・note.md 訂正)
