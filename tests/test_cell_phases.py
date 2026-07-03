"""TASK-0030 operando/cell_phases — セル固定相プリセット (FR-312) の Red フェーズテスト。

対象 API (docs/design/m3-operando/interfaces.py L232-244):
- ``FixedPhaseSpec`` (frozen dataclass, フィールド ``phase: PhaseInstance`` / ``label: str``)
- ``CELL_PHASE_PRESETS: Mapping[str, FixedPhaseSpec]`` (キー "Be" / "Al" / "graphite")
- ``fixed_free_suffixes(spec) -> tuple[str, ...]`` (常に ``("scale",)``)

正典契約: AC 原文 TC-203-01 は "PhaseCandidate" と記すが、本タスクは interfaces.py /
TASK-0030.md の ``FixedPhaseSpec`` を正典としてテストする。
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, param_name
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance

# 【対象未実装 API】: cell_phases モジュールはまだ存在しないため、この import で ImportError
#                     となり全テストが失敗する (Red フェーズの期待失敗)。
from tsumugin.operando.cell_phases import (
    CELL_PHASE_PRESETS,
    FixedPhaseSpec,
    fixed_free_suffixes,
)

# 文献格子定数 (直方近似) — 実装 docstring と一致させる期待値。
# Be(hcp): a=2.2858, b=a·√3, c=3.5843 / Al(fcc): a=b=c=4.0495 /
# graphite(hex): a=2.464, b=a·√3, c=6.711 (単位 Å)。
_BE_A = 2.2858
_BE_C = 3.5843
_AL_A = 4.0495
_GRAPHITE_A = 2.464
_GRAPHITE_C = 6.711

_GRID = np.arange(15.0, 80.0, 0.02)


# ---------------------------------------------------------------------------
# 1. 正常系テストケース
# ---------------------------------------------------------------------------


def test_cell_phase_presets_has_three_fixed_phase_specs():
    # 【テスト目的】: CELL_PHASE_PRESETS が Be/Al/graphite の 3 キーを持ち各値が FixedPhaseSpec (TC-203-01)
    # 【テスト内容】: プリセットのキー集合と各値の型を検証
    # 【期待される動作】: 3 プリセットが FixedPhaseSpec インスタンスとして取り出せる
    # 🔵 信頼性レベル: TC-203-01 / REQ-009 / interfaces.py L236-244 に直接依拠

    # 【テストデータ準備】: プリセット定数 (引数なし) を対象にする
    # 【初期条件設定】: モジュールロード時に確定した不変定数を参照
    presets = CELL_PHASE_PRESETS

    # 【結果検証】: キー集合が過不足なく 3 種であること
    # 【期待値確認】: interfaces.py L244「"Be" | "Al" | "graphite"」に対応
    assert set(presets) == {"Be", "Al", "graphite"}  # 【確認内容】: キー集合が 3 種で過不足なし 🔵

    # 【結果検証】: 各値が FixedPhaseSpec 型であること
    for key in ("Be", "Al", "graphite"):
        assert isinstance(presets[key], FixedPhaseSpec)  # 【確認内容】: 値が FixedPhaseSpec 型 🔵


def test_cell_phase_presets_lattice_matches_literature():
    # 【テスト目的】: 各プリセット格子定数が文献値 (直方近似後) と一致 (完了条件3)
    # 【テスト内容】: Be/Al/graphite の a/b/c が docstring 記載の文献値どおりか検証
    # 【期待される動作】: ハードコードされた格子値が文献値と 0.001 Å 精度で一致
    # 🟡 信頼性レベル: TASK-0030.md 完了条件・タスク指示の格子値に依拠 (格子値そのものは 🟡)

    # 【テストデータ準備】: 各プリセットの phase.lattice を取り出す
    be = CELL_PHASE_PRESETS["Be"].phase.lattice
    al = CELL_PHASE_PRESETS["Al"].phase.lattice
    graphite = CELL_PHASE_PRESETS["graphite"].phase.lattice

    # 【結果検証】: Be の a/c が文献値と一致 (b は直方近似で TC-BV01 が別途検証)
    assert be.a == pytest.approx(_BE_A)  # 【確認内容】: Be a=2.2858 Å 🟡
    assert be.c == pytest.approx(_BE_C)  # 【確認内容】: Be c=3.5843 Å 🟡

    # 【結果検証】: Al は立方晶なので a=b=c=4.0495
    assert al.a == pytest.approx(_AL_A)  # 【確認内容】: Al a=4.0495 Å 🟡
    assert al.b == pytest.approx(_AL_A)  # 【確認内容】: Al b=4.0495 Å 🟡
    assert al.c == pytest.approx(_AL_A)  # 【確認内容】: Al c=4.0495 Å 🟡

    # 【結果検証】: graphite の a/c が文献値と一致
    assert graphite.a == pytest.approx(_GRAPHITE_A)  # 【確認内容】: graphite a=2.464 Å 🟡
    assert graphite.c == pytest.approx(_GRAPHITE_C)  # 【確認内容】: graphite c=6.711 Å 🟡


def test_fixed_free_suffixes_returns_scale_only():
    # 【テスト目的】: 固定相の解放パラメータが scale のみ (構造固定) であることを確認 (TC-203-02)
    # 【テスト内容】: 全プリセットの spec に対し fixed_free_suffixes が ("scale",) を返す
    # 【期待される動作】: lattice/occupancy suffix を含まず scale のみが解放対象
    # 🟡 信頼性レベル: TC-203-02 / REQ-009 / interfaces.py L238 に依拠

    # 【テストデータ準備】: Be/Al/graphite の 3 プリセットを走査対象にする (構造固定は材料非依存のため)
    for key in ("Be", "Al", "graphite"):
        spec = CELL_PHASE_PRESETS[key]

        # 【実際の処理実行】: 固定相の解放 suffix 展開ヘルパを呼ぶ
        # 【処理内容】: 構造固定・scale のみ解放の契約を単一の真実源から取得
        suffixes = fixed_free_suffixes(spec)

        # 【結果検証】: 戻り値が ("scale",) であること
        # 【期待値確認】: 構造 (lattice/occ) を解放しない REQ-009 字義
        assert suffixes == ("scale",)  # 【確認内容】: scale のみ解放 (lattice/occ を含まない) 🟡


def test_fixed_phase_spec_frozen_and_structural_equality():
    # 【テスト目的】: FixedPhaseSpec を直接生成し等価比較 (==) が成立する (§4 データモデル)
    # 【テスト内容】: 同一 phase・同一 label の 2 インスタンスが構造的に等価
    # 【期待される動作】: 同値 spec は == で真
    # 🔵 信頼性レベル: interfaces.py L236-241 / CLAUDE.md (frozen dataclass 規約) に依拠

    # 【テストデータ準備】: プリセット定数を介さない純データモデル契約を検証
    # 【初期条件設定】: 同一 phase・同一 label で 2 つの FixedPhaseSpec を生成
    phase = PhaseInstance("Al", LatticeParams(_AL_A, _AL_A, _AL_A))
    spec_a = FixedPhaseSpec(phase=phase, label="Al collector")
    spec_b = FixedPhaseSpec(phase=phase, label="Al collector")

    # 【結果検証】: 構造的等価が成立すること
    # 【期待値確認】: frozen dataclass は値ベースの == を持つ
    assert spec_a == spec_b  # 【確認内容】: 同値 spec が == で等価 🔵


def test_cell_phase_presets_have_valid_phase_and_label():
    # 【テスト目的】: 各プリセットの phase が PhaseInstance、label が非空 str (TC-203-01)
    # 【テスト内容】: FixedPhaseSpec の各フィールドが実体を持つことを確認
    # 【期待される動作】: 固定相の相インスタンスとラベルが正しく詰まっている
    # 🔵 信頼性レベル: TC-203-01 / interfaces.py L240-241 に直接依拠

    for key in ("Be", "Al", "graphite"):
        spec = CELL_PHASE_PRESETS[key]

        # 【結果検証】: phase が PhaseInstance であること
        assert isinstance(spec.phase, PhaseInstance)  # 【確認内容】: phase が PhaseInstance 型 🔵

        # 【結果検証】: label が非空 str であること
        assert isinstance(spec.label, str)  # 【確認内容】: label が str 型 🔵
        assert spec.label != ""  # 【確認内容】: label が空でない 🔵

        # 【結果検証】: 相参照が設定されていること
        assert spec.phase.phase_ref != ""  # 【確認内容】: phase_ref が非空 🔵


def test_active_phase_refines_with_fixed_cell_phase():
    # 【テスト目的】: 固定相込みの合成データで活物質相の scale が真値へ収束 (TC-203-03)
    # 【テスト内容】: 固定相 Al (scale のみ解放) + 活物質相を合成し scale を精密化
    # 【期待される動作】: セル材料ピーク重畳下でも活物質相 scale が真値へ
    # 🔵 信頼性レベル: TC-203-03 / REQ-009 / test_simulated_backend の scale 収束に依拠

    # 【テストデータ準備】: 固定相 (真 scale 2.0) と活物質相 (真 scale 3.0) の合成パターン
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _GRID
    spec_al = CELL_PHASE_PRESETS["Al"]
    fixed_truth = spec_al.phase.with_updates(scale=2.0)
    active_truth = PhaseInstance("LFP", LatticeParams(5.0, 5.0, 5.0), scale=3.0)
    y = backend.simulate((fixed_truth, active_truth), tt)

    # 【初期条件設定】: scale をずらした初期相。固定相 scale + 活物質 scale のみ解放
    start_fixed = spec_al.phase.with_updates(scale=1.0)
    start_active = PhaseInstance("LFP", LatticeParams(5.0, 5.0, 5.0), scale=1.0)
    free = {param_name(0, s) for s in fixed_free_suffixes(spec_al)} | {param_name(1, "scale")}
    model = RefinementModel(
        phases=(start_fixed, start_active),
        free_params=frozenset(free),
        two_theta=tt,
        intensity=y,
    )

    # 【実際の処理実行】: scale のみ解放で精密化
    result = backend.refine(model)

    # 【結果検証】: 収束し、活物質相 scale が真値 3.0 へ
    assert result.converged  # 【確認内容】: 精密化が収束 🔵
    assert result.phases[1].scale == pytest.approx(3.0, rel=0.05)  # 【確認内容】: 活物質相同定 🔵
    assert result.phases[0].scale > 0  # 【確認内容】: 固定相 scale も正値へ追随 🔵


def test_cell_phase_presets_deterministic():
    # 【テスト目的】: CELL_PHASE_PRESETS を 2 回参照して同一プリセット (NFR-102 / REQ-402)
    # 【テスト内容】: プリセットの 2 回参照が等価
    # 【期待される動作】: 実行のたびに揺れない不変定数
    # 🔵 信頼性レベル: NFR-102 / REQ-402 / CLAUDE.md 不変条件に直接依拠

    # 【結果検証】: 2 回参照した Be プリセットが等価
    assert CELL_PHASE_PRESETS["Be"] == CELL_PHASE_PRESETS["Be"]  # 【確認内容】: 決定論的に等価 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース
# ---------------------------------------------------------------------------


def test_fixed_phase_spec_is_frozen():
    # 【テスト目的】: FixedPhaseSpec が frozen でフィールド再代入不可 (§4 不変性)
    # 【テスト内容】: frozen dataclass のフィールドへ再代入を試みる
    # 【期待される動作】: FrozenInstanceError が送出される
    # 🔵 信頼性レベル: interfaces.py L236 (frozen=True) / CLAUDE.md 非破壊規約に直接依拠

    # 【テストデータ準備】: プリセット定数を共有オブジェクトとして取り出す
    spec = CELL_PHASE_PRESETS["Be"]

    # 【結果検証】: フィールド再代入で FrozenInstanceError
    # 【期待値確認】: プリセット定数が実行時に破壊されない
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.label = "x"  # type: ignore[misc]  # 【確認内容】: frozen による再代入拒否 🔵


def test_cell_phase_presets_unknown_key_raises_keyerror():
    # 【テスト目的】: 未定義キー参照で KeyError (Mapping 契約)
    # 【テスト内容】: CELL_PHASE_PRESETS に存在しないキー "Cu" を参照
    # 【期待される動作】: 標準 Mapping の未定義キー挙動で KeyError
    # 🟡 信頼性レベル: interfaces.py L244 (Mapping 型) からの標準挙動 (妥当推測)

    # 【結果検証】: 未定義キーで KeyError
    # 【期待値確認】: 未定義プリセットを捏造せず例外で停止
    with pytest.raises(KeyError):
        _ = CELL_PHASE_PRESETS["Cu"]  # 【確認内容】: 未定義キーの明示失敗 🟡


# ---------------------------------------------------------------------------
# 3. 境界値テストケース
# ---------------------------------------------------------------------------


def test_hexagonal_presets_orthohexagonal_b_equals_a_sqrt3():
    # 【テスト目的】: 六方晶プリセットの直方近似 b == a·√3 (直方近似の核心 / 完了条件3)
    # 【テスト内容】: Be/graphite の b 軸が a·√3 で決まることを検証
    # 【期待される動作】: b が a と縮退せず √3 倍で分離される
    # 🟡 信頼性レベル: 要件定義 §2.2 (orthohexagonal b=a·√3) / SimulatedBackend 直方近似に依拠

    # 【テストデータ準備】: 六方晶 2 プリセットの格子を取り出す
    for key in ("Be", "graphite"):
        lattice = CELL_PHASE_PRESETS[key].phase.lattice

        # 【結果検証】: b == a·√3 (orthohexagonal 近似)
        # 【期待値確認】: a=b 縮退による b 方向反射消失を回避する近似式
        assert lattice.b == pytest.approx(
            lattice.a * math.sqrt(3.0)
        )  # 【確認内容】: b が a·√3 に一致 🟡


def test_al_preset_is_cubic_isotropic():
    # 【テスト目的】: 立方晶 Al は a==b==c (直方近似の歪みなし境界 / 完了条件3)
    # 【テスト内容】: Al の三軸が完全一致し角が既定 90° であることを検証
    # 【期待される動作】: 六方近似のような軸変換を Al には適用しない
    # 🟡 信頼性レベル: 要件定義 §2.2 (Al fcc a=b=c) / 文献値に依拠 (格子値は 🟡)

    # 【テストデータ準備】: 集電体 Al の格子を取り出す
    lattice = CELL_PHASE_PRESETS["Al"].phase.lattice

    # 【結果検証】: 三軸が完全一致 (異方近似を誤適用しない)
    assert lattice.a == pytest.approx(_AL_A)  # 【確認内容】: a=4.0495 Å 🟡
    assert lattice.b == pytest.approx(_AL_A)  # 【確認内容】: b=4.0495 Å (a と等長) 🟡
    assert lattice.c == pytest.approx(_AL_A)  # 【確認内容】: c=4.0495 Å (a と等長) 🟡

    # 【結果検証】: 角は既定 90° (直方系)
    assert lattice.alpha == pytest.approx(90.0)  # 【確認内容】: α=90° 🟡
    assert lattice.beta == pytest.approx(90.0)  # 【確認内容】: β=90° 🟡
    assert lattice.gamma == pytest.approx(90.0)  # 【確認内容】: γ=90° 🟡


def test_fixed_phase_lattice_unchanged_after_scale_only_refine():
    # 【テスト目的】: 固定相は scale のみ解放 — 精密化後も格子が不変 (TC-203-02)
    # 【テスト内容】: graphite 固定相を scale のみ解放して refine し lattice 不変を確認
    # 【期待される動作】: 解放していない lattice が 1 つも変化しない
    # 🟡 信頼性レベル: TC-203-02 / REQ-009 / SimulatedBackend _recognized 挙動に依拠

    # 【テストデータ準備】: 真 scale 1.5 の固定相 graphite で合成データを作る
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _GRID
    spec_graphite = CELL_PHASE_PRESETS["graphite"]
    fixed = spec_graphite.phase.with_updates(scale=1.5)
    y = backend.simulate((fixed,), tt)

    # 【初期条件設定】: scale をずらした初期相。scale のみ解放 (lattice 解放 0 個)
    start = fixed.with_updates(scale=0.5)
    free = {param_name(0, s) for s in fixed_free_suffixes(spec_graphite)}
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset(free),
        two_theta=tt,
        intensity=y,
    )

    # 【実際の処理実行】: scale のみ解放で精密化
    result = backend.refine(model)

    # 【結果検証】: lattice が精密化前後で不変
    assert result.phases[0].lattice.a == pytest.approx(fixed.lattice.a)  # 【確認内容】: a 不変 🟡
    assert result.phases[0].lattice.b == pytest.approx(fixed.lattice.b)  # 【確認内容】: b 不変 🟡
    assert result.phases[0].lattice.c == pytest.approx(fixed.lattice.c)  # 【確認内容】: c 不変 🟡

    # 【結果検証】: scale は真値 1.5 へ収束
    assert result.phases[0].scale == pytest.approx(1.5, rel=0.05)  # 【確認内容】: scale 収束 🟡
