# V2c C2: GSAS-II フル同梱可否調査

**日付**: 2026-07-26
**関連**: `docs/design/adr/0001-gui-frontend-stack.md` (ADR-0001 §1, sidecar 方式)、
`desktop/README.md` §本番 sidecar 梱包 (M-later) — GSAS-II 同梱は本調査まで未着手のまま保留されていた。
**性質**: 調査のみ。実装・commit なし。検証は使い捨てスクリプトで `scratchpad/` 上のみ実施 (git 未追跡)。

## 結論 (先出し)

**Tier1 (コア+web のみ同梱、GSAS はローカル導入前提 + 自動検出 UI) を推奨。**
Tier2 (フル同梱) は技術的には可能で追加サイズも小さい (実測+25〜30MB 程度) が、
(1) バイナリ解決がランタイムの `glob`+ctypes 拡張 import に依存し PyInstaller の静的解析が
到達できないため `--add-data` による手動配線 + numpy ABI バージョン厳密一致が必須、
(2) 「遅延 import」で GSAS 非依存を保っている tsumugin コアも PyInstaller の静的解析には
無力で、GSASIIscriptable に到達する経路がある限り GSAS-II ソースツリー全体 (wx 専用 GUI
モジュール込み) が解析対象になる、(3) `--all-extras` 環境でビルドすると M5/M6 拡張
(pymatgen/mp-api/dynesty 等) 経由で botocore 等の巨大な無関係依存が静的解析に引き込まれる
実害を実測確認、という3点で「サイズは小さいが構成の脆さとビルド手順の複雑さ」が支配的コストであり、
現時点でこれを払う便益 (GSAS 未導入ユーザーの initial setup 省略) に見合わない。

## 1. 現行導入形態

| 項目 | 実測 |
|---|---|
| GSAS-II ソースツリー `C:\Users\tomoo\G2` | **28M** (`.git` 込み) / **23M** (`.git` 除く) |
| バイナリ `~/.GSASII/GSASII-bin/win_64_p3.12_n2.2` | **6.4M** |
| `~/.GSASII` 全体 (`config.ini` 含む) | 6.4M |

- **import 経路**: `.venv\Lib\site-packages\gsas2-source.pth` の中身は `C:\Users\tomoo\G2`
  の1行のみ (sys.path に追加)。`GSASII/` パッケージがその直下にあり
  `from GSASII import GSASIIscriptable` が解決する。
- **バイナリ解決機構**: `GSASIIpath.SetBinaryPath()` (`GSASIIpath.py:1354-1394`) がまず
  `from GSASII import pypowder` (co-located ビルド) を試み、失敗すると
  `pathHacking._path_discovery()` (`pathHacking.py:11-90`) にフォールバックする。
  探索先は `sys.path[0]` → `pathHacking.py` の所在ディレクトリ (`GSASII/`) → その親 →
  `~/.GSASII` の4箇所 (`pathHacking.py:24-27`)、各所で `bin`/`bindist`/`GSASII-bin`
  サブディレクトリと `AllBinaries/<prefix>*`/`GSASII-bin/<prefix>*` を `glob` する
  (`pathHacking.py:35-58`)。`prefix` は `win_64_p3.12` のような
  `platform+pythonバージョン` 文字列 (`GetBinaryPrefix`, `GSASIIpath.py:149-164`) で、
  末尾の `n2.2` は numpy バージョンから決まる (見つかった候補を numpy バージョンで
  ソートし現在の numpy 以下の最大版を選ぶ、`pathHacking.py:44-57`)。
  一致する `.pyd` を実際に `import` して spacegroup 演算まで試走し (`pathhack_TestSPG`)、
  成功して初めて `sys.path` に挿入する。**見つからなくても例外にはならず**
  `BinaryPathFailed=True` の warning に縮退する (`pathHacking.py:70-77`) —
  Tier1 の自動検出 UI (§5) はこの成否をそのまま使える。
