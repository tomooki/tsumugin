"""TASK-0027 multistart/perturb — 決定論的初期値摂動列生成 (FR-231 / 設計 D1)。

マルチスタート大域最適確認 (FR-230) の入口となる「初期値摂動列生成器」を、
**乱数を一切使わない start index ベースの決定論列**として提供する。

- ``PerturbationSpec``: 摂動幅の設定値のみを保持する frozen 値オブジェクト。
- ``MultistartConfig``: マルチスタート全体設定 (本タスクで使うのは ``n_starts`` / ``spec``)。
- ``generate_starts(phases, *, config)``: start index の純関数で摂動 phases 列を返す。
  i=0 は無摂動 (基準)、i>=1 は index から一意に決まる決定論値 (格子等間隔グリッド・
  scale 対数一様グリッド・占有率固定 LHS)。

🔵 信頼性レベル: interfaces.py L124-169 / architecture.md D1 / AC TC-201-01・07 に依拠。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from tsumugin.model import PhaseInstance


@dataclass(frozen=True)
class PerturbationSpec:
    """【機能概要】: 決定論摂動の幅設定のみを保持する不変値オブジェクト。

    【実装方針】: interfaces.py L126-133 の 3 フィールドをそのまま frozen dataclass 化。
    【テスト対応】: test_perturbation_spec_defaults_and_explicit_fields / test_spec_and_config_are_frozen。
    🔵 信頼性レベル: interfaces.py L126-133 / requirements 2.1 (既定値は 🟡 チューニング既定)。
    """

    lattice_frac: float = 0.02  # 【格子幅】: 格子定数 a/b/c の相対摂動幅 (±2%)
    scale_log_range: float = 0.5  # 【scale 幅】: scale の log10 空間での片側幅 (10^±0.5)
    occupancy_delta: float = 0.1  # 【占有率幅】: 占有率 LHS オフセットの絶対幅


@dataclass(frozen=True)
class MultistartConfig:
    """【機能概要】: マルチスタート全体設定 (本タスクは n_starts / spec を消費)。

    【実装方針】: interfaces.py L135-141 準拠。basin_rel_tol / ms_max_cycles は器として
    正しい既定値で保持するのみ (消費は TASK-0028)。
    【テスト対応】: test_multistart_config_defaults_nested_and_explicit_fields / frozen 検証。
    🔵 信頼性レベル: interfaces.py L135-141 / requirements 2.2 (D2/D3 既定値は 🟡)。
    """

    n_starts: int = 8  # 【本数】: 生成する start 組数 N (FR-231: 8-16)
    spec: PerturbationSpec = PerturbationSpec()  # 【摂動幅】: ネスト既定は共有安全 (frozen)
    basin_rel_tol: float = 1e-2  # 【器のみ】: basin クラスタ距離閾値 (TASK-0028 で消費)
    ms_max_cycles: int = 15  # 【器のみ】: 各 start の refine 上限 (TASK-0028 で消費)


def _grid_positions(m: int) -> list[float]:
    """【機能概要】: 摂動 start 数 m に対する [-1, 1] の等間隔グリッド位置列を返す。

    【実装方針】: 乱数を使わず index から一意に決まる決定論グリッド。m>=2 は端点 -1..+1 を
    含む等間隔列、m==1 は単一の非零点 (+1)、m<=0 は空。
    【テスト対応】: 格子/scale の範囲・分散・対数スパン検証 (TC-201-01) の基盤。
    🔵 信頼性レベル: architecture.md D1 (等間隔グリッド) / requirements 2.3 に依拠。
    """
    # 【縮退回避】: N=1 (m=0) では摂動 start が無いので空列を返し 0 除算を避ける 🔵
    if m <= 0:
        return []
    # 【単一点】: N=2 (m=1) では基準と区別できる非零点 1 つ (分母 m-1=0 を踏まない) 🔵
    if m == 1:
        return [1.0]
    # 【等間隔グリッド】: k=0..m-1 を -1..+1 に線形写像 (端点を含む) 🔵
    return [-1.0 + 2.0 * k / (m - 1) for k in range(m)]


def _clip_unit(value: float) -> float:
    """【機能概要】: 占有率を物理範囲 [0, 1] にクリップする。🟡 requirements 4.2 (境界)。"""
    # 【範囲固定】: 摂動加算で範囲外に出た占有率を [0,1] に収める (非物理値を返さない)
    return min(max(value, 0.0), 1.0)


def generate_starts(
    phases: tuple[PhaseInstance, ...], *, config: MultistartConfig
) -> tuple[tuple[PhaseInstance, ...], ...]:
    """【機能概要】: start index ごとの決定論摂動 phases 列を生成する (i=0 は無摂動)。

    【実装方針】: 乱数不使用。摂動値は start index i・相 index j・site index s・パラメータ種別
    のみから ``_grid_positions`` の純関数で導出する。格子と scale はグリッド上で半周ずらし
    (decorrelate) し、i>=1 の全 start が基準と必ず異なるようにする。更新は ``replace`` /
    ``with_updates`` による非破壊生成のみ。
    【テスト対応】: multistart-perturb 18 件 (決定論・範囲・i=0 無摂動・N=1 縮退・非破壊)。
    🔵 信頼性レベル: interfaces.py L165-169 / architecture.md D1 / AC TC-201-01・07 に依拠。

    @param phases: 基準となる相群 (1 相以上)。
    @param config: マルチスタート設定 (keyword-only)。
    @returns: 長さ ``config.n_starts`` の tuple。各要素は摂動済み phases (相数・相順は保存)。
    """
    n = config.n_starts  # 【本数】: 生成する start 組数 N
    spec = config.spec  # 【摂動幅】: 格子/scale/占有率の幅設定
    m = n - 1  # 【摂動 start 数】: i=0 を除く摂動対象の本数
    positions = _grid_positions(m)  # 【グリッド】: [-1,1] 決定論等間隔位置列
    half = m // 2  # 【decorrelate 量】: 格子と scale をグリッド上で半周ずらす index 差

    # 【i=0 無摂動】: 基準 phases をそのまま先頭に置く (恒等・0 除算回避) 🔵
    starts: list[tuple[PhaseInstance, ...]] = [phases]

    # 【i>=1 摂動列】: index から一意な決定論摂動を各相に適用する 🔵
    for i in range(1, n):
        k = i - 1  # 【摂動 index】: 0..m-1 の摂動 start 位置
        perturbed: list[PhaseInstance] = []
        for j, phase in enumerate(phases):
            # 【格子摂動】: a/b/c に相対摂動 (角度は非摂動)。等間隔グリッド上の点 🔵
            lat_pos = positions[(k + j) % m]
            delta = spec.lattice_frac * lat_pos
            new_lattice = replace(
                phase.lattice,
                a=phase.lattice.a * (1.0 + delta),
                b=phase.lattice.b * (1.0 + delta),
                c=phase.lattice.c * (1.0 + delta),
            )

            # 【scale 摂動】: 対数一様グリッド上で scale * 10^offset (格子とは半周ずらす) 🔵
            scale_pos = positions[(k + j + half) % m]
            offset_log = spec.scale_log_range * scale_pos
            new_scale = phase.scale * (10.0**offset_log)

            # 【占有率摂動】: 固定 LHS 由来オフセットを site ごとに加算し [0,1] クリップ 🔵🟡
            if phase.occupancies:
                new_occ: dict[str, float] = {}
                for s, (site, base_val) in enumerate(phase.occupancies.items()):
                    occ_pos = positions[(k + j + s) % m]
                    new_occ[site] = _clip_unit(base_val + spec.occupancy_delta * occ_pos)
            else:
                # 【空スキップ】: occupancies=={} の相は占有率摂動をスキップ (空のまま) 🟡
                new_occ = dict(phase.occupancies)

            # 【非破壊生成】: 新インスタンスを生成し入力 phase は変更しない (P2 / REQ-404) 🔵
            perturbed.append(
                phase.with_updates(lattice=new_lattice, scale=new_scale, occupancies=new_occ)
            )
        starts.append(tuple(perturbed))

    # 【結果返却】: N 組の摂動 phases 列を不変 tuple で返す 🔵
    return tuple(starts)
