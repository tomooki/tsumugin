# M12 設計: Bruker TOPAS を第 2 の精密化バックエンドに

**作成日**: 2026-07-30 / ブランチ: `milestone/m12-topas-backend`
**関連**: 仕様 §P7 (バックエンド交換可能性) / §3.1 (GSAS-II 採用理由)
**実装計画**: `docs/tasks/m12-topas-backend/PLAN.md`

**【信頼性レベル凡例】**: 🔵 実測・仕様に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## 1. 背景 🔵

仕様 §P7 は `RefinementBackend` を交換可能な抽象として掲げるが、実データ精密化の実体は
**GSAS-II 一本**である。`autorietveld.engine.run_auto_rietveld` (3038 行中 885 行) が
段階解放の**方針**と GSAS-II の**呼び出し**を融合しているため、第 2 のエンジンを挿す余地が
関数の内側に無い。ローカルに TOPAS 7 が導入済みなので、これを第 2 バックエンドとして配線する。

**得られるもの**は 2 つ。(a) TOPAS 固有のモデル (Stephens 異方歪み・剛体・ペナルティ系) への道、
(b) **バックエンド間の独立確認** — 同じデータと同じ構造から 2 つの独立実装が同じ格子・同じ相分率へ
落ちれば大域最適の強い傍証になる。これは `multistart` の初期値摂動より強い証拠である
(実装のバグまで含めて独立だから)。

---

## 2. TOPAS 側の実測事実 (T0) 🔵

導入形態: `C:/TOPAS7`, DIFFRAC.TOPAS **V7.0 (7.0.1.7)**, CodeMeter ドングルライセンス。

| # | 事実 | 影響 |
|---|---|---|
| 1 | **自動化経路は `tc.exe` のバッチ実行のみ**。COM/OLE 登録なし・Python API なし (レジストリ調査済)。`ta.exe` は存在しない | driver は `subprocess` 一択 |
| 2 | `tc <INP のベース名(拡張子なし)> ["macro Name { value }"]` で実行し `<ベース名>.out` を書く | `.out` は**精密化後の INP そのもの** |
| 3 | **`tc.exe` は INP の構文エラーで異常終了しても終了コード 0 を返す** | ⚠ 終了コードで成否を判定してはならない。stdout の異常終了マーカー + 出力ファイル生成で判定する |
| 4 | **TOPAS は空間群生成で `sgcom6.exe` を子プロセス起動する**。これは PATH からしか引かれない | tc.exe を絶対パスで叩いても、PATH にインストールディレクトリが無いと `Cannot open file c:\topas7\sg\<sg>.sg` で異常終了する。driver は PATH に `topas_home()` を足す |
| 5 | `Sg/` は sgcom6 が**オンデマンド生成するキャッシュ**ディレクトリ (初期状態で 5 ファイル) | 空間群名の誤りは**loud に失敗**する (silent ではない) |
| 6 | `out "results.txt"` + `Out(Get(r_wp), "r_wp\t%.8f\n")` が最も決定論的な出力 | パーサの一次対象。`.out` の 1 行目にも `r_p/r_wp/r_exp/gof` が書き戻される |
| 7 | **`r_wp_dash` は背景差引き** (同一データで r_wp 20.3 に対し 26.6、別条件で r_wp 46.8 に対し 66.4) | GSAS の `rwp = 100·sqrt(chi2/Σw·yobs²)` と同スケールなのは **`r_wp`**。BIC 比較の一貫性はこちらで担保する |
| 8 | `Out` の**値側書式に改行を入れると esd が次行へ落ちる** | 1 レコード 1 行になるよう値側は改行なし、esd 側に改行を置く |
| 9 | マニュアル PDF はすべて暗号化されテキスト抽出不可 | 言語仕様の正は `topas.inc` (2483 行) と Tutorial INP 206 本。**想定と違う挙動は実行して確かめるしかない** |

### 2.1 パラメータ意味論 🔵

| 書き方 | 意味 |
|---|---|
| `9.18` | 固定 (無名) |
| `@ 9.18` | 精密化 (無名) |
| `lpa1 9.18` | 精密化 (名前付き — 名前は既定で精密化対象) |
| `!lpa1 9.18` | 固定 (名前付き; 参照先にできる) |
| `=lpa1;` | 他パラメータの参照 (式) |
| `@ 9.18 min 9 max 9.3` | 範囲付き |

### 2.2 GSAS-II との構造的な差 🔵