- **設定ファイル**: `~/.GSASII/config.ini` (`GSASIIpath.py:1401,1459` ほか) —
  常にユーザーホーム配下、バンドルディレクトリの外。PyInstaller onedir/onefile
  いずれでも無条件に書き込み可能 (バンドル内への書き込みではない)。

## 2. ライセンス

`C:\Users\tomoo\G2\LICENSE` (Argonne National Laboratory, "GSAS-II OPEN SOURCE LICENSE"):
BSD 系オープンソースライセンス。**再配布可**。条件:
著作権表示の保持・変更箇所の明示・派生物への謝辞
("This product includes software produced by UChicago Argonne, LLC…") 記載・
バイナリ配布時のソース同梱、の4点 (LICENSE:7-30)。商用含め royalty-free。

同梱ソフトウェアの個別ライセンス注記あり (LICENSE:32-43):
NIST_profile/NIST\*LATTICE/DIFFaX は著作権フリーまたは著者許諾。
**`GSASII/G2shapes.py` のみ GNU GPLv3+** (`G2shapes.py:1180` に
`'License: GNU GPLv3'` の埋め込み文字列を確認)。SAXS 形状解析用の周辺モジュールで
tsumugin の Rietveld 経路 (GSASIIscriptable 経由) からは通常到達しないが、
フル同梱時はツリーに含まれるため注意 (対応: 除外するか、LICENSE 同梱で足りる
「集合著作物」として扱うか要検討。除外の方が単純)。
**判断: ライセンス上の障害は無い** (Tier1/Tier2 いずれも可)。

## 3. PyInstaller との相性 — 実証結果

`scratchpad/pyi_entry.py` (`from tsumugin.workbench.__main__ import main`) を
エントリポイントに `uv run --with pyinstaller pyinstaller --onedir` で3パターン検証
(コードは書き捨て、git 未追跡)。

**検証A (素朴に `__main__.py` を直接指定)**: ビルドは成功するが実行時に
`ImportError: attempted relative import with no known parent package`。
PyInstaller がエントリスクリプトをパッケージ外の孤立モジュールとして解析するため
`from .app import serve` を解決できず、`app.py` 以降 (fastapi 等) が
**解析されずに素通りする** — ビルドが「エラー無く成功」しても実行時に壊れる典型例。
パッケージ修飾したラッパースクリプト経由でエントリポイントを作る必要がある
(Tauri sidecar 化の際、`desktop/README.md:75-76` の想定通りエントリポイントの
差し替えが要る根拠になる)。

**検証B (パッケージ修飾ラッパー、`--all-extras` 環境そのまま)**: 解析は正しく
`tsumugin.workbench.__main__` → `.app.serve()` 内の遅延 `import fastapi` まで到達し、
さらに **GSASIIscriptable にも到達**して GSAS-II ソースツリー全域を解析対象にした
(`warn-*.txt` に `GSASII.GSASIIctrlGUI`/`GSASIIdataGUI`/`GSASIIphsGUI`/`GSASIIrmcGUI`
等 wx 専用 GUI モジュール群が "missing module wx" 経由で55件言及、xref に
`GSASIIscriptable` 55ヒット)。同時に `pymatgen`/`mp_api`/`dynesty`/`pandas`/`plotly`/
`botocore`/`joblib` 等も解析対象に入り、ビルドは Windows の `MAX_PATH` 制限
(botocore のデータファイルパスが深すぎる) で `COLLECT` 段階で失敗。
途中まで生成された `_internal/botocore` だけで **15M** (未完走なのでさらに増える)。

