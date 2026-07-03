# Verification Report: m0-refinement-core

> 2026-07-03 / TDD 自律実装 (同日追補: GSAS-II 導入 + GSASIIBackend 実体化)

## サマリ

M0 (PoC) スコープの 10 タスク + 追補タスク 011 (GSAS-II) を TDD で実装完了。全タスク `status: done`。

- **テスト**: 70 passed, 1 skipped (skip は「GSAS-II 未導入時に例外」経路 — 導入済みのため正しく skip)
- **GSAS-II contract tests**: 7 本すべて実 GSAS-II (2.0, win_64_p3.12_n2.2 バイナリ) で green
- **カバレッジ**: 95% (764 stmts / 38 miss)
- **Lint**: `ruff` クリーン (line-length 100)
- **再現性**: 全エンジン・パイプラインで同一入力 → ビット同一出力を検証 (NFR-102)

## タスク別テスト内訳

| Task | モジュール | テスト | 状態 |
|------|-----------|-------|------|
| 001 | model | test_model.py (7) | ✅ |
| 002 | backends.base | test_backend_interface.py (5) | ✅ |
| 003 | backends.simulated | test_simulated_backend.py (7) | ✅ |
| 004 | backends.gsasii | test_gsasii_backend.py (2 + 1 skip) | ✅ |
| 005 | store.ledger | test_ledger.py (7) | ✅ |
| 006 | store.snapshot | test_snapshot.py (7) | ✅ |
| 007 | refinement.guardrails | test_guardrails.py (8) | ✅ |
| 008 | refinement.staged | test_staged_engine.py (6) | ✅ |
| 009 | evidence | test_evidence.py (9) | ✅ |
| 010 | pipeline | test_pipeline.py (6) | ✅ |
| 011 | backends.gsasii (実体化) | test_gsasii_backend.py (7 + 1 skip) | ✅ |

## 仕様適合の要点

- **P2 / NFR-101 / NFR-105**: Ledger/SnapshotStore に破壊的メソッドを実装しないことをテストで否定確認。
  ハッシュチェーン検証 (`verify()`) と非破壊 revert を担保。
- **P7**: `RefinementBackend` / `EvidenceBackend` を `Protocol` で定義。SimulatedBackend と
  GSASIIBackend(薄いラッパ) を交換可能に。
- **FR-200/202**: 段階テンプレート駆動。悪化段の固定戻しを検証。
- **FR-210/212**: 5 種の発散検知、自動ロールバック、3 回失敗でエスカレーション (処理はブロックしない)。
- **FR-121/124**: BIC(既定)/AIC、softmax+温度較正確率、ΔBIC<10 の僅差競合フラグ。

## GSAS-II 導入 (追補)

- 方式: ソースツリー (`C:\Users\tomoo\G2`, git clone --depth 1) + venv の `gsas2-source.pth` +
  buildtools リリースのビルド済みバイナリ (`~/.GSASII/GSASII-bin/win_64_p3.12_n2.2`)。
  Windows で公式が pip ビルドを非推奨とする gfortran/gcc 問題を回避。
- `GSASIIBackend`: refine (HAP Scale / Cell) + simulate (noise-free Ycalc) を実装。
  精密化失敗は chi2=inf に変換しガードレールに処理を委譲。
- 実バックエンドで発覚したガードの欠陥を修正: chi2≈0 (ノイズフリー) での比率爆発誤検知
  → `GuardConfig.chi2_worsen_floor_per_obs` (絶対増分下限) を追加。**契約テストが M0 の
  ガード設計の実データ耐性バグを 1 件検出した**ことになる (contract test の狙いどおり)。
- バイナリは numpy 2.2 ビルド (venv は 2.5、ABI 前方互換で動作確認済み)。

## 設計上の注記 / 実装時に確定した事項

- SimulatedBackend の格子-ピーク結合は **直方近似** (1/d² = h²/a²+k²/b²+l²/c²) を採用。
  当初の「有効セル長=体積^(1/3)」案は a/b/c が体積に縮退し個別識別できないため変更。
- SimulatedBackend の LM は narrow-Gaussian のため捕捉範囲が狭い (Δa ≲ 0.05)。
  M0 のガードレール/戦略検証には十分だが、実データ相当の大域探索は M1 のマルチスタート (FR-230) で担保予定。
- 段階の受理条件は「ガード違反なし & Rwp 非悪化」。FR-115 の R 改善閾値による枝打ち切りは M1 の
  木探索側で本格導入する (M0 は全段走査)。

## M0 スコープ外 (次段)

多仮説木探索(FR-110)、シーケンシャル/operando(FR-300/310)、中性子 joint(FR-240)、
MEM(FR-600)、nested sampling、Web/REST/MCP、GSASIIBackend.refine 本体 (M1)。
