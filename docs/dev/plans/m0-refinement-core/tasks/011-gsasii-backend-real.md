---
id: "011"
title: "GSAS-II を導入し GSASIIBackend.refine/simulate を実装"
status: done
priority: 2
dependencies: ["004", "008"]
estimated_complexity: high
---

# Task: GSAS-II を導入し GSASIIBackend.refine/simulate を実装

## Goal

GSAS-II を環境に導入し、GSASIIBackend を薄いスタブから実際の Rietveld 精密化エンジンに
昇格させる。契約テスト (`@pytest.mark.gsas`) を実 GSAS-II で green にする。

## 導入方式 (Windows / コンパイラなし環境)

公式は Windows での pip ビルドを非推奨 (gfortran/gcc 必要) のため、GSAS-II 自身が
サポートするソースツリー + ビルド済みバイナリ方式を採用:

1. `git clone --depth 1 https://github.com/AdvancedPhotonSource/GSAS-II.git C:\Users\tomoo\G2`
2. venv site-packages に `gsas2-source.pth` (中身は `C:\Users\tomoo\G2`) を置き `import GSASII` を可能に
3. コンパイル済みバイナリを GSAS-II 付属関数でダウンロード:
   `GSASIIpath.getGitBinaryLoc()` → `InstallGitBinary(url, ~/.GSASII/GSASII-bin, nameByVersion=True)`
   (win_64_p3.12_n2.2 が `pathHacking._path_discovery` により自動発見される)
4. ランタイム依存は pyproject の extra: `uv sync --extra gsas` (scipy, pycifrw, requests)

## Interfaces

```python
# tsumugin/backends/gsasii.py
def gsasii_available() -> bool          # 🔵 GSASII.GSASIIscriptable の実 import で判定 (lru_cache)

class GSASIIBackend:                    # 🔵 RefinementBackend 実装
    name = "gsasii"
    def __init__(self, *, wavelength: float = 1.5406): ...   # 未導入なら GSASUnavailableError
    def simulate(self, phases, two_theta) -> np.ndarray      # 🟡 noise-free Ycalc を返す
    def refine(self, model, *, max_cycles=20) -> RefinementResult
```

パラメータマッピング (M1 最小):
- `phase{i}.scale` → HAP Scale (相分率) の refine flag
- `phase{i}.lattice.*` → phase Cell refine (対称性の許す自由度をまとめて解放; P m m m で a/b/c 独立)
- その他 suffix (profile/texture/occupancy/coordinates/adp) → no-op (M2+ で拡張)

構造の簡約: 各相 = P m m m + Ni 1 原子 @ 原点の CIF。SimulatedBackend の直方 d 間隔模型と整合。
一時ファイル (.gpx/.xye/.instprm/.cif) は tempfile 配下で生成し自動破棄。

## Test Strategy

- [x] `gsasii_available()` が bool を返し例外を投げない
- [x] simulate が有限値・ピークありのパターンを返す
- [x] noop refine (解放 0) が metrics を返す (n_params==0)
- [x] scale 解放で rwp が noop 比で改善し scale が動く
- [x] lattice.a 解放で真値 4.0 を ±0.005 で回収
- [x] StagedRefinementEngine が実バックエンドで escalated=False・格子回収・ledger verify
- [x] analyze_single_pattern が正解構造を 1 位にランキング

## Implementation Notes

- 精密化失敗 (GSAS-II 例外) は chi2=inf の RefinementResult に変換し、ガードレール側で
  ロールバック処理させる (エンジンをクラッシュさせない)。
- chi2/rwp はヒストグラム配列 (yobs, w, ycalc) から自前計算し、SimulatedBackend と同一
  セマンティクスを保証 (BIC 比較の一貫性)。n_params は GSAS の varyList 長。
- **ガード修正**: ノイズフリーデータで chi2≈0 のとき数値ゆらぎが比率ベースの発散検知を
  誤発動させたため、GuardConfig に `chi2_worsen_floor_per_obs` (絶対増分の下限) を追加。

## Files

- 変更: src/tsumugin/backends/gsasii.py (全面実装),
        src/tsumugin/refinement/guardrails.py (floor 追加), pyproject.toml (gsas extra)
- テスト: tests/test_gsasii_backend.py (7), tests/test_guardrails.py (+1)
