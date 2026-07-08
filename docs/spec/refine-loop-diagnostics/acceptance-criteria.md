# refine-loop-diagnostics 受け入れ基準

**作成日**: 2026-07-09
**関連要件定義**: [requirements.md](requirements.md)
**関連ユーザストーリー**: [user-stories.md](user-stories.md)

**【信頼性レベル凡例】**: 🔵 設計文書/実装/ヒアリング参照 / 🟡 妥当な推測 / 🔴 未参照推測

すべて numpy コア + runner/diagnose スタブ注入で決定論テスト可能 (`-m "not gsas"`)。

---

## REQ-001: AutoRietveldResult 内省フィールド 🔵

### Given
- 精密化済み `AutoRietveldResult`(GSAS runner or スタブ)。

### When
- 新フィールド(per-atom Uiso/占有率、per-hist 吸収/プロファイル、obs/calc 幅比/非対称/PO 指標)を参照する。

### Then
- 各フィールドが取得でき、既存フィールドは非破壊。旧構築(新フィールド未指定)でも既定値で生成できる。

### テストケース
- [ ] **TC-001-01**: 新フィールドを与えた result が値を保持する 🔵
- [ ] **TC-001-02**: 新フィールド省略で既定値(空/None)を持ち後方互換 🔵 *EDGE-001*
- [ ] **TC-001-B01**: frozen dataclass で `with_updates`/`dataclasses.replace` が新フィールドを非破壊更新 🔵

---

## REQ-002: 残差解析 diagnose 🔵

### Given
- `residual_two_theta/intensity/sigma` + 内省フィールドを持つ result。

### When
- `diagnose_residual(result, inp)` を呼ぶ。

### Then
- `ResidualFeatures`(拡張シグナル)列を返す。決定論(同一入力→ビット同一)。

### テストケース
- [ ] **TC-002-01**: 幅ずれパターンで fwhm 系シグナルが立つ 🔵
- [ ] **TC-002-02**: 非対称パターンで asymmetry/position シグナルが立つ 🔵
- [ ] **TC-002-03**: 系統 obs>calc で intensity_bias(PO)シグナルが立つ 🔵
- [ ] **TC-002-04**: 背景 wiggle 過剰(極値過多)で overfit シグナルが立つ 🔵
- [ ] **TC-002-E01**: 残差空/全ノイズでシグナルを立てない(false positive なし) 🔵 *EDGE-102*
- [ ] **TC-002-B01**: 内省フィールド欠落の旧 result で例外なく縮退(見えないシグナルは出さない) 🔵 *EDGE-001*

---

## REQ-101/003: 非対称/位置を別々の候補として提案 🔵

### Given
- 非対称/位置シグナルが立った `ResidualFeatures`。

### When
- `propose_next_actions` を呼ぶ。

### Then
- シフト(Zero: `profile_lorentzian`/`tof_profile` の Zero)と非対称(X線 `profile_asymmetry`=SH/L /
  TOF `tof_profile`=alpha,beta)が **別々の `ReleaseParams` 提案**として列挙される。両者は独立に
  policy が試せる(片方採用・片方 revert が成立する)。

### テストケース
- [ ] **TC-101-01**: 非対称シグナルで「Zero 候補」と「非対称候補」の2提案が出る 🔵
- [ ] **TC-101-02**: 両提案とも `is_safe`(SafeAction=ReleaseParams) 🔵
- [ ] **TC-101-03**: 決定論順序(型名/優先度で安定ソート) 🔵 *REQ-402*
- [ ] **TC-101-04**: X線ヒストは SH/L、TOF ヒストは alpha/beta が候補になる(放射源で分岐) 🔵

---

## REQ-102/103/104: PO・幅・背景減項の提案 🔵

### テストケース
- [ ] **TC-102-01**: 系統 obs>calc で `preferred_orientation` 提案 🔵
- [ ] **TC-103-01**: 幅ずれで U,V,W / X,Y / size が**別々の候補**として出る 🔵
- [ ] **TC-104-01**: 背景 overfit で背景**減項**の `AdjustBackground` が出る(現行の増項と両立) 🔵
- [ ] **TC-104-02**: 背景残差(不足)では従来どおり増項提案 🔵 *非回帰*

