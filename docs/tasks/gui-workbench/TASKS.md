# GUI Workbench タスク分割 (gui-workbench)

ブランチ: `milestone/gui-workbench`。実装プロセスは Fable 主導 TDD
(CLAUDE.md)。機械的・独立なタスクは Sonnet サブエージェントへ TDD ごと委任、
受け入れ判断は Fable。1 タスク green = 1 コミット。

| # | タスク | 担当 | 受け入れ基準 |
|---|---|---|---|
| G1 | docs 三点セット | Fable | 本 3 文書 |
| G2 | `tsumugin.workbench` バックエンド TDD (`session.py`/`seed.py`/`app.py`) | Sonnet | `tests/workbench/` green。モード切替が ledger 追記・engine.set_mode 経由。変更系は全て ledger 追記。削除ルートなし。fastapi 遅延 import (web extra 無しで import 可)。 |
| G3 | frontend scaffold (Vite+React+TS+vitest、tokens.css、i18n 辞書抽出、元素表、API client、state store、シェル) | Sonnet | `npm test` green・`npm run build` 成功。EN/JA キー集合一致テスト。元素 99 択テスト。モードトグルで右ペイン領域のみ切替わるテスト。 |
| G4a | FIT + PARAMETERS タブ | Sonnet | 忠実再現 + release チェック→カウント/ゲート連動テスト |
| G4b | HYPOTHESES + PHASE ID タブ | Sonnet | 行選択→DIFF 再指向テスト、chem guard 反転表示 |
| G4c | SEQUENCE + LEDGER タブ | Sonnet | アンカーチップ・actor 色分け・削除 UI 不在テスト |
| G4d | STRUCTURE タブ | Sonnet | インライン編集/pending counter/DISCARD disabled/対称固定セル disabled/APPLY→API 呼び出しテスト |
| G5 | 右ペイン MANUAL (recipe gating + review queue) / AUTO (transcript + 承認カード + composer) | Sonnet | ゲート live 反映、承認両経路 ledger 表示、escalation 反転チップ |
| G6 | 統合: FastAPI 静的配信 + 実 API 配線 + ブラウザスモーク | Fable+Sonnet | dev サーバで全タブ・両モード・EN/JA を目視スモーク (browser pane) |
| G7 | Tauri scaffold + debug ビルド | Sonnet | `cargo build` 成功、dev 構成文書 |
| G8 | `/code-review` 修正ループ → PR | Fable | 新規指摘ゼロ。マージはユーザー判断 |

依存: G2‖G3 並行可 → G4a-d は G3 後に並行 → G5 は G3 後 (G4 と並行可) →
G6 は G2+G4+G5 後 → G7 は G6 後 → G8 最後。

ガード系テスト (ゲート・DISCARD・キー集合一致・削除 UI 不在) は**変異させて fail する
ことを実証してから受け入れる** (CLAUDE.md: 落ちないガードは無いより悪い)。