これが示す2つの構造的事実:
1. **「遅延 import」(呼び出し時 import) は PyInstaller の静的解析を回避しない。**
   PyInstaller の `modulegraph` は AST を静的にたどり、`try/except`・関数内・条件分岐の
   `import` 文もすべて到達可能性判定の対象にする。tsumugin コアが
   「numpy-only import + GSAS/pymatgen は遅延 import」で保っている軽量性
   (CLAUDE.md 記載の設計原則) は **実行時のオンデマンド性**であって
   **ビルド時の同梱範囲を絞る効果は無い**。エントリポイントの静的到達グラフに
   `autorietveld`/`reference.mp` 等が含まれる限り、それらが参照する重い依存
   (GSASIIscriptable 経由の GSAS-II 全体、mp 経由の pymatgen/mp-api) を
   PyInstaller は「見つけて」バンドルしようとする。
2. **`--all-extras` venv でビルドすると無関係な巨大依存 (botocore 等) を巻き込む。**
   Tier1/Tier2 いずれのビルドも、`web`(+`gsas`) 相当のみを sync した専用ビルド用
   venv から行う必要がある。現行 venv 運用の注意書き (CLAUDE.md: 「プレーン `uv sync`
   は gsas が、`--extra gsas` 単独は nested/mp/mcp 等が外れる」) がそのまま
   配布ビルドにも波及する。

**検証C (重量級 extras を `--exclude-module` で明示除外、GSAS も除外)**: ビルド成功。
`dist/t3` **92M** (numpy+scipy+fastapi+uvicorn+pydantic+pycifrw 込み。scipy/numpy が
大半を占める)。生成 exe を `--port` 指定で実起動し `uvicorn` 起動ログ・
`GET /` 200・`GET /api/session` 404 (正しいエンドポイントは `/api/state` 等、
ルーティング自体は生存) を確認 — **onedir バンドルの core+web 部分は問題なく動く**。

**GSAS-II 固有の PyInstaller リスク (コードから確認、実ビルドは未実施)**:
- バイナリ (`.pyd`/`.dll`) は `pathHacking._path_discovery` が実行時に `glob` で
  発見して `sys.path.insert` → `import` する方式 (§1)。これは**静的 import ではない**
  ため PyInstaller の `modulegraph` は自動収集できない。Tier2 では
  `GSASII-bin/win_64_p3.12_n2.2/` 一式を **`--add-data` で明示的にデータとして**
  探索対象ディレクトリ (バンドル後の `GSASII/` パッケージ隣接、または `~/.GSASII`)
  に配置する必要がある。
- 探索ディレクトリ名の `n2.2` は numpy バージョン埋め込みのため、
  **PyInstaller がバンドルする numpy のバージョンと GSASII-bin のビルド時 numpy
  バージョンが厳密一致しないと発見に失敗する** (`GetBinaryPrefix`, `pathHacking.py:44-57`)。
  失敗しても例外にはならず機能不全 (chi2=inf 相当) に縮退するため実害の発覚が遅れやすい
  — Tier2 を選ぶ場合はこの一致を CI で固定検証する仕組みが要る。
- `GSASIIElem.py` は `inputs/Xsect.dat` (`inputs/` ディレクトリ計 591K) を実行時に
  `open()` で読む (`GSASIIElem.py` 内で `inputs`/`Xsect.dat` 参照を確認) — Python
  ソースではないため PyInstaller が自動収集せず、これも `--add-data` が要る。
- `icons/`(365K)・`help/`(5.1M) は GUI 専用で GSASIIscriptable 経路では不要 —
  同梱すると無駄な +5.5M。
- `imports/__init__.py` (`imports/__init__.py:1-40`) はプラグイン読み込みが
  **静的 `from . import G2xxx`** のみで書かれており (メンテナのコメント「ここに追加したら
  meson.build にも」)、この部分は PyInstaller フレンドリー。動的発見
  (`glob`+`importlib.util.spec_from_file_location`, `GSASIIfiles.py:614-625`) は
  **ユーザー拡張用の `~/.GSASII/imports` のみ**を対象にしており、バンドル内部の
  標準リーダーには影響しない (空なら何も起きないだけ)。
- `config.ini` はバンドル外 (§1) なので書き込みは問題なし。

