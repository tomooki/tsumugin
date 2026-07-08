# refine-loop-diagnostics アーキテクチャ設計

**作成日**: 2026-07-09
**関連要件定義**: [requirements.md](../../spec/refine-loop-diagnostics/requirements.md)
**ヒアリング記録**: [design-interview.md](design-interview.md)
**設計入力(正)**: [GAP_ANALYSIS.md](GAP_ANALYSIS.md) / [serious-refinement-flow.md](../../reference/serious-refinement-flow.md)

**【信頼性レベル凡例】**: 🔵 要件/設計文書/既存実装参照 / 🟡 妥当な推測 / 🔴 未参照推測

---

## システム概要 🔵

**信頼性**: 🔵 *requirements.md 概要より*

`tsumugin.refine_loop` の**第2層b(診断オートトライ)を拡張**する。核心の accept/revert エンジン
(`orchestrator._accept` = Rwp 改善 ∧ validity 維持) は不変で、追加は (1)残差を「見える化」する
前提工事、(2)診断シグナル→トライ候補の規則、(3)少数の新 SafeAction、(4)上位のモデル比較
オーケストレータ。GSAS-II は runner 内遅延 import、コアは numpy のみ、決定論 (NFR-102)。

## アーキテクチャパターン 🔵

**信頼性**: 🔵 *CLAUDE.md・既存 refine_loop 実装より*

- **パターン**: 決定論オーケストレータ + 純データ変換 Action + 注入可能境界 (Protocol)。
  観測(diagnose)→判断(policy)→適用(action.apply)→評価(_accept)→revert のループ。
- **選択理由**: 既存 M8 実装 (action/diagnostics/policy/orchestrator) がこのパターンで、本要件は
  その診断語彙を増やす純増分。frozen dataclass + Protocol 境界を踏襲し決定論・テスト容易性を保つ。

## レイヤーとコンポーネント (3層マッピング) 🔵

**信頼性**: 🔵 *GAP_ANALYSIS.md 表A/B/C より*

| 層 | 役割 | モジュール | 本要件での変更 |
|---|---|---|---|
| 第1層 Default | 普遍段階列 | `autorietveld.build_recipe` | 変更なし |
| 第2層a 条件分岐 | 装置/試料分岐 | `build_recipe` アダプタ | 変更なし |
| **第2層b 診断オートトライ** | 残差→候補→try/revert | `refine_loop.diagnostics` / **`diagnose_residual`(新)** / `action` / `policy` / `orchestrator` | **拡張** |
| 第3層 Judgment | モデル選択等 | `action`(ModelAction) / **`model_compare`(新)** / `compare` | **追加** |

### 変更/新規モジュール 🔵

**信頼性**: 🔵 *requirements REQ-001〜005 より*

1. **`autorietveld/model.py`** (拡張): `AutoRietveldResult` に内省フィールド追加 (REQ-001)。
   非破壊・末尾追加・既定値で後方互換 (EDGE-001)。
2. **`refine_loop/diagnose_residual.py`** (新): 残差配列 + 内省フィールド → `ResidualFeatures`
   (拡張シグナル) を算出する既定 diagnose (REQ-002)。`orchestrator` の `Diagnose` 契約を満たし、
   `_default_diagnose` を置換する既定実装。
3. **`refine_loop/diagnostics.py`** (拡張): `ResidualFeatures` に新シグナル追加 + `propose_next_actions`
   に規則追加。候補は**別々の `ReleaseParams`** として列挙 (REQ-003/101〜104)。
4. **`refine_loop/action.py`** (拡張): 新 SafeAction `RestrictUiso` / `SetAbsorption` (REQ-004)。
5. **`refine_loop/model_compare.py`** (新): 変種を精密化し `compare.compare_models` で BIC+妥当性
   裁定 + ledger 追記する薄いオーケストレータ (REQ-005/202)。

## 主要な設計決定 🔵

**信頼性**: 🔵 *GAP_ANALYSIS.md・requirements より*

- **DD-1 汎用性優先**: 大半の新診断は既存 `ReleaseParams(label, flags)` + engine flag で表現し、
  新 Action は「限定/値固定」の 2 つ (`RestrictUiso`/`SetAbsorption`) のみ (NFR-101, 表C)。
- **DD-2 別々の候補**: 非対称/位置は 1 提案に束ねず、シフト(Zero)と非対称(SH/L・alpha/beta)を
  独立提案とする。policy が個別に試し `_accept` が採否 → 「結論を焼き込まない」(REQ-405)。
- **DD-3 内省フィールドは非破壊拡張**: `AutoRietveldResult` に Mapping/tuple の既定空フィールドを
  末尾追加。旧 result・スタブでも欠落を許容し diagnose は縮退 (EDGE-001)。