| 論点 | GSAS-II | TOPAS |
|---|---|---|
| 相とヒストグラムの関係 | 1 相を N ヒストグラムが**共有**するネイティブ機構 | 無い。`str` を xdd ごとに複製し、構造パラメータをトップレベル `prm` へ持ち上げて `=name;` で参照する (公式 Tutorial `neutron_Si_corefinement.inp` の idiom) |
| 格子の対称拘束 | `set_refinements({"Cell": True})` が空間群を見て**自動**で拘束 | **自動拘束しない**。`Cubic(cv)` マクロが `a cv b = Get(a); c = Get(a);` と明示展開する。拘束を張らないと立方晶の a/b/c が独立に動く |
| 解放の意味論 | `set_refinements` は**置換** | INP テキストの `@` の有無 (累積でも置換でもなく、毎回書き下す) |
| 温度因子 | Uiso | **B (`beq`) = 8π²·Uiso** |
| 失敗の伝わり方 | `G2Project.refine` が `Refine` の失敗戻り値を**捨てる** (無言 no-op) | 終了コード 0 のまま "Abnormal program termination" を stdout に出す |

最後の行が示すとおり、**両エンジンとも「失敗が呼び出し側に届かない」罠を持つ**。GSAS 側は
`_capture_refine_status` で解決済み。TOPAS 側は driver が stdout と出力ファイルで判定し、
`TopasRunError` → chi2=inf → revert の既存経路へ載せる (不変条件「バックエンドの失敗は
例外でなく chi2=inf に変換」)。

---

## 3. アーキテクチャ 🔵

```
  消費側 (insitu / refine_loop / mcp / search / multistart / workbench)
       │  runner: Callable[..., AutoRietveldResult]     ← 既存のシーム (無変更)
       │  backend: "gsasii" | "topas"                   ← 新設の分岐キー
       ├──────────────────────────┬─────────────────────────┐
       ▼                          ▼                         │
  autorietveld.engine        topas.engine                   │
  .run_auto_rietveld         .run_topas_rietveld            │
       │                          │                         │
       └──────────┬───────────────┘                         │
                  ▼                                         │
     autorietveld.stagepolicy  (T7 で新設・純関数)           │
       段の受理/revert 判定・StageResult 組立・ledger 追記   │
                  ▲                                         │
     autorietveld.{model,recipe,validity,bounds}  ← 既存の中立層を両者が共用
```

**選択の理由**: `engine.py` を `RietveldSession` Protocol へ全面分解する案は、実測で積み上げた
振舞い (無言失敗検出・`_apply_sample_geometry` の Type 整合・セル崩壊ガード) を全面リファクタする
ことになり回帰リスクが便益を上回る。抜き出すのは**判定ロジックだけ**にし、GSAS の `.gpx` 操作には
触らない。

### 3.1 モジュール構成

| モジュール | 役割 | GSAS/TOPAS 依存 |
|---|---|---|
| `topas.availability` | tc.exe 解決・`topas_home()` (sgcom6 対策)・`describe()` | なし (stdlib) |
| `topas.inp` | INP 文書ビルダ (`Param`/`TopasPhase`/`TopasHistogram`/`TopasDocument`) | なし (純関数) |
| `topas.structure` | CIF → `TopasPhase` (結晶系拘束・Uiso→beq) | なし (純関数) |
| `topas.instrument` | GSAS `.prm`/`.instprm` → TOPAS 装置記述 | なし (純関数) |
| `topas.flags` | `RefinementStage.flags` → TOPAS 解放指示 (`engine._apply_stage` の対) | なし (純関数) |
| `topas.driver` | tc.exe 起動 (PATH に home を足す・タイムアウト・失敗検出) | tc.exe |
| `topas.parse` | `.out` / `results.txt` パース | なし (純関数) |
| `topas.engine` | 段階解放 (`run_topas_rietveld`) | driver 経由 |
| `backends.topas` | `RefinementBackend` Protocol 実装 | driver 経由 |

**純関数層が大半**であることが重要で、`tc.exe` 無しの CI でも INP 生成まで全部テストできる。

---

## 4. 非目標 (明示的に見送る) 🔵

- **MEM (Dysnomia) 経路**: GSAS の `.gpx` ハンドルに依存するため TOPAS 非対応。
  `AutoRietveldResult.gpx_path` は TOPAS では空文字になる。
- **`cell_refine.py` の TOPAS 化**: 相同定の前処理であり精密化エンジンとは独立。GSAS 依存のまま共用。
- **TOPAS 固有機能** (剛体/z-matrix・`Auto_T` simulated annealing・Stephens 異方歪み・
  charge flipping): 本 PR では露出しない。`RefinementStage.flags` 語彙の拡張として M-later。

---

## 5. 検証方針 🔵

**ゴールデンテストは決定論を証明するだけで、TOPAS が受理することは証明しない。** そのため
純関数層の各タスクでも、生成物を**実 tc.exe に通す**確認を並行して行う (`@pytest.mark.topas`)。
実際、T3 では実 CIF (IT 番号なし) が設計の誤りを 1 件炙り出した。

最終検証は M7 の実データ T1–T4 を TOPAS で再現し、GSAS-II 値と突き合わせる
(`docs/benchmark/m12-topas/`)。**両エンジンが同じ格子・同じ相分率に落ちるか**が最重要の観測点で、
食い違えばどちらかにバグがある。