---

## REQ-004/105/106: RestrictUiso / SetAbsorption 🔵

### Given
- Uiso 発散/負、または吸収不確実のシグナル。

### When
- `propose_next_actions` → policy → `action.apply(inp)`。

### Then
- `RestrictUiso(labels)` は `PhaseSpec.free_uiso_labels` を設定した入力を返す(純変換)。
- `SetAbsorption(hist_id, value, refine)` は当該 `HistogramSpec.absorption`(+必要なら解放段)を設定。
- 両者 SafeAction で revert ガード下に自律適用可。

### テストケース
- [ ] **TC-004-01**: `RestrictUiso(("Cu","Ow")).apply(inp)` が free_uiso_labels を設定 🔵
- [ ] **TC-004-02**: `SetAbsorption(0, 0.031, refine=False).apply(inp)` が hist0 の absorption=0.031 🔵
- [ ] **TC-106-01**: 吸収不確実で free/物理/0 の3提案が列挙される 🔵
- [ ] **TC-004-E01**: 範囲外 hist_id で IndexError 🔵
- [ ] **TC-105-01**: Uiso 発散シグナルで RestrictUiso 提案(重原子/水に限定) 🔵

---

## REQ-005/202: モデル比較オーケストレータ 🔵

### Given
- 構造モデル変種列(例 model5/model6)+ 観測ヒストグラム。runner スタブ注入。

### When
- モデル比較オーケストレータを実行する。

### Then
- 各変種を精密化 → `compare.compare_models` で BIC+妥当性序列化 → **物理妥当なうち最小 BIC** を
  best に、妥当皆無なら全体最小へフォールバック(`best_is_valid=False`)。

### テストケース
- [ ] **TC-005-01**: 妥当な変種のうち最小 BIC を best に選ぶ 🔵 *compare 準拠*
- [ ] **TC-005-02**: 低 BIC でも非妥当な変種は best にしない 🔵 *REQ-202*
- [ ] **TC-005-B01**: 全変種非妥当で best_is_valid=False + 全体最小 BIC 🔵 *EDGE-101*
- [ ] **TC-005-02b**: ledger 追記(verify() True) 🔵 *NFR-102*

---

## REQ-201: 受理基準(不変)/ REQ-402 決定論 🔵

### テストケース
- [ ] **TC-201-01**: 提案適用が Rwp 改善 ∧ validity 維持で採用、悪化で revert(据え置き) 🔵 *_accept 不変*
- [ ] **TC-402-01**: 同一入力・種でループがビット同一(提案順序安定) 🔵 *NFR-102*
- [ ] **TC-403-01**: ModelAction(SetLimits 含む)は自律適用されず open_proposals へ 🔵 *REQ-403/404*

---

## 非機能要件テスト

### NFR-001/102: 決定論・台帳 🔵
- [ ] **TC-NFR-001-01**: 全新規テストが `-m "not gsas"` で GSAS 非依存に green 🔵
- [ ] **TC-NFR-102-01**: ledger `verify()` が常に True 🔵

---

## テストケースサマリー

| カテゴリ | 正常系 | 異常系 | 境界値 | 合計 |
|---------|--------|--------|--------|------|
| 機能要件 | 17 | 2 | 4 | 23 |
| 非機能要件 | 2 | 0 | 0 | 2 |
| 合計 | 19 | 2 | 4 | 25 |

### 信頼性レベル分布
- 🔵 青信号: 25件 (100%)
- 🟡/🔴: 0件

**品質評価**: 高品質(全基準 🔵、設計入力 + ヒアリングに追跡可能)

## テスト実施計画
- Phase 1 (P0): REQ-001, REQ-002 — 内省フィールド + 残差解析 diagnose
- Phase 2 (P1): REQ-101〜104, REQ-003 — 診断規則(既存 ReleaseParams)
- Phase 3 (P2): REQ-004, REQ-105, REQ-106 — RestrictUiso/SetAbsorption
- Phase 4 (P4): REQ-005, REQ-202 — モデル比較オーケストレータ