- **DD-4 経験則は prior**: 「TOF は alpha が効く」等は提案の `priority` を偏らせるだけの非拘束
  ヒント。候補自体は常に列挙し `_accept` が検証 (REQ-301)。
- **DD-5 データリミットは第3層維持**: `SetLimits` は ModelAction のまま。ループ内オートトライに
  しない (REQ-404, ヒアリング P3)。
- **DD-6 モデル比較は上位**: `model_compare` は単一モデル調律ループ (`run_refinement_loop`) の
  外側で、変種ごとに runner を回し `compare_models` に委譲 (REQ-005, ヒアリング P4)。

## 内省フィールド設計 (REQ-001) 🔵

**信頼性**: 🔵 *diagnose が必要とするシグナル源より*

`AutoRietveldResult` に追加 (すべて既定空、非破壊):

| フィールド | 型 | 用途 (診断) |
|---|---|---|
| `atom_uiso` | `Mapping[str, Mapping[str, float]]` (phase→label→Uiso) | Uiso 発散/負値 → RestrictUiso (REQ-105) |
| `atom_occupancy` | `Mapping[str, Mapping[str, float]]` | 占有率 [0,1] 逸脱 → 制約/モデル (REQ-106 隣接) |
| `hist_absorption` | `tuple[float, ...]` (per hist) | 吸収の現値 → SetAbsorption 判断 (REQ-106) |
| `hist_profile` | `tuple[Mapping[str, float], ...]` | プロファイル現値 (Zero/alpha/X/Y 等) |
| `peak_width_ratio` | `tuple[float, ...]` (obs/calc FWHM, per hist) | 幅ずれ → U,V,W/X,Y/size (REQ-103) |
| `asymmetry_metric` | `tuple[float, ...]` (残差の左右非対称度) | 非対称 → Zero/SH·L/alpha (REQ-101) |
| `intensity_bias_metric` | `tuple[float, ...]` (系統 obs>calc 度) | 選択配向 (REQ-102) |
| `bg_extrema` | `tuple[int, ...]` (背景の極値数) | 背景 overfit → 減項 (REQ-104) |

runner (GSAS) がこれらを gpx から算出して詰める。スタブ/旧構築は空 → diagnose は該当シグナルを
立てない (EDGE-001)。

## ディレクトリ構造 🔵

**信頼性**: 🔵 *既存 src レイアウトより*

```
src/tsumugin/
├── autorietveld/
│   └── model.py            # AutoRietveldResult に内省フィールド追加
└── refine_loop/
    ├── action.py           # + RestrictUiso, SetAbsorption
    ├── diagnostics.py       # + ResidualFeatures 新シグナル, propose 規則
    ├── diagnose_residual.py # 新: 残差解析の既定 diagnose
    ├── model_compare.py     # 新: BIC モデル比較オーケストレータ
    ├── orchestrator.py      # 既定 diagnose を diagnose_residual に差し替え
    └── policy.py            # 変更なし (SafeAction 増加を自動吸収)
tests/refine_loop/           # 各実装ファイルと 1:1 の決定論テスト
```

## 非機能要件の実現 🔵

**信頼性**: 🔵 *CLAUDE.md・NFR より*

- **決定論 (NFR-102/REQ-402)**: 提案は safe 優先→優先度降順→型名昇順で安定ソート (既存踏襲)。
  新シグナルの算出は numpy 決定論。乱数なし。
- **numpy コア + GSAS 遅延 (REQ-401)**: diagnose_residual/diagnostics/action/model_compare は numpy
  のみ。GSAS は runner 内。内省フィールドの算出は runner (GSAS 側) が担い、コアは値を消費するだけ。
- **台帳 (NFR-102/105)**: `model_compare` は各変種評価を ledger に追記、`verify()` True を保つ。
- **テスト容易性 (NFR-001)**: runner/diagnose 注入で GSAS 非依存に `-m "not gsas"` green。

## 技術的制約 🔵

**信頼性**: 🔵 *CLAUDE.md・requirements 制約要件より*

- frozen dataclass + `dataclasses.replace`。境界は `typing.Protocol`。ruff line-length 100。
- P2 非破壊: 適用は純変換 (`apply`) + revert。ModelAction は自律適用しない (REQ-403)。
- 材料固有結論の焼き込み禁止 (REQ-405)。

## 関連文書

- **データフロー**: [dataflow.md](dataflow.md)
- **型定義(Python)**: [interfaces.py](interfaces.py)
- **要件定義**: [requirements.md](../../spec/refine-loop-diagnostics/requirements.md)

## 信頼性レベルサマリー

- 🔵 青信号: 全項目 (要件 + 既存実装 + GAP_ANALYSIS に追跡可能)
- 🟡/🔴: 0

**品質評価**: 高品質