## 4. 判断: Tier1 推奨

| | Tier1 (コア+web のみ) | Tier2 (フル同梱) |
|---|---|---|
| 実測/見積サイズ | **92M** (実測, core+web, GSAS/重量extras除外) | Tier1 + GSAS-II ソース(23M) + バイナリ(6.4M) + inputs(0.6M) ≒ **+25〜30M** (icons/help 除外時) |
| ライセンス | 問題なし | 問題なし (G2shapes.py の GPLv3 混入のみ要検討) |
| ビルドの脆さ | 低 (fastapi/numpy/scipy の静的解析範囲は狭く実証済み) | 高 — numpy ABI バージョン厳密一致・`--add-data` 手動配線・wx-GUI 分岐を誤って巻き込まない除外設定・専用ビルド venv 管理、いずれも継続メンテナンスコスト |
| 得られる便益 | GSAS 未導入ユーザーは初回セットアップ (`C:\Users\tomoo\G2` 相当の導入) が必要 | ゼロセットアップで即動作 |

**サイズだけ見ればTier2は十分小さい (+30M弱)** が、GSAS-II のバイナリ解決が
「静的解析不可能なランタイム glob」である以上、Tier2 は毎リリースで
「numpy バージョンを固定し、それに合った `GSASII-bin` を選び、`--add-data` の
パスを spec ファイルに保守する」という**手作業の同期義務**を負う。この失敗モードは
静かな機能低下 (§3 のバージョン不一致) であり、GUI からは §5 の検出 UI が
「GSAS 無し」と正しく報告してしまう (誤動作ではなく機能欠落として顕在化するので
実害は限定的だが、原因究明にビルド設定の突き合わせが要る)。
現段階 (v2c, デスクトップ配布はまだ M-later) でこのコストを払う必然性は無く、
**Tier1 + ローカル導入ガイド + 自動検出 UI** を推奨する。Tier2 は
「配布実績が要求する (例: 非開発者ユーザーへの一般配布が実際の目標になった)」
タイミングで、専用ビルド venv・CI でのバイナリ/numpy 版一致検証込みで再検討する。

## 5. Tier1 での GSAS 検出 UX 提案

sidecar (`tsumugin.workbench`) 起動時に、`GSASIIpath.SetBinaryPath()` 相当の
呼び出し結果 (成功/失敗は例外を投げず bool で返る、§1・§3) を1回だけ試行し、
`WorkbenchSession` の `state` に読み取り専用フィールドとして出す案:

```
state.gsas_available: bool        # SetBinaryPath 成否 (BinaryPathFailed の否定)
state.gsas_detail: str | None     # 失敗時のみ: 検索したディレクトリ一覧などの要約
```

- 判定は起動時に一度だけ (バイナリ探索はファイルI/Oを伴うため毎リクエストは避ける)。
- `gsas_available=False` でもサーバは起動し API は動く (read-only 閲覧・
  非 GSAS 機能は引き続き使える) — GUI 側は「実精密化には GSAS-II 導入が必要です」
  という非致命的なバナー表示に留める (契約上は enum 追加ではなく既存
  `state` dict へのフィールド追加なので後方互換; **契約変更そのものは本調査の
  スコープ外の提案であり、実装時に `api-contract.md` 側の合意を別途取ること**)。
- 検出ロジックは `GSASIIpath.SetBinaryPath(showConfigMsg=False)` を呼んだ後
  `GSASIIpath.BinaryPathFailed` を読むだけで良く、新規の探索コードを
  tsumugin 側に重複実装する必要はない (既存の遅延 import 境界
  `tsumugin.backends.gsas` 等から `GSASIIpath` を触れる箇所に配線する)。

## 付記: 検証コード

`scratchpad/pyi_entry.py` (PyInstaller エントリラッパー) のみ使い捨てとして残置
(git 管理外、`dist`/`build` 生成物は調査後に削除済み)。
