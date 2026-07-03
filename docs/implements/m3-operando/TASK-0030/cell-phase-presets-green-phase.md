# TASK-0030 Green フェーズ記録: operando/cell_phases — セル固定相プリセット (FR-312)

**機能名**: cell-phase-presets / **タスクID**: TASK-0030 / **要件名**: m3-operando
**実装ファイル**: `src/tsumugin/operando/cell_phases.py` (新規) + `src/tsumugin/operando/__init__.py` (re-export)
**実装日時**: 2026-07-04

---

## 1. 実装方針

- `FixedPhaseSpec` を interfaces.py L236-241 契約どおり `phase: PhaseInstance` / `label: str` の
  frozen dataclass として実装 (探索メタ delta_u なし)。
- `CELL_PHASE_PRESETS` を `MappingProxyType` (読み取り専用・未定義キーは KeyError) でモジュールレベル
  不変定数として公開。Be/Al/graphite の 3 プリセット。
- 格子は直方近似: 六方晶 (Be/graphite) は `_orthohexagonal` で `b = a·√3`、立方晶 (Al) は `_cubic` で `a=b=c`。
  b は `a * math.sqrt(3.0)` で算出しテスト TC-BV01 とビット一致。
- `fixed_free_suffixes(spec)` は spec 非依存で常に `("scale",)` を返す (構造固定・scale のみ解放)。
- **docstring にモジュールレベルで直方近似・文献値出典・実回折とのずれの注意を明記** (完了条件・タスク指示)。
- `operando/__init__.py` に 3 シンボルを re-export 追加。model/backends は非破壊 (利用のみ)。

## 2. テスト実行結果

- 新規テスト単体: `uv run pytest tests/test_cell_phases.py` → **12 passed**。
- 全体回帰: `uv run pytest` → **565 passed, 3 skipped**。
- Lint: `uvx ruff@latest check src tests` → **All checks passed!**。

## 3. 課題・改善点 (Refactor フェーズ候補)

- 格子定数のマジックナンバーは docstring と実装本体・コメントに重複して現れる。定数化 (名前付き) や
  文献出典コメントの集約で可読性を上げられる余地がある (機能影響なし)。
- 現状 `_orthohexagonal` / `_cubic` の 2 ヘルパで十分だが、将来プリセット追加時の一貫性維持のため
  近似方針をテーブル駆動 (材料→結晶系→格子) に整理する余地がある。
