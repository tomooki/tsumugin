# TASK-0014 PersistentSnapshotStore — Refactor フェーズ記録

**要件名**: m2-sequential / **タスクID**: TASK-0014 / **フェーズ**: Refactor
**対象**: `src/tsumugin/store/persistent.py`（`PersistentLedger` + `PersistentSnapshotStore`）
**実施日時**: 2026-07-03 / **判定**: ✅ 高品質（構造変更なし＝YAGNI 判断）

---

## 1. リファクタリング方針と結論

**結論: コード変更なし（no-change refactor）。** 現状のコードは可読性・命名・コメント・
ファイルサイズ（259 行 < 500 行）すべて適正水準にあり、Green フェーズ完了時点で
リファクタ観点の是正項目は存在しない。焦点であった **`PersistentLedger` と
`PersistentSnapshotStore` の JSONL 読み書き重複**は、共通化するとかえって
2 つの独立契約（整合性検証あり／なし）を結合させるため、YAGNI に基づき現状維持とする。

---

## 2. JSONL 読み書き重複の分析（本フェーズの主眼）

### 2.1 書き込み（append / save）— 完全一致する 2 行イディオム

```python
# PersistentLedger.append (L105-106)
with open(self._path, "a", encoding="utf-8") as f:
    f.write(json.dumps(entry.to_dict()) + "\n")

# PersistentSnapshotStore.save (L206-207)
with open(self._path, "a", encoding="utf-8") as f:
    f.write(json.dumps(row) + "\n")
```

- **重複度**: 2 行・2 箇所の同一イディオム（"a" モード追記 → JSON 1 行 + 改行）。
- **抽出案**: module-level `_append_jsonl_line(path, row: dict)` へ切り出し可能。
- **不抽出の判断（🟡）**: 追記専用（NFR-203）の不変条件は、既に両クラスとも
  `test_append_only_growth_prefix_unchanged` / `test_snapshot_append_only_growth_prefix_unchanged`
  で先頭バイト列不変を検証済みであり、ヘルパ抽出による保証強化は不要。抽出しても
  読者は `"a"` モードを確認するためにヘルパへジャンプする必要が生じ、削減行数（2 行）と
  間接化コストが相殺する。**費用対効果が中立のため現状維持**。

### 2.2 読み込み（_load_and_verify / _load）— 骨格は近いが誤り処理が意図的に異なる

| 観点 | PersistentLedger._load_and_verify | PersistentSnapshotStore._load |
|---|---|---|
| 骨格 | `read_text` → `splitlines` → 空行 skip → `json.loads` | 同左 |
| 不正 JSON 行 | `LedgerIntegrityError` に**包んで送出**（握り潰さない） | **包まない**（整合性検証はスコープ外） |
| ロード後検証 | `verify_entries()` で hash チェーン全件検証・破損は明示エラー | 検証なし（Snapshot に hash なし） |
| 行→オブジェクト | `LedgerEntry`（そのままの値で改竄検出のため再計算しない） | `Snapshot`（phases を `phase_from_dict` で型復元） |

- **共有できる真の重複**は「空行 skip の走査ループ骨格」のみ（4 行程度）。
- **不抽出の判断（🔵）**: ledger は「改竄を沈黙させない整合性台帳」、snapshot は
  「hash を持たない素の復元」という**意図的に別契約**（note.md §6「破損検出は本タスクの
  スコープ外／監査完全性は注入 ledger 側が担保」）。共通ジェネレータへ束ねると、
  片方だけの `LedgerIntegrityError` 包み・`verify_entries` を条件分岐で持ち込むことになり、
  2 契約の関心事を 1 箇所へ結合させてしまう。**分離した現状の方が単一責任に忠実**。

### 2.3 YAGNI 判断の根拠まとめ

1. 重複は浅い（書き込み 2 行・読み込み骨格 4 行）。
2. 読み込みの誤り処理が意図的に発散（整合性 vs 非整合性）しており、共通化は関心事の結合。
3. ファイルは 259 行で 500 行制限に余裕。分割の必要なし。
4. タスク指示自体が「YAGNI・変更不要判断可」を明示。
→ **共有ヘルパ抽出は将来 3 つ目の JSONL 永続クラス（例: Project Store）が現れた時点で
D-Q5 の serialization 分業と同様に検討すれば足りる。現時点では過剰設計。**

---

## 3. セキュリティレビュー

- **入力経路**: `path`（呼び出し側指定・ライブラリ内部の信頼境界内）、JSONL の各行
  （`json.loads` のみ・`eval` 等の動的評価なし）。インジェクション面なし。🔵
- **書き込み**: `"a"` モード追記のみ。既存バイト列を書き換える API（削除・上書き・truncate）は
  構造的に不在（`test_no_destructive_methods_and_same_surface_as_in_memory` で保証）。🔵
- **不正 JSON**: ledger 側は `LedgerIntegrityError` に包んで明示化（沈黙しない）。snapshot 側は
  整合性対象外のため素の `json.loads`（設計判断・note.md §6）。🔵
- **機密漏洩**: ログ・例外メッセージにパス名のみ含む（payload 内容は露出しない）。問題なし。🔵
- **結論**: 重大な脆弱性なし。

## 4. パフォーマンスレビュー

- **append / save**: O(1) の 1 行追記（メモリ内リスト append + 1 回の open/write）。🔵
- **_load / _load_and_verify**: 再オープン時に全行を O(n) 走査して復元（`verify_entries` も O(n)）。
  再オープンは本来的に全復元コストを伴うもので、想定 snapshot 件数（逐次解析の段階数）では
  問題にならない。ボトルネックなし。🔵
- **メモリ**: 全エントリ／全 snapshot を in-memory 保持（in-memory 版と同一形式）。想定規模で妥当。🔵
- **結論**: 重大な性能課題なし。

---

## 5. テスト実行結果

| 項目 | 結果 |
|---|---|
| 全体回帰 | `uv run pytest` → **280 passed, 3 skipped**（10.77s） |
| TASK-0014 単体 | `tests/test_persistent_store.py` → 全 green（PersistentLedger 14 + PersistentSnapshotStore 13 = 27 件） |
| 遅いテスト（2s 以上） | TASK-0014 スコープ内は**なし**（最遅 0.03s）。2.11s は `test_gsasii_backend`（本タスク対象外） |
| Lint | `uvx ruff check src tests` → **All checks passed!** |
| コード変更 | なし（構造・コメントとも Green フェーズから不変） |

## 6. コメント品質

Green フェーズ時点で【機能概要】【実装方針】【テスト対応】＋信頼性レベル（🔵🟡🔴）の
日本語 docstring が全メソッドに付与済み。追加・改善の必要なしと判断。

---

## 7. 品質判定

```
✅ 高品質:
- テスト結果: 280 passed / 3 skipped で全継続成功（Taskツール相当の uv run pytest 実行）
- セキュリティ: 重大な脆弱性なし
- パフォーマンス: 重大な性能課題なし
- リファクタ品質: YAGNI に基づく「変更不要」判断（重複は意図的分離の維持が最適）
- コード品質: 259 行 < 500 行・ruff clean・日本語コメント完備
- ドキュメント: 本ファイルで完成
```

**次のステップ**: `/tsumiki:tdd-verify-complete` で完全性検証を実行。
