# M12 実装計画: TOPAS バックエンド

ブランチ: `milestone/m12-topas-backend` / 設計: `docs/design/m12-topas-backend/architecture.md`

到達点はユーザー選択により **「第 2 段: `autorietveld` も Topas 化」** (= `RefinementBackend` 層 +
実構造段階解放エンジンの両方)、段階フラグは **TOF/joint まで**、バックエンド選択は
**② に `backend` 引数を新設**。

## 進捗

| # | タスク | 状態 | 備考 |
|---|---|---|---|
| T0 | 前提確認 (tc.exe がライセンス的に起動するか) | ✅ | CodeMeter ドングルで headless 起動。実測事実 9 件は設計 §2 |
| T1 | 可用性境界 (`topas.availability` / 例外 / marker) | ✅ | 明示指定は権威的・`=none` で強制無効化。skip ガードを 3 モードで実証 |
| T2 | INP 文書ビルダ (`topas.inp`) | ✅ | joint の `prm` 持ち上げ。実 tc.exe で受理・収束を確認 |
| T3 | CIF → `str` ブロック (`topas.structure`) | ✅ | 結晶系拘束。実 PbSO4 CIF で **Rwp 12.30 / GOF 2.49**・セル文献一致 |
| T5 | driver + パーサ (`topas.driver` / `topas.parse`) | ✅ | **終了コードで判定しない** (T0-3)。PATH に home を足す (T0-4)。失敗マーカー行は全部集約 |
| T4 | 装置パラメータ変換 (`topas.instrument`) | 🟡 | `.instprm`/`.PRM` 両対応・データは `.xye` へ。**プロファイル種付けは opt-in のまま** (係数スケール未検証) |
| T6 | 段階フラグ翻訳表 (`topas.flags`) | 🟡 | 13/17 フラグ。未対応は `UnsupportedStageFlagError` で明示的に失敗。残り: `tof_profile`/`absorption`/`hydrostatic_strain`/`preferred_orientation` |
| T8 | TOPAS 段階解放エンジン (`topas.engine`) | ✅ | **実 PbSO4 で Rwp 8.30 / GOF 1.68** (GSAS X 線単独 11.0% 超え) |
| T7 | 段方針の共通化 (`autorietveld.stagepolicy`) | ⬜ | リファクタ。受け入れ条件は gated T1–T4 の非回帰 |
| T9 | `backends.topas.TopasBackend` | ⬜ | Protocol + `simulate` (`iters 0` + `Out_X_Ycalc`) |
| T10 | バックエンド選択の配線 (①→②) | ⬜ | runner ファクトリ 6 箇所 + `backend` 引数 + `list_refinement_backends` |
| T11 | ③ 手順書 (skill / PLAYBOOK) + 恒久ガード | ⬜ | 変異させて fail することを実証してから受け入れる |
| T12 | 実データ検証 T1–T4 | ⬜ | GSAS 値と併記して `docs/benchmark/m12-topas/` へ |

## 受け入れ基準

```bash
uv run pytest -m "not gsas and not topas and not agent"   # 外部プログラム非依存 (CI と同じ集合)
uv run pytest -m gsas -k "engine_t1 or engine_t2 or engine_t3 or engine_t4"  # T7 の非回帰
uv run pytest -m topas                                     # 実 tc.exe 経路
uv run ruff check src tests
```

③ からの到達確認 (テスト green ≠ 完了): MCP 経由で `list_refinement_backends` →
`auto_rietveld(backend="topas", ...)` を **JSON 引数だけ**で通し、`result["backend"] == "topas"` と
有限の `final_rwp` を確認する。callable の `runner` を使わずに実行できることが受け入れ条件。

## T12 の合格基準

| # | 系 | GSAS-II 実績 | TOPAS 合格基準 |
|---|---|---|---|
| T1 | fluoroapatite 単相ラボ X 線 | 9.83% | Rwp ≤ 12% |
| T2 | garnet 単相 CW 中性子 (Fe/Al 混合占有) | 4.33% | Rwp ≤ 6.5% + 占有率和 = 1 充足 |
| T3 | PbSO4 X 線 + 中性子 joint | 6.66% | 合計 wR ≤ 8% |
| T4 | NAC+CaF2 TOF + 放射光 多相 | ~12.8% | Rw ≤ 15% |

**両エンジンが同じ格子・同じ相分率に落ちるか**が最重要の観測点。

## 既知の積み残し (T8 時点)

- **座標段 (`coords`) が実データで revert される**。TOPAS 経路は特殊位置の自由軸判定を持たず、
  Pnma の鏡映サイト (y=1/4 など) まで解放してしまう。GSAS 経路は `GSASIIspc.GetCSxinel` で
  自由軸を判定している。TOPAS では `structure` 側で特殊位置成分を参照式 (固定) にしておく契約に
  するのが筋。**現状はガードが効いて revert されるだけなので静かに壊れてはいない**が、
  座標が一切精密化されないため T12 の合格基準に届かない可能性がある。
- **精密化後セルの回収が未実装** (`_refined_cells` は参照セルを素通し)。`Out(Get(a), …)` を
  足して `refined_cells`/`cell_esd` を埋める必要がある。validity ゲートが実質空回りしている。
- `n_obs` が 0 のまま (BIC の dof に効く)。`Out(Get(Yobs_Count), …)` 相当で回収する。
