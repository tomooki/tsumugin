# m5-nested-mem-oed 準備タスク（ユーザー作業）

> **仕様**: [requirements.md](requirements.md) / **生成日**: 2026-07-04

**【信頼性レベル凡例】**: 🔵 明確に必要 / 🟡 妥当な推測 / 🔴 予防的推測

M5 は 3 本柱 + 較正すべてに外部依存(dynesty/ultranest・Dysnomia・PyBOED)が絡むが、いずれも
**optional extra** とし、境界・入力生成・提案スキーマ・較正評価は外部依存なしで実装・テストする。
そのため**実装開始前に必須の準備は無い**。ただし M5 完了後の実地検証・contract test 確立のため、
外部依存の導入判断が推奨・確認事項として発生する。

## 必須（実装開始前に完了が必要）

なし — M5 も実装開始時点では外部サービス・認証情報・追加インフラを必要としない。
テストは合成データ + モック外部依存で完結し、実サンプラ(dynesty/ultranest)・実バイナリ(Dysnomia)・
PyBOED は `@pytest.mark.{nested,mem,oed}` 相当で分離し未導入環境では自動 skip する。
コア import(`import tsumugin`)は numpy のみで成功する。

## 推奨（実装中に用意できればOK）

- [ ] **nested サンプラ(dynesty / UltraNest)の導入と実裁定 smoke** 🟡 *FR-121/NFR-102/NFR-103*
  - `uv sync --extra nested` で dynesty(or ultranest)を導入すると、実 nested 裁定の smoke
    (TC-515-02)と logZ±誤差の再現性(TC-502-04)を検証できる。**M5 のコア実装・通常テストには不要**
    (未導入なら `NestedUnavailableError` へ縮退し境界テストで網羅)
  - どちらを既定サンプラにするか(REQ-303)は導入時に確定
  - 関連要件: REQ-004, REQ-006, REQ-009, REQ-303

- [ ] **Dysnomia バイナリの入手・導入** 🟡 *FR-602/NFR-106/§14 リスク表*
  - MEM v1 実装は Dysnomia 連携(外部バイナリラッパ)。実バイナリを導入すると MEM smoke(TC-515-04)と
    入出力ファイル契約の contract test(NFR-106)を確立できる。**配布・ライセンスは要確認**(PyPI 非公開・
    GSAS-II と同様のバイナリ導入形態)。未導入なら `MEMUnavailableError` へ縮退し境界/入力生成テストで網羅
  - 関連要件: REQ-019, REQ-020, REQ-406

- [ ] **MEM 検証用の joint 済み単相/主相支配データ(任意)** 🟡 *FR-605/§12-6*
  - 適用ガード推奨条件(joint 済み単相/主相支配)を満たす既知系(例: Na/K 伝導体)の joint データが
    あると、MEM 密度マップ・ボンド経路最小密度の実地検証(伝導パス評価)に使える。M5 テスト自体には不要
    (合成データ + モックで完結)
  - 関連要件: REQ-022, REQ-029, REQ-030

- [ ] **較正ベンチ用の正解ラベル付きデータセット(任意)** 🟡 *§12-5/§13 ベンチ公開*
  - reliability diagram / ECE の実評価(bic と nested 別系列)には正解相既知のベンチデータ群が要る。
    M5 は較正評価ユーティリティの実装 + 合成データでの決定論検証までがスコープ。実データでのベンチ**公開運用**は
    M-later(§13「ベンチ公開」の公開部)
  - 関連要件: REQ-016, REQ-017, REQ-106

## 確認事項（判断が必要）

- [ ] **nested/mem/oed を optional extra として追加する方針の可否** 🟡 *interview Q3/Q7/Q11/REQ-403*
  - M5 は `[project.optional-dependencies]` に `nested = ["dynesty>=2.1"]`(or ultranest)/ `mem = [...]`
    (Dysnomia ラッパの Python 依存)/ `oed = ["pyboed>=..."]` を追加する想定。未導入環境では該当実行 API のみ
    friendly error(`NestedUnavailableError` / `MEMUnavailableError` / `OEDUnavailableError`)へ縮退し、
    コア import は numpy のみで成功する(M4 の `mcp` extra 方式踏襲)
  - 関連要件: REQ-004, REQ-005, REQ-019, REQ-020, REQ-036, REQ-403

- [ ] **nested サンプラの既定(dynesty vs UltraNest)の確認** 🟡 *interview Q3/REQ-303*
  - どちらを既定 nested 実装にするか。両対応(設定で選択・REQ-303)にするか単一実装にするかを確認。
    live points 等のサンプラ設定既定も導入時に固定
  - 関連要件: REQ-004, REQ-303

- [ ] **nested 時間上限(既定 30 分)・ΔBIC 再裁定閾値(既定 10)の確認** 🟡 *NFR-103/FR-122/interview 残課題*
  - NFR-103 の 1 仮説 30 分上限、FR-122 の ΔBIC<10 再裁定閾値、FR-124 の温度較正パラメータ(既定 T=1.0)を
    M5 のテスト凍結値として採用してよいか。最終数値は較正ベンチ(§12-5)で較正
  - 関連要件: REQ-011, REQ-101, REQ-014, REQ-405

- [ ] **MEM-Rietveld 反復を既定オフのまま維持する方針の確認** 🔵 *FR-603/§15-3*
  - §15-3 で「既定オフを維持・条件付き auto は運用実績を見て将来判断」と確定済。M5 は既定オフ + 明示有効化
    (最大反復数・収束判定を設定)で実装し、条件付き auto 運転は M-later でよいか
  - 関連要件: REQ-024, REQ-302

- [ ] **Dysnomia の配布・ライセンス条件の確認** 🟡 *§14 リスク表/NFR-106*
  - Dysnomia の配布形態・ライセンスを確認し、バージョン固定 + contract test(NFR-106)の対象バージョンを
    決める。ライセンス上の制約があれば MEMBackend 抽象化により未導入環境で明示無効化(既に境界設計済)
  - 関連要件: REQ-019, REQ-406

---

## サマリー

| 優先度 | 件数 | 🔵 | 🟡 | 🔴 |
|--------|------|-----|-----|-----|
| 必須 | 0 | 0 | 0 | 0 |
| 推奨 | 4 | 0 | 4 | 0 |
| 確認事項 | 5 | 1 | 4 | 0 |

## 関連文書

- [requirements.md](requirements.md) / [interview-record.md](interview-record.md)
