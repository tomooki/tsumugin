# プロファイル物理性ガード 受け入れ基準

**作成日**: 2026-07-09
**関連要件定義**: [requirements.md](requirements.md)
**関連ユーザストーリー**: [user-stories.md](user-stories.md)

**【信頼性レベル凡例】**: 🔵 確実 / 🟡 妥当な推測 / 🔴 資料にない推測

> **⚠ 改訂 (GSAS getFWHM 精読 + T1 実測)**: 下記 TC のうち「CW 係数の符号違反 → hard NG」を想定した
> ものは、**soft 警告 (passed=True) に改訂**した。GSAS はガウス分散を `max(0.001,·)` でクランプし、
> 実 T1 良好フィットが U=-1.96,Y=-3.13 に収束するため。**hard (revert) は真の発散のみ**: 解放済値の
> NaN/inf・TOF σ²<0・TOF alpha/beta-0≤0。実テストは `tests/autorietveld/test_profile_physicality*.py`
> が最新 (GSAS 忠実) の正典。CW 系 TC は「passed=True + warnings に記録」へ読み替える。

---

## REQ-001: プロファイル値抽出と hist_profile 充填 🔵

### Given / When / Then
- **Given**: GSAS `Instrument Parameters` を持つ精密化済ヒストグラム群
- **When**: engine が結果を構築する
- **Then**: `AutoRietveldResult.hist_profile` が各 hist の `{key: value}` で充填される

### テストケース
- [ ] **TC-001-01**: モック g2hist (`[0]={'U':[2.0,3.1,True],...}`) から `_extract_profile` が
  `({'U':3.1,...},)` を返す 🔵 *純関数テスト*
- [ ] **TC-001-02**: 抽出結果が解放フラグも保持し、未解放/解放を区別できる 🔵
- [ ] **TC-001-E01**: `Instrument Parameters` 欠落 hist → 空 dict に縮退し例外を出さない 🔵 *EDGE-001*

---

## REQ-002: CW ガウス幅 H_G² 正値性 🔵

### Given / When / Then
- **Given**: `U,V,W` と 2θ レンジ
- **When**: `check_profile_physicality` を呼ぶ
- **Then**: レンジ全域で `H_G²>0` なら OK、どこかで ≤0 なら NG

### テストケース
- [ ] **TC-002-01**: `U=2,V=-2,W=5` (既定) → レンジ [10°,120°] で正 → OK 🔵 *interop 既定値は物理的*
- [ ] **TC-002-E01**: `W` を大きな負に → 低角で `H_G²<0` → NG 🔵
- [ ] **TC-002-E02**: `U` 負で高角の頂点/端点が負 → NG 🔵
- [ ] **TC-002-B01**: 頂点 `tanθ*=-V/2U` がレンジ内で最小値 ≤0 → NG (頂点評価が効く) 🔵 *EDGE-102*
- [ ] **TC-002-B02**: `U=0` (線形退化) → 端点のみ評価で判定 🔵 *EDGE-103*

---

## REQ-003: CW ローレンツ X,Y 非負 🔵

### テストケース
- [ ] **TC-003-01**: `X=1.0, Y=0.5` (解放済) → OK 🔵
- [ ] **TC-003-E01**: `X=-0.5` (解放済) → NG 🔵
- [ ] **TC-003-E02**: `Y=-0.3` (解放済) → NG 🔵
- [ ] **TC-003-B01**: `X=-1e-6` (tol 内, 解放済) → OK (数値ノイズ許容) 🔵 *tol*

---

## REQ-004: SH/L 下限 0 🔵

### テストケース
- [ ] **TC-004-01**: `SH/L=0.002` (解放済) → OK 🔵
- [ ] **TC-004-E01**: `SH/L=-0.01` (解放済) → NG 🔵

---

## REQ-005: TOF ガウス分散 σ² 非負 🔵

### テストケース
- [ ] **TC-005-01**: `sig-0=100, sig-1=5, sig-2=0` → d レンジ全域で σ²≥0 → OK 🔵
- [ ] **TC-005-E01**: `sig-2` 大きな負で高 d の σ²<0 → NG 🔵
- [ ] **TC-005-B01**: d レンジ端点で σ²=0 近傍 → tol 内で OK 🔵

---

## REQ-006: TOF alpha/beta strict-pos 🔵

### テストケース
- [ ] **TC-006-01**: `alpha=0.5, beta-0=0.02` (解放済) → OK 🔵
- [ ] **TC-006-E01**: `alpha=0` (解放済) → NG (発散) 🔵
- [ ] **TC-006-E02**: `beta-0=-0.01` (解放済) → NG 🔵

---

## REQ-101 / REQ-201: engine revert ガード配線 🔵

### Given / When / Then
- **Given**: `profile` を解放する段階が非物理な U,V,W を生む runner (モック)
- **When**: `run_auto_rietveld` 相当の段階ループを回す
- **Then**: 当該段階が revert され、直前段階の rwp/gof に巻き戻る

### テストケース
- [ ] **TC-101-01**: `_profiles_physical` が False を返す状態で段階が revert される 🔵 *engine 統合 (numpy モック可能な純関数側で検証)*
- [ ] **TC-101-02**: `_profiles_physical` が True なら従来どおり Rwp 判定のみ (非回帰) 🔵

---

## REQ-102: 未解放パラメータで誤 revert しない 🔵

### テストケース
- [ ] **TC-102-01**: `X=-0.5` だが **refined=False** → 個別符号違反は無視 → OK 🔵
- [ ] **TC-102-02**: 同じ `X=-0.5` が **refined=True** → NG (対比) 🔵

---

## REQ-103: soft 上限は警告 (revert しない) 🔵

### テストケース
- [ ] **TC-103-01**: `SH/L=0.5` (hard は満たすが soft 上限 0.1 超) → `passed=True` かつ warnings に記録 🔵
- [ ] **TC-103-02**: warnings があっても revert 判定 (hard) は False を返さない 🔵

---

## 非機能・制約テスト

### REQ-401 / REQ-402: 純関数・決定論 🔵
- [ ] **TC-NFR-01**: `check_profile_physicality` は numpy のみ import で動作 (GSAS 非依存) 🔵
- [ ] **TC-NFR-02**: 同一入力で2回呼び同一結果 (ビット同一) 🔵

### REQ-404: 非回帰 🔵
- [ ] **TC-NFR-03**: T1〜T4 の `@pytest.mark.gsas` テストが green を維持 🔵 *実 GSAS 環境*

---

## テストケースサマリー

| カテゴリ | 正常系 | 異常系 | 境界値 | 合計 |
|---------|--------|--------|--------|------|
| 抽出 (REQ-001) | 2 | 1 | 0 | 3 |
| CW 幅 (REQ-002/003/004) | 3 | 6 | 3 | 12 |
| TOF (REQ-005/006) | 2 | 3 | 1 | 6 |
| ガード配線 (REQ-101/102/103) | 4 | 2 | 0 | 6 |
| 非機能 | 3 | 0 | 0 | 3 |
| **合計** | 14 | 12 | 4 | 30 |

### 信頼性レベル分布
- 🔵 青信号: 30件 (100%)

**品質評価**: 高品質
