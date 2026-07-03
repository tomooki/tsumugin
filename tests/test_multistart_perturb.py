"""TASK-0027 multistart/perturb (決定論摂動列) の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/multistart/perturb.py``: ``PerturbationSpec`` (frozen dataclass) /
  ``MultistartConfig`` (frozen dataclass) / ``generate_starts(phases, *, config)``
  (start index の純関数で摂動 phases 列を返す。i=0 は無摂動、乱数不使用の決定論列)。
- ``src/tsumugin/multistart/__init__.py``: 上記 3 シンボルの re-export。

摂動の意味論 (requirements §2 / interfaces.py L124-169 / architecture.md D1 / AC TC-201-01・07 で固定):
- 格子 (a/b/c): 基準の ``[1-lattice_frac, 1+lattice_frac]`` 倍の等間隔グリッド。角度 (alpha/beta/gamma) は非摂動。
- scale: ``scale * 10^offset`` の対数一様グリッド (``|log10(scale_pert/scale_base)| <= scale_log_range``)。
- 占有率: 固定 LHS 表由来の ``occupancy_delta`` 幅オフセットを加算し **[0,1] にクリップ**。空 dict はスキップ。
- i=0 は無摂動 (基準と同値)。``n_starts=1`` は基準 1 組のみ (N=1 縮退、0 除算回避)。
- 同一 ``(phases, config)`` で 2 回呼ぶとビット同一 (乱数不使用)。入力 ``phases`` は非破壊 (P2 / REQ-404)。

書式は ``tests/test_lifecycle.py`` (TASK-0016) を範とし、決定論・整数は ``==``、浮動小数の域検証は
``math.log10`` / 許容幅、frozen 検証は ``pytest.raises(FrozenInstanceError)`` を用いる。テストケース定義
(multistart-perturb 18 件: 正常系 10 / 異常系 2 / 境界値 6) に対応する。

対象モジュール未実装のため import が collection 時に失敗し、本ファイルの全テストがエラー(=失敗)になる想定 (Red)。
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.multistart import MultistartConfig, PerturbationSpec, generate_starts

# ---------------------------------------------------------------------------
# テストヘルパ (テストケース定義 §テストヘルパに準拠)
# ---------------------------------------------------------------------------


def _phase(ref="A", a=5.0, b=5.0, c=5.0, scale=1.0, occ=None):
    """基準 PhaseInstance を組む。occ は {site: 占有率}。"""
    return PhaseInstance(
        phase_ref=ref,
        lattice=LatticeParams(a=a, b=b, c=c),
        scale=scale,
        occupancies=(occ or {}),
    )


def _differs(pert: PhaseInstance, base: PhaseInstance) -> bool:
    """摂動相 pert が基準相 base と (いずれかのパラメータで) 異なるか。"""
    return (
        pert.lattice.a != base.lattice.a
        or pert.lattice.b != base.lattice.b
        or pert.lattice.c != base.lattice.c
        or pert.scale != base.scale
        or dict(pert.occupancies) != dict(base.occupancies)
    )


def _key(phase: PhaseInstance):
    """start を一意化するキー (格子/scale/占有率の組)。"""
    return (
        phase.lattice.a,
        phase.lattice.b,
        phase.lattice.c,
        phase.scale,
        tuple(sorted(phase.occupancies.items())),
    )


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_generate_starts_returns_n_starts_preserving_phase_count():
    # 【テスト目的】: generate_starts が n_starts 組を返し各要素が入力と同じ相数を持つことを確認 (T-N01)
    # 【テスト内容】: 単相・既定 N=8 で戻り値の外側長 / 内側長を検証
    # 【期待される動作】: 外側 len==n_starts、内側 len==len(phases)
    # 🔵 信頼性レベル: requirements 2.3 / interfaces.py L165-169 / architecture.md D1 に依拠

    # 【テストデータ準備】: 相数保存を確認するため単相 (len==1) を用意
    # 【初期条件設定】: 既定 N=8 (FR-231) の基本ケース
    phases = (_phase(),)

    # 【実際の処理実行】: generate_starts で N=8 の摂動列を生成
    starts = generate_starts(phases, config=MultistartConfig(n_starts=8))

    # 【結果検証】: 本数と各 start の相数保存を確認
    assert len(starts) == 8  # 【確認内容】: start 本数が n_starts と一致 🔵
    for i in range(8):
        assert len(starts[i]) == 1  # 【確認内容】: 各 start が入力と同数(1)の相を保持 🔵


def test_perturbation_sequence_is_deterministic_bit_identical():
    # 【テスト目的】: 同一入力で 2 回生成した摂動列がビット同一であることを確認 (T-N02 / TC-201-01)
    # 【テスト内容】: 非対称格子 + 占有率ありの相で 3 摂動全てが効く代表入力を 2 回生成
    # 【期待される動作】: starts_a == starts_b (frozen dataclass の構造的等価、全数値 ==)
    # 🔵 信頼性レベル: acceptance-criteria TC-201-01 / REQ-402 / NFR-102 に依拠

    # 【テストデータ準備】: 格子/scale/占有率いずれも摂動対象になる非対称・占有率ありの相
    # 【初期条件設定】: 既定 N=8 で 2 回呼ぶ
    phases = (_phase(a=5.0, b=5.1, c=5.2, scale=1.0, occ={"Fe": 0.8}),)
    config = MultistartConfig(n_starts=8)

    # 【実際の処理実行】: 同一 (phases, config) で 2 回生成
    starts_a = generate_starts(phases, config=config)
    starts_b = generate_starts(phases, config=config)

    # 【結果検証】: 乱数由来のブレがゼロでビット一致することを確認
    assert starts_a == starts_b  # 【確認内容】: 全 start の格子/scale/占有率が == (決定論) 🔵
    for i in range(8):
        assert starts_a[i][0].lattice.a == starts_b[i][0].lattice.a  # 【確認内容】: 格子 a のビット一致 🔵
        assert starts_a[i][0].scale == starts_b[i][0].scale  # 【確認内容】: scale のビット一致 🔵
        assert starts_a[i][0].occupancies == starts_b[i][0].occupancies  # 【確認内容】: 占有率のビット一致 🔵


def test_index_zero_is_unperturbed_equal_to_base():
    # 【テスト目的】: 任意の N で starts[0] が入力 phases と同値 (i=0 無摂動) であることを確認 (T-N03 / TC-201-07)
    # 【テスト内容】: 単相 (格子/scale/占有率あり) で i=0 の恒等性を検証
    # 【期待される動作】: starts[0] == phases、基準値がビット一致 (近似でなく ==)
    # 🔵 信頼性レベル: acceptance-criteria TC-201-07 / architecture.md D1 / interfaces.py L168 に依拠

    # 【テストデータ準備】: 基準そのものと一致するか確認するため代表値を設定
    phases = (_phase(a=5.0, scale=1.0, occ={"Fe": 0.8}),)

    # 【実際の処理実行】: N=8 で生成し先頭 start を検査
    starts = generate_starts(phases, config=MultistartConfig(n_starts=8))

    # 【結果検証】: i=0 が基準と同値であることを確認
    assert starts[0] == phases  # 【確認内容】: start 集合に基準解が無摂動で含まれる 🔵
    assert starts[0][0].lattice.a == 5.0  # 【確認内容】: 格子 a が基準そのまま (δ=0) 🔵
    assert starts[0][0].scale == 1.0  # 【確認内容】: scale が基準そのまま (offset=0) 🔵
    assert starts[0][0].occupancies == {"Fe": 0.8}  # 【確認内容】: 占有率が基準そのまま (lhs=0) 🔵


def test_lattice_perturbation_within_frac_grid_range():
    # 【テスト目的】: i>=1 の格子 a が基準 ±lattice_frac の範囲内で i により異なることを確認 (T-N04 / TC-201-01)
    # 【テスト内容】: lattice_frac=0.02, base_a=5.0 で格子摂動の範囲・分散・角度非摂動を検証
    # 【期待される動作】: 全 i で 4.9 <= a <= 5.1、少なくとも 2 つの i で a が異なる、角度は 90.0 のまま
    # 🔵 信頼性レベル: acceptance-criteria TC-201-01 / requirements 2.3 / architecture.md D1 に依拠

    # 【テストデータ準備】: 相対幅 ±2% の代表 (base_a=5.0 → [4.9, 5.1])
    base_a = 5.0
    phases = (_phase(a=base_a, b=base_a, c=base_a),)
    config = MultistartConfig(n_starts=8, spec=PerturbationSpec(lattice_frac=0.02))

    # 【実際の処理実行】: 格子摂動列を生成
    starts = generate_starts(phases, config=config)

    # 【結果検証】: 範囲内・分散・角度不変を確認
    a_values = []
    for i in range(8):
        a = starts[i][0].lattice.a
        a_values.append(a)
        assert 4.9 - 1e-9 <= a <= 5.1 + 1e-9  # 【確認内容】: 格子 a が基準 ±2% の範囲内 🔵
        assert starts[i][0].lattice.alpha == 90.0  # 【確認内容】: 角度 alpha は非摂動 🔵
        assert starts[i][0].lattice.beta == 90.0  # 【確認内容】: 角度 beta は非摂動 🔵
        assert starts[i][0].lattice.gamma == 90.0  # 【確認内容】: 角度 gamma は非摂動 🔵
    assert len(set(a_values)) >= 2  # 【確認内容】: グリッドが縮退せず 2 つ以上の異なる a を生む 🔵


def test_scale_perturbation_within_log_uniform_range():
    # 【テスト目的】: i>=1 の scale が対数一様グリッドの範囲内 (|log10比| <= range) であることを確認 (T-N05 / TC-201-01)
    # 【テスト内容】: base_scale=2.0, scale_log_range=0.5 で対数域の範囲・正値・分散を検証
    # 【期待される動作】: 全 i で abs(log10(scale/2.0)) <= 0.5、scale>0、少なくとも 2 つの i で scale が異なる
    # 🔵 信頼性レベル: acceptance-criteria TC-201-01 / requirements 2.3 / architecture.md D1 に依拠

    # 【テストデータ準備】: base_scale=2.0、対数片側幅 0.5 (10^±0.5 = ×0.316〜×3.16)
    base_scale = 2.0
    phases = (_phase(scale=base_scale),)
    config = MultistartConfig(n_starts=8, spec=PerturbationSpec(scale_log_range=0.5))

    # 【実際の処理実行】: scale 摂動列を生成
    starts = generate_starts(phases, config=config)

    # 【結果検証】: 対数域内・正値・分散を確認
    scales = []
    for i in range(8):
        s = starts[i][0].scale
        scales.append(s)
        assert s > 0.0  # 【確認内容】: scale が負や 0 にならない (対数域) 🔵
        assert abs(math.log10(s / base_scale)) <= 0.5 + 1e-9  # 【確認内容】: log10 比が片側幅 0.5 以内 🔵
    assert len(set(scales)) >= 2  # 【確認内容】: 対数グリッドが縮退せず分散する 🔵


def test_occupancy_perturbation_within_delta_and_clipped():
    # 【テスト目的】: i>=1 の占有率が [0,1] 内かつ基準から occupancy_delta 幅に収まることを確認 (T-N06 / TC-201-01)
    # 【テスト内容】: occ={"Fe":0.5,"O":0.9}, occupancy_delta=0.1 で範囲・幅・site 保存を検証
    # 【期待される動作】: 全 site 値が 0<=v<=1、abs(v-base)<=0.1、キー集合は基準と同一
    # 🔵 信頼性レベル: acceptance-criteria TC-201-01 / requirements 2.3・4.2 / architecture.md D1 に依拠

    # 【テストデータ準備】: 中央値 0.5 と上端寄り 0.9、摂動幅 0.1
    base_occ = {"Fe": 0.5, "O": 0.9}
    phases = (_phase(occ=dict(base_occ)),)
    config = MultistartConfig(n_starts=8, spec=PerturbationSpec(occupancy_delta=0.1))

    # 【実際の処理実行】: 占有率摂動列を生成
    starts = generate_starts(phases, config=config)

    # 【結果検証】: 範囲・幅・site 集合保存を確認
    for i in range(8):
        occ = starts[i][0].occupancies
        assert set(occ.keys()) == {"Fe", "O"}  # 【確認内容】: site 数・名が基準と同一 (欠落なし) 🔵
        for site, v in occ.items():
            assert 0.0 <= v <= 1.0  # 【確認内容】: 占有率が物理範囲 [0,1] 内 (クリップ) 🔵
            assert abs(v - base_occ[site]) <= 0.1 + 1e-9  # 【確認内容】: LHS 幅 occupancy_delta を超えない 🔵


def test_multi_phase_perturbs_each_phase_preserving_order():
    # 【テスト目的】: 2 相入力で各 start が A/B 両相に摂動を持ち相順が保存されることを確認 (T-N07 / 完了条件 4)
    # 【テスト内容】: 異なる格子/scale の 2 相 (A,B) で相順・phase_ref 保存と i=0 基準 / i>=1 摂動を検証
    # 【期待される動作】: 全 i で len==2 かつ相順保存、ある i>=1 で A・B ともに基準と異なる、i=0 は両相基準
    # 🟡 信頼性レベル: TASK-0027 完了条件 4 / architecture.md D1 (相ごと独立摂動は設計裁量) に依拠

    # 【テストデータ準備】: 異なる格子/scale の 2 相 = 多相摂動の代表
    a = _phase("A", a=5.0, scale=1.0)
    b = _phase("B", a=8.0, scale=0.5)
    phases = (a, b)

    # 【実際の処理実行】: N=4 で多相摂動列を生成
    starts = generate_starts(phases, config=MultistartConfig(n_starts=4))

    # 【結果検証】: 相数・相順保存、i=0 基準、i>=1 で両相摂動を確認
    for i in range(4):
        assert len(starts[i]) == 2  # 【確認内容】: 各 start が 2 相を保持 🔵
        assert starts[i][0].phase_ref == "A"  # 【確認内容】: 相順 (先頭 A) 保存 🔵
        assert starts[i][1].phase_ref == "B"  # 【確認内容】: 相順 (末尾 B) 保存 🔵
    assert starts[0][0].lattice.a == 5.0  # 【確認内容】: i=0 は相 A が基準 🔵
    assert starts[0][1].lattice.a == 8.0  # 【確認内容】: i=0 は相 B が基準 🔵
    both_perturbed = any(
        _differs(starts[i][0], a) and _differs(starts[i][1], b) for i in range(1, 4)
    )
    assert both_perturbed  # 【確認内容】: ある i>=1 で A・B 両相が摂動される (多相各相摂動) 🟡


def test_perturbation_spec_defaults_and_explicit_fields():
    # 【テスト目的】: PerturbationSpec が既定値と明示値で生成でき各フィールドを保持することを確認 (T-N08)
    # 【テスト内容】: 既定 → (0.02, 0.5, 0.1)、明示 → 指定値を検証
    # 【期待される動作】: 既定値が interfaces.py L131-133 と一致、任意値を保持
    # 🔵 信頼性レベル: interfaces.py L126-133 / requirements 2.1 に依拠

    # 【実際の処理実行】: 既定と明示の 2 種を生成
    default_spec = PerturbationSpec()
    explicit_spec = PerturbationSpec(lattice_frac=0.05, scale_log_range=1.0, occupancy_delta=0.2)

    # 【結果検証】: 既定値と保持値を確認
    assert default_spec.lattice_frac == 0.02  # 【確認内容】: lattice_frac 既定 0.02 🔵
    assert default_spec.scale_log_range == 0.5  # 【確認内容】: scale_log_range 既定 0.5 🔵
    assert default_spec.occupancy_delta == 0.1  # 【確認内容】: occupancy_delta 既定 0.1 🔵
    assert explicit_spec.lattice_frac == 0.05  # 【確認内容】: 明示 lattice_frac を保持 🔵
    assert explicit_spec.scale_log_range == 1.0  # 【確認内容】: 明示 scale_log_range を保持 🔵
    assert explicit_spec.occupancy_delta == 0.2  # 【確認内容】: 明示 occupancy_delta を保持 🔵


def test_multistart_config_defaults_nested_and_explicit_fields():
    # 【テスト目的】: MultistartConfig が既定 (n_starts=8, spec 既定, basin_rel_tol=1e-2, ms_max_cycles=15) を持ち
    #                 明示値・ネスト spec を保持することを確認 (T-N09)
    # 【テスト内容】: 既定と、n_starts=16 + カスタム spec を検証
    # 【期待される動作】: 既定 4 フィールドが interfaces.py L136-141 と一致、ネスト spec 既定は PerturbationSpec()
    # 🔵 信頼性レベル: interfaces.py L135-141 / requirements 2.2 に依拠

    # 【実際の処理実行】: 既定と明示の 2 種を生成
    default_config = MultistartConfig()
    explicit_config = MultistartConfig(n_starts=16, spec=PerturbationSpec(lattice_frac=0.05))

    # 【結果検証】: 既定値・ネスト既定・保持値を確認
    assert default_config.n_starts == 8  # 【確認内容】: n_starts 既定 8 (FR-231) 🔵
    assert default_config.basin_rel_tol == 1e-2  # 【確認内容】: basin_rel_tol 既定 1e-2 (器) 🔵
    assert default_config.ms_max_cycles == 15  # 【確認内容】: ms_max_cycles 既定 15 (器) 🔵
    assert default_config.spec.lattice_frac == 0.02  # 【確認内容】: ネスト spec の既定 (PerturbationSpec()) 🔵
    assert explicit_config.n_starts == 16  # 【確認内容】: 明示 n_starts (上限 16) を保持 🔵
    assert explicit_config.spec.lattice_frac == 0.05  # 【確認内容】: 明示ネスト spec を保持 🔵


def test_all_starts_are_mutually_distinct():
    # 【テスト目的】: N=8 で生成した start 群が相互に異なる初期値を持つ (縮退しない) ことを確認 (T-N10)
    # 【テスト内容】: 3 摂動全てが効く単相で分散を検証
    # 【期待される動作】: i=0 と i=1 は異なり、i>=1 は基準と異なる
    # 🟡 信頼性レベル: architecture.md D1 (グリッド分散) / requirements 1 からの妥当推測

    # 【テストデータ準備】: 格子/scale/占有率いずれも摂動対象の単相
    base = _phase(a=5.0, scale=1.0, occ={"Fe": 0.5})
    phases = (base,)

    # 【実際の処理実行】: N=8 で生成
    starts = generate_starts(phases, config=MultistartConfig(n_starts=8))

    # 【結果検証】: 分散 (縮退しないこと) を確認
    assert _key(starts[0][0]) != _key(starts[1][0])  # 【確認内容】: i=0 基準と i=1 摂動が区別可能 🟡
    for i in range(1, 8):
        assert _differs(starts[i][0], base)  # 【確認内容】: i>=1 は基準と異なる摂動を持つ 🟡


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（エラーハンドリング / 頑健性）
# ---------------------------------------------------------------------------


def test_empty_occupancies_skips_occupancy_perturbation():
    # 【テスト目的】: occupancies=={} の相で占有率摂動をスキップし例外を出さないことを確認 (T-E01)
    # 【テスト内容】: 占有率なし相で全 start の占有率が {} のまま、格子/scale は摂動されることを検証
    # 【期待される動作】: 例外なし、全 start で occupancies=={}、格子/scale は摂動される
    # 🟡 信頼性レベル: requirements 4.2 (空 occupancies 挙動) からの妥当推測

    # 【テストデータ準備】: 占有率を持たない (格子/scale のみ精密化) 相
    base = _phase(a=5.0, scale=1.0, occ={})
    phases = (base,)

    # 【実際の処理実行】: 空 dict への操作で KeyError/ZeroDivisionError を起こさないことを確認
    starts = generate_starts(phases, config=MultistartConfig(n_starts=8))

    # 【結果検証】: 占有率が空のまま、格子/scale は摂動されることを確認
    for i in range(8):
        assert starts[i][0].occupancies == {}  # 【確認内容】: 占有率摂動をスキップし空のまま 🟡
    perturbed = any(_differs(starts[i][0], base) for i in range(1, 8))
    assert perturbed  # 【確認内容】: 占有率なしでも格子/scale は摂動される 🟡


def test_occupancy_clipped_to_unit_interval_at_boundaries():
    # 【テスト目的】: 基準占有率が 1.0/0.0 近傍でも摂動値が [0,1] にクリップされることを確認 (T-E02)
    # 【テスト内容】: occ={"Fe":1.0,"O":0.0}, occupancy_delta=0.1 で範囲外値のクリップを検証
    # 【期待される動作】: 全 start・全 site で 0.0<=v<=1.0 を厳守 (min(max(v,0),1) 相当)
    # 🟡 信頼性レベル: requirements 4.2 / architecture.md D1 (占有率 [0,1]) からの妥当推測

    # 【テストデータ準備】: 完全占有 site (1.0) と空孔 site (0.0) = クリップ境界
    phases = (_phase(occ={"Fe": 1.0, "O": 0.0}),)
    config = MultistartConfig(n_starts=8, spec=PerturbationSpec(occupancy_delta=0.1))

    # 【実際の処理実行】: 境界占有率の摂動列を生成
    starts = generate_starts(phases, config=config)

    # 【結果検証】: 非物理的占有率を返さない (クリップ) ことを確認
    for i in range(8):
        occ = starts[i][0].occupancies
        assert 0.0 <= occ["Fe"] <= 1.0  # 【確認内容】: 完全占有 site が 1.0 を超えない 🟡
        assert 0.0 <= occ["O"] <= 1.0  # 【確認内容】: 空孔 site が 0.0 を下回らない 🟡


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（最小値・境界・null・回帰）
# ---------------------------------------------------------------------------


def test_n_starts_one_degenerates_to_base_only():
    # 【テスト目的】: n_starts=1 で基準 1 組のみを返し 0 除算しないことを確認 (T-B01 / TC-201-07 / EDGE-101)
    # 【テスト内容】: N=1 縮退でグリッド分母 N-1=0 を回避し基準をそのまま返すことを検証
    # 【期待される動作】: len(starts)==1、starts[0]==phases (基準と同値)、例外なし
    # 🔵 信頼性レベル: acceptance-criteria TC-201-07 / requirements EDGE-101 / architecture.md D1 に依拠

    # 【テストデータ準備】: グリッド分母が退化する最小ケース
    phases = (_phase(a=5.0, scale=1.0, occ={"Fe": 0.8}),)

    # 【実際の処理実行】: N=1 で生成 (0 除算・空グリッドを起こさないこと)
    starts = generate_starts(phases, config=MultistartConfig(n_starts=1))

    # 【結果検証】: 基準 1 組のみを確認
    assert len(starts) == 1  # 【確認内容】: start 本数が 1 (最小本数) 🔵
    assert starts[0] == phases  # 【確認内容】: 摂動なしで基準と同値 (i=0 無摂動の原則) 🔵


def test_input_phases_are_not_mutated():
    # 【テスト目的】: generate_starts が入力 phases を書き換えない (非破壊) ことを確認 (T-B02 / P2 / REQ-404)
    # 【テスト内容】: 呼び出し後に base の格子/scale/占有率と元 dict が不変であることを検証
    # 【期待される動作】: 実行後も base の全フィールドと元 occ dict が不変
    # 🔵 信頼性レベル: requirements 3 (非破壊) / CLAUDE.md P2 / REQ-404 に依拠

    # 【テストデータ準備】: 占有率 dict の in-place 変更 (誤実装の罠) を検出するため参照を保持
    occ = {"Fe": 0.8}
    base = _phase(a=5.0, scale=1.0, occ=occ)
    phases = (base,)

    # 【実際の処理実行】: 摂動列を生成 (副作用ゼロの純関数であること)
    generate_starts(phases, config=MultistartConfig(n_starts=8))

    # 【結果検証】: 入力が呼び出し前後で不変であることを確認
    assert base.lattice.a == 5.0  # 【確認内容】: 入力格子 a が不変 🔵
    assert base.scale == 1.0  # 【確認内容】: 入力 scale が不変 🔵
    assert base.occupancies == {"Fe": 0.8}  # 【確認内容】: 入力占有率が不変 🔵
    assert occ == {"Fe": 0.8}  # 【確認内容】: 元の占有率 dict が in-place 変更されていない 🔵


def test_spec_and_config_are_frozen():
    # 【テスト目的】: PerturbationSpec / MultistartConfig が frozen で再代入を拒否することを確認 (T-B03)
    # 【テスト内容】: frozen 属性への代入が FrozenInstanceError を送出することを検証
    # 【期待される動作】: いずれの代入も FrozenInstanceError
    # 🔵 信頼性レベル: CLAUDE.md (frozen 規約) / interfaces.py L126・135 に依拠

    # 【テストデータ準備】: 既定インスタンスを 2 種用意
    spec = PerturbationSpec()
    config = MultistartConfig()

    # 【結果検証】: 不変値オブジェクトへの再代入拒否を確認
    with pytest.raises(FrozenInstanceError):
        spec.lattice_frac = 0.1  # type: ignore[misc]  # 【確認内容】: PerturbationSpec が frozen 🔵
    with pytest.raises(FrozenInstanceError):
        config.n_starts = 2  # type: ignore[misc]  # 【確認内容】: MultistartConfig が frozen 🔵


def test_n_starts_two_minimal_nondegenerate_grid():
    # 【テスト目的】: n_starts=2 で i=0 基準・i=1 摂動が明確に分かれることを確認 (T-B04)
    # 【テスト内容】: N=2 (分母 N-1=1) の最小摂動ケースで基準+摂動の 2 点を検証
    # 【期待される動作】: len==2、starts[0]==phases、starts[1] は格子 or scale が基準と異なる
    # 🟡 信頼性レベル: architecture.md D1 (等間隔グリッド) / EDGE-101 隣接ケースからの妥当推測

    # 【テストデータ準備】: N=1 (縮退) と N=8 (通常) の間の最小摂動ケース
    base = _phase(a=5.0, scale=1.0)
    phases = (base,)

    # 【実際の処理実行】: N=2 で生成 (分母 N-1=1 で 0 除算しないこと)
    starts = generate_starts(phases, config=MultistartConfig(n_starts=2))

    # 【結果検証】: 基準 + 摂動の 2 点構造を確認
    assert len(starts) == 2  # 【確認内容】: グリッド 2 点が生成される 🟡
    assert starts[0] == phases  # 【確認内容】: i=0 基準の原則が N=2 でも保たれる 🟡
    assert _differs(starts[1][0], base)  # 【確認内容】: i=1 は基準と異なる摂動を持つ 🟡


def test_generate_starts_returns_fresh_independent_instances():
    # 【テスト目的】: 摂動 start が入力から独立した新インスタンスであること (純新規・非破壊追加) を確認 (T-B05)
    # 【テスト内容】: 純新規モジュール追加が既存資産を壊さないゲートを、返り値の独立性 (object identity) で検証
    #                 (suite 全体の 505 collected 無退行は verify-complete フェーズで確認)
    # 【期待される動作】: i>=1 の摂動 start は入力オブジェクトと別インスタンス (is not)、値は基準と異なる
    # 🔵 信頼性レベル: CLAUDE.md 不変条件 / REQ-404 / note.md ベースライン (505) に依拠

    # 【テストデータ準備】: 摂動が効く単相を保持
    base = _phase(a=5.0, scale=1.0, occ={"Fe": 0.5})
    phases = (base,)

    # 【実際の処理実行】: 摂動列を生成
    starts = generate_starts(phases, config=MultistartConfig(n_starts=8))

    # 【結果検証】: 返り値が入力から独立した新インスタンス群であることを確認
    for i in range(1, 8):
        assert starts[i][0] is not base  # 【確認内容】: 摂動 start は入力と別オブジェクト (非破壊生成) 🔵
        assert starts[i][0].lattice is not base.lattice  # 【確認内容】: 格子も別インスタンス 🔵


def test_scale_grid_is_log_uniform_spanning_the_range():
    # 【テスト目的】: scale 摂動が対数一様グリッド (線形でない) で対数域を張ることを確認 (T-B06)
    # 【テスト内容】: base_scale=1.0, N=9, scale_log_range=1.0 で対数域の範囲・両側分布・スパンを検証
    # 【期待される動作】: 全 i で |log10(scale)|<=1.0、正負両側の offset が存在、offset のスパンが range 以上
    # 🟡 信頼性レベル: architecture.md D1 (対数一様グリッド) / requirements 2.3 に依拠 (具体配置は 🟡)

    # 【テストデータ準備】: 奇数 N=9 (中央 index あり)、対数域 [-1,1] = ×0.1〜×10
    phases = (_phase(scale=1.0),)
    config = MultistartConfig(n_starts=9, spec=PerturbationSpec(scale_log_range=1.0))

    # 【実際の処理実行】: 広い対数域の scale 摂動列を生成
    starts = generate_starts(phases, config=config)

    # 【結果検証】: 対数域内・両側分布・スパンを確認
    offsets = [math.log10(starts[i][0].scale / 1.0) for i in range(9)]
    for o in offsets:
        assert abs(o) <= 1.0 + 1e-9  # 【確認内容】: log10 offset が対数域 [-1,1] 内 🟡
    assert any(o > 1e-9 for o in offsets)  # 【確認内容】: 基準より大きい scale が存在 (対数上側) 🟡
    assert any(o < -1e-9 for o in offsets)  # 【確認内容】: 基準より小さい scale が存在 (対数下側) 🟡
    assert (max(offsets) - min(offsets)) >= 1.0 - 1e-9  # 【確認内容】: offset が対数域を張る (線形微小摂動でない) 🟡
