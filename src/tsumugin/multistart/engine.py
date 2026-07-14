"""TASK-0028 multistart/engine — マルチスタート大域最適確認エンジン (FR-230/232 / 設計 D2/D3)。

``MultistartEngine.run`` が決定論摂動列 (``generate_starts``, TASK-0027) を入口に、各 start を
**direct refine** (staged 解放ループなし、``ms_max_cycles`` で 1 回だけ精密化) して収束解を集め、
発散 (chi2 非有限) を除外し、``cluster_basins`` で basin へ畳んで ``MultistartResult`` を返す。

- 単一 basin → ``is_global_corroborated=True`` (「大域最適の傍証あり」)、``promoted=()``。
- 複数 basin → 各 basin 代表を ``Hypothesis`` へ昇格 (``metrics.multistart`` 付き) し evidence 昇順で ``promoted``。
- 全滅 (全 start 発散) → ``warnings`` + 空 basins (元仮説維持)、``is_global_corroborated=False``。
- ``ledger`` 提供時は各操作を ``append("multistart.*", ...)`` で追記 (verify() は常に True)。

各 start は独立な純関数ループ (map 置換可能 / REQ-005) で、乱数不使用・2 回実行でビット同一 (NFR-102)。

🔵 信頼性レベル: interfaces.py L153-191 (MultistartResult / MultistartEngine) / architecture.md
  D2 (direct refine) / D3 (basin) / REQ-002〜006・102 / TC-201-02〜07 に依拠。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from ..backends.base import RefinementBackend, RefinementModel, RefinementResult, param_name
from ..model import Hypothesis, PhaseInstance, RefinementMetrics
from ..store.ledger import Ledger
from .basin import BasinInfo, cluster_basins
from .perturb import MultistartConfig, generate_starts

# 【direct refine の既定解放パラメータ接尾辞】: scale + 格子 a/b/c (探索モード相当のコストに抑える) 🔵
_DEFAULT_FREE_SUFFIXES = ("scale", "lattice.a", "lattice.b", "lattice.c")


@dataclass(frozen=True)
class MultistartResult:
    """【機能概要】: マルチスタート大域最適確認の結果を保持する不変値オブジェクト。

    【実装方針】: interfaces.py L153-162 の 6 フィールドを frozen dataclass 化。warnings は末尾
    既定 () で後方互換。basins は evidence 昇順、promoted は複数 basin 時のみ非空。
    【テスト対応】: test_basininfo_and_result_are_frozen ほか engine 系 12 件。
    🔵 信頼性レベル: interfaces.py L153-162 / REQ-002/003/102 に直接依拠。
    """

    basins: tuple[BasinInfo, ...]  # 【basin 群】: evidence 昇順 (発散除外後)
    n_starts: int  # 【start 総数】: 実行した start 本数 (= config.n_starts)
    n_diverged: int  # 【発散数】: chi2 非有限で basin から除外した start 数
    promoted: tuple[Hypothesis, ...]  # 【昇格仮説】: 複数 basin 時のみ各 basin を昇格 (単一なら ())
    is_global_corroborated: bool  # 【傍証フラグ】: n_basins == 1 (大域最適の傍証あり)
    warnings: tuple[str, ...] = ()  # 【警告】: 全滅時の縮退警告など (既定 空)


class MultistartEngine:
    """【機能概要】: 決定論マルチスタート精密化を実行し basin 報告・昇格・ledger 記録を行うエンジン。

    【実装方針】: 精密化バックエンドは RefinementBackend Protocol 依存 (GSAS-II 非依存)。run は
    generate_starts → 各 start direct refine (純関数ループ) → 発散除外 → cluster_basins →
    複数 basin 昇格 → MultistartResult の薄いオーケストレータ。乱数不使用で決定論。
    【テスト対応】: engine 系 12 件 (単峰/双峰/昇格/metrics/direct 回数/ledger/決定論/発散/全滅/N=1/ledger 無)。
    🔵 信頼性レベル: interfaces.py L172-191 / architecture.md D2/D3 に直接依拠。
    """

    def __init__(
        self,
        backend: RefinementBackend,
        *,
        config: MultistartConfig = MultistartConfig(),
        ledger: Ledger | None = None,
    ) -> None:
        # 【依存注入】: 精密化バックエンド・設定・台帳を保持 (ledger=None なら記録スキップ) 🔵
        self.backend = backend
        self.config = config
        self.ledger = ledger

    def run(
        self,
        phases: tuple[PhaseInstance, ...],
        two_theta: np.ndarray,
        intensity: np.ndarray,
        *,
        free_suffixes: tuple[str, ...] = _DEFAULT_FREE_SUFFIXES,
        weights: np.ndarray | None = None,
    ) -> MultistartResult:
        """【機能概要】: N 本の摂動初期値を direct refine し basin 化した MultistartResult を返す。

        【実装方針】: generate_starts で N 組の初期値を作り、各 start を独立に (map 置換可能な
        純関数ループ) direct refine。chi2 非有限を発散として除外・カウントし、残りを
        cluster_basins へ。複数 basin なら各 basin を Hypothesis へ昇格 (metrics.multistart 付き)。
        全滅なら警告 + 空 basins (元仮説維持)。ledger 提供時は各操作を追記。
        【テスト対応】: engine 系 12 件すべて。
        🔵 信頼性レベル: architecture.md D2/D3 / dataflow / REQ-002〜006・102 に依拠。

        @param phases: 基準となる相群 (摂動列の起点)。破壊しない。
        @param two_theta: 観測 2θ 配列 (backend へ委譲)。
        @param intensity: 観測強度配列 (n_obs の基準)。
        @param free_suffixes: direct refine で解放するパラメータ接尾辞 (既定 scale + 格子 a/b/c)。
        @param weights: 観測重み (任意)。
        @returns: basin 報告・昇格・傍証フラグを含む MultistartResult。
        """
        # 【フェーズ 1: 摂動列生成】: i=0 無摂動 + i>=1 決定論摂動の N 組初期値 (TASK-0027) 🔵
        starts = generate_starts(phases, config=self.config)
        n_starts = len(starts)

        # 【free_params 構築】: free_suffixes × 全相 index を param_name で "phase{j}.{suffix}" に 🔵
        free_params = frozenset(
            param_name(j, suffix) for j in range(len(phases)) for suffix in free_suffixes
        )

        # 【フェーズ 2: direct refine】: 各 start を独立に精密化し発散を除外・カウント (D2/REQ-102) 🔵
        surviving_indices, surviving_results, n_diverged = self._refine_starts(
            starts, free_params, two_theta, intensity, weights
        )

        # 【フェーズ 3: basin クラスタ】: 生存解を正規化パラメータ距離で basin 化 (D3) 🔵
        raw_basins = cluster_basins(surviving_results, basin_rel_tol=self.config.basin_rel_tol)

        # 【start index 再マップ】: cluster_basins の positional member を元の start index へ戻す 🔵
        basins = self._remap_basins(raw_basins, surviving_indices)
        for basin in basins:
            self._record(
                "multistart.basin",
                {"members": list(basin.member_starts), "chi2": basin.chi2, "evidence": basin.evidence},
            )

        # 【フェーズ 4: 傍証判定】: 単一 basin = 大域最適の傍証あり (REQ-003 / EDGE-001) 🔵
        n_basins = len(basins)
        is_global_corroborated = n_basins == 1

        # 【昇格】: 複数 basin のときのみ各 basin 代表を Hypothesis へ昇格 (evidence 昇順 / FR-232) 🔵
        promoted: tuple[Hypothesis, ...]
        if n_basins > 1:
            promoted = tuple(
                self._promote(basin, order, n_starts, n_basins, n_diverged)
                for order, basin in enumerate(basins)
            )
            for hypothesis in promoted:
                self._record("multistart.promote", {"id": hypothesis.id})
        else:
            promoted = ()

        # 【フェーズ 5: 全滅の縮退】: 生存 0 は警告 + 空 basins (元仮説維持)。非例外化 (EDGE-002) 🟡
        warnings: tuple[str, ...] = ()
        if not surviving_results:
            message = f"all {n_starts} starts diverged; basins empty (original hypothesis retained)"
            warnings = (message,)
            self._record("multistart.warning", {"message": message, "n_diverged": n_diverged})

        # 【フェーズ 6: 結果集約 (記録)】: 実行サマリを台帳へ (ledger 提供時のみ) 🔵
        self._record(
            "multistart.result",
            {
                "n_starts": n_starts,
                "n_diverged": n_diverged,
                "n_basins": n_basins,
                "is_global_corroborated": is_global_corroborated,
            },
        )

        # 【結果返却】: basin 報告・昇格・傍証フラグを不変値オブジェクトで返す 🔵
        return MultistartResult(
            basins=basins,
            n_starts=n_starts,
            n_diverged=n_diverged,
            promoted=promoted,
            is_global_corroborated=is_global_corroborated,
            warnings=warnings,
        )

    def _refine_starts(
        self,
        starts: Sequence[tuple[PhaseInstance, ...]],
        free_params: frozenset[str],
        two_theta: np.ndarray,
        intensity: np.ndarray,
        weights: np.ndarray | None,
    ) -> tuple[list[int], list[RefinementResult], int]:
        """【ヘルパー関数】: 各 start を direct refine し発散除外済みの生存解列を返す。

        【機能概要】: N 組の初期値を start index 順に 1 回ずつ精密化 (staged 解放ループなし、
        max_cycles=ms_max_cycles) し、chi2 非有限の start を除外して n_diverged にカウントする。
        【改善内容】: run() に内包されていた refine ループを抽出し、run() を「摂動列生成 →
        精密化 → basin 化 → 昇格 → 縮退 → 集約」の読めるフェーズ列に分解した (可読性向上)。
        【設計方針】: 各 start は独立評価の純関数ループ (map 置換可能 / REQ-005 並列化非阻害)。
        発散は例外化せず縮退 (CLAUDE.md「失敗は chi2=inf 結果へ変換」)。
        【単一責任】: 精密化と発散仕分けのみを担い、basin 化・昇格には関与しない。
        🔵 信頼性レベル: architecture.md D2 (direct refine) / REQ-005/102 / TC-E05・A01 に依拠。

        @param starts: generate_starts が返した N 組の初期 phases (start index 順)。
        @param free_params: 解放パラメータ名集合 ("phase{j}.{suffix}")。
        @param two_theta: 観測 2θ 配列 (backend へ委譲)。
        @param intensity: 観測強度配列。
        @param weights: 観測重み (任意)。
        @returns: (生存 start index 列 [昇順], 生存収束解列 [同順], 発散数) のタプル。
        """
        surviving_indices: list[int] = []
        surviving_results: list[RefinementResult] = []
        n_diverged = 0
        for index, phases_i in enumerate(starts):
            model = RefinementModel(
                phases=phases_i,
                free_params=free_params,
                two_theta=two_theta,
                intensity=intensity,
                weights=weights,
            )
            # 【direct 精密化】: staged 解放ループなし、max_cycles=ms_max_cycles で 1 回だけ 🔵
            result = self.backend.refine(model, max_cycles=self.config.ms_max_cycles)
            self._record("multistart.start", {"start": index, "chi2": result.chi2})
            # 【発散除外】: chi2 非有限は例外化せず basin 対象外にして n_diverged へ加算 (REQ-102) 🔵
            if math.isfinite(result.chi2):
                surviving_indices.append(index)
                surviving_results.append(result)
            else:
                n_diverged += 1
        return surviving_indices, surviving_results, n_diverged

    def _remap_basins(
        self, raw_basins: tuple[BasinInfo, ...], surviving_indices: list[int]
    ) -> tuple[BasinInfo, ...]:
        """【機能概要】: cluster_basins の positional member を元の start index へ再マップする。

        【実装方針】: 発散除外で生存解を詰めたため member_starts は生存列の positional index。
        surviving_indices で元 start index に戻し、evidence 昇順 (同点は先頭 member 小) で再整列。
        surviving_indices は昇順のため順序は不変だが決定論を明示的に担保する。
        🔵 信頼性レベル: TC-A01 (発散 start を basin から除外し元 index を保つ) に依拠。
        """
        # 【再マップ】: positional member → 元 start index。BasinInfo を再構築 (frozen のため) 🔵
        remapped: list[BasinInfo] = []
        for basin in raw_basins:
            members = tuple(sorted(surviving_indices[p] for p in basin.member_starts))
            remapped.append(
                BasinInfo(
                    representative=basin.representative,
                    member_starts=members,
                    chi2=basin.chi2,
                    evidence=basin.evidence,
                )
            )
        # 【再整列】: evidence 昇順 (同点は先頭 member index 小) でビット同一を保証 🔵
        remapped.sort(key=lambda basin: (basin.evidence, basin.member_starts[0]))
        return tuple(remapped)

    def _promote(
        self, basin: BasinInfo, order: int, n_starts: int, n_basins: int, n_diverged: int
    ) -> Hypothesis:
        """【機能概要】: 1 つの basin 代表を metrics.multistart 付き Hypothesis へ昇格する。

        【実装方針】: 代表 phases をそのまま持つ Hypothesis を作り、RefinementMetrics に
        multistart={"n","n_basins","n_diverged"} を記録 (REQ-006 / TC-201-06)。id は order から
        決定論的に生成しビット同一を保つ。
        🔵 信頼性レベル: interfaces.py L86 / REQ-003/006 / TC-201-04・06 に依拠。
        """
        # 【metrics 付与】: 代表の適合度 + マルチスタートメタ (非破壊フィールド multistart) 🔵
        representative = basin.representative
        metrics = RefinementMetrics(
            rwp=representative.rwp,
            gof=0.0,
            chi2=representative.chi2,
            n_obs=representative.n_obs,
            n_params=representative.n_params,
            multistart={"n": n_starts, "n_basins": n_basins, "n_diverged": n_diverged},
            # 【Issue #64 / FR-123 写像】: backend が推定した noise_scale を metrics へ伝播する 🔵
            noise_scale=representative.noise_scale,
        )
        # 【昇格】: 代表 phases を持つ候補仮説を決定論 id で生成 🔵
        return Hypothesis(
            id=f"multistart-basin-{order}",
            phases=representative.phases,
            metrics=metrics,
            status="candidate",
        )

    def _record(self, kind: str, payload: Mapping[str, object]) -> None:
        """【機能概要】: ledger 提供時のみ操作を追記する (append-only / verify() 維持)。

        【実装方針】: ledger=None なら記録スキップ (エンジンは ledger 非依存で動作 / TC-BV05)。
        kind は必ず "multistart." 前置。Ledger.append はハッシュチェーンを伸ばし verify() は常に True。
        【改善内容】: payload 型を dict → Mapping[str, object] へ (Ledger.append 契約に整合)。
        🔵 信頼性レベル: NFR-105 / store/ledger.py append / TC-E06 に依拠。
        """
        # 【None ガード】: 台帳未提供なら何もしない (結果は ledger 有無で不変) 🔵
        if self.ledger is not None:
            self.ledger.append(kind, payload)
