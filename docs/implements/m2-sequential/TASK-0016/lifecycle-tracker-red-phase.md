# TASK-0016 Red フェーズ記録: LifecycleTracker

**機能名**: LifecycleTracker / **要件名**: m2-sequential / **タスクID**: TASK-0016
**テストファイル**: `tests/test_lifecycle.py` (新規) / **対象実装 (未実装)**: `src/tsumugin/sequential/lifecycle.py`
**作成日時**: 2026-07-03 / **フェーズ**: Red (失敗するテスト作成)

---

## 1. 作成したテストケース一覧 (13 件)

| ID | テスト関数 | 分類 | 検証内容 | 信頼性 |
|---|---|---|---|---|
| N-01 | `test_birth_confirmed_after_hysteresis` | 正常系 | 連続 3 フレーム present → `birth_frame==10` (連続開始) | 🔵 |
| N-02 | `test_death_confirmed_after_absent_hysteresis` | 正常系 | 連続 3 フレーム absent → `death_frame==15` (不在開始) | 🔵 |
| N-03 | `test_death_cancelled_on_reappear_within_window` | 正常系 | 窓内 (2<3) 再出現 → `death_frame is None` (REQ-201) | 🔵 |
| N-04 | `test_all_frames_present_confidence_one` | 正常系 | 全存在 → birth=0/death=None/`confidence==1.0` | 🟡 |
| N-05 | `test_multiple_phases_tracked_independently` | 正常系 | A/B 独立追跡 (key={A,B}, 各 birth/death 確定) | 🔵 |
| N-06 | `test_lifecycle_config_defaults_frozen_and_reexport` | 正常系 | 既定値 (3/1e-3)・frozen・`sequential.__all__` 公開 | 🔵 |
| E-01 | `test_single_frame_flicker_not_birth` | 異常系 | 1 フレーム点滅 → birth 非認定 (キーなし) TC-103-03 | 🔵 |
| E-02 | `test_empty_observation_returns_empty_mapping` | 異常系 | observe 無し finalize → `{}` (EDGE-001) | 🟡 |
| E-03 | `test_absent_run_reaching_window_confirms_death` | 異常系 | 不在=N 後の再出現でも `death_frame==15` (N-03 対偶) | 🔵 |
| B-01 | `test_birth_boundary_exactly_n_frames` | 境界値 | (a) N-1=2→キーなし / (b) N=3→`birth_frame==10` | 🔵 |
| B-02 | `test_death_cancelled_at_window_minus_one` | 境界値 | 不在 N-1=2 で再出現 → `death_frame is None` | 🔵 |
| B-03 | `test_single_frame_observation_no_birth` | 境界値 | 1 フレーム観測 → birth 未確定・例外なし (EDGE-101) | 🟡 |
| B-04 | `test_confidence_is_presence_fraction` | 境界値 | present 7/10 → `confidence==0.7` (0<c<1) | 🟡 |

内訳: 正常系 6 / 異常系 3 / 境界値 4 = **13 件** (テストケース定義と一致)。

---

## 2. Red フェーズで固定した意味論 (🟡 判断点の決定)

要件定義に残っていた 🟡 判断点をテストで以下のとおり固定した:

1. **confidence の分母** = **総観測フレーム数** (observe 呼び出し総数)。
   - N-04: 全 10 フレーム present の C → 10/10 = 1.0。
   - B-04: 全 10 フレームのうち D が 7 present → 7/10 = 0.7。
2. **death 確定後の再出現の扱い** = 窓 (連続 N) を満たした不在は death 確定し、以後の再出現で**取り消さない** (E-03)。取り消しは不在ランが hysteresis **未満**のうちの再出現のみ (N-03 / B-02)。
3. **birth 未確定の相の扱い** = `finalize()` の返り値**キーに含めない** (E-01 / B-01(a) / B-03)。

---

## 3. 期待される失敗内容 (Red 確認済み)

```
ERROR collecting tests/test_lifecycle.py
E   ModuleNotFoundError: No module named 'tsumugin.sequential.lifecycle'
```

- 対象モジュール `src/tsumugin/sequential/lifecycle.py` 未実装のため、import が collection 時に失敗し
  全 13 テストがエラー (=失敗) になる。これは想定どおりの Red 状態。
- `uvx ruff check tests/test_lifecycle.py` → All checks passed! (line-length 100 準拠)。

---

## 4. Green フェーズで実装すべき内容

`src/tsumugin/sequential/lifecycle.py` を新設:

- **`LifecycleConfig`** — `@dataclass(frozen=True)`。`hysteresis: int = 3`, `presence_wt_frac: float = 1e-3`。
- **`LifecycleTracker`** — ステートフルクラス:
  - `__init__(self, *, config: LifecycleConfig = LifecycleConfig())`: 相ごとの可変状態を初期化。
  - `observe(self, frame_index: int, present_refs: Sequence[str])`: 相ごとに連続 present/absent ランの
    開始 frame とカウントを更新。連続 present が hysteresis 到達で birth 確定 (連続開始 frame)、
    連続 absent が hysteresis 到達で death 確定 (不在開始 frame)。不在ラン < hysteresis 中の再出現は不在ランをリセット。
    観測フレーム総数と相ごとの present フレーム数を計上 (confidence 用)。
  - `finalize(self) -> Mapping[str, PhaseLifecycle]`: birth 確定済みの相のみを安定順序で辞書化。
    各相を `PhaseLifecycle(birth_frame, death_frame, confidence=present数/総観測数)` で生成 (既存型を再利用)。
- **`src/tsumugin/sequential/__init__.py`**: `__all__` に `LifecycleConfig` / `LifecycleTracker` を昇順追加し re-export。

制約: 決定論 (乱数不使用・安定走査順)、`PhaseLifecycle` は `model/phase.py` の既存型を再利用 (新設しない)。
