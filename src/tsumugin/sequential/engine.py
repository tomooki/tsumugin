"""オンライン逐次精密化 + 局所木探索エンジン (仕様 FR-301〜306 / interfaces.py L211-253)。

時系列フレーム列 ``FrameSeries`` を先頭から**単一パス**で逐次 Rietveld 精密化し、相構成の
変化点 (changepoint) でのみ局所木探索を起動して相構成を更新しながら、フレームごとの結果を
``Trajectory`` に組み立てるオーケストレーション本体 (D1/D2/D3)。下位部品
(``StagedRefinementEngine`` / ``HypothesisTreeSearch`` / ``detect_changepoint`` /
``LifecycleTracker`` / ``Trajectory``) を束ねるだけで新規ロジックは薄い。

決定論 (NFR-102 / REQ-402): 乱数不使用・安定ソート・dict 反復順非依存。同一入力の 2 回実行で
``SequentialResult`` の全出力がビット同一になる。非有限を漏らさない (M1 教訓 / EDGE-002): 精密化
失敗フレームは例外化せず ``rwp=None/chi2=None/refine_failed=True`` で伝播し、直近成功フレームから
warm start を継続する。``orchestration="native"`` は未実装 (REQ-105 / FR-302 は M-later) で
``NotImplementedError`` を送出する。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

import numpy as np

from ..backends.base import RefinementBackend, RefinementModel, RefinementResult, param_name
from ..evidence.base import EvidenceBackend
from ..evidence.ic import BICBackend
from ..model import Hypothesis, PhaseInstance, RefinementMetrics
from ..refinement.staged import RefinementReport, StagedRefinementEngine
from ..search.clustering import PhaseCandidate
from ..search.matcher import match_score, unmatched_peaks
from ..search.peaks import find_peaks
from ..search.tree import HypothesisTreeSearch, SearchConfig, SearchResult
from ..store.ledger import Ledger
from ..store.snapshot import SnapshotStore
from .changepoint import ChangepointConfig, detect_changepoint
from .lifecycle import LifecycleConfig, LifecycleTracker
from .series import FrameSeries
from .trajectory import FrameRecord, Trajectory

__all__ = ["SequentialConfig", "SequentialEngine", "SequentialResult"]

# 【定数定義】: 後続フレームの direct refine で解放するパラメータ suffix (tree.py と同一)。
#   全相の scale + 格子 a/b/c のみを解放する (D2/REQ-003)。frame0 staged / 局所探索と識別可能 🔵
_EXPLORE_KEYS = ("scale", "lattice.a", "lattice.b", "lattice.c")

# 【量子化桁数】: changepoint 履歴 (rwp_history / lattice_history) へ渡す前に丸める有効桁。
#   robust z は尺度不変のため、ほぼ完全適合の合成データでは物理的に無意味なノイズフロア
#   (Rwp ~1e-9 %, 格子 ~1e-9 Å) の数値ジッタが増幅され偽の changepoint (rwp_jump /
#   lattice_jump) を生む。micro-% / ~1e-4 Å 未満の変動は物理的に無意味なため 6 桁量子化で
#   ノイズフロア発火を抑える。量子化は changepoint 入力に限定し、記録用 (record.rwp /
#   record.phases) は full precision を保持する 🟡 NFR-102。
_HISTORY_QUANTIZE_DIGITS = 6


@dataclass(frozen=True)
class SequentialConfig:
    """逐次エンジン設定 (frozen)。既定は interfaces.py L211-221 の契約に一致。🔵

    【機能概要】: orchestration/継承粒度/後続サイクル数/初回 staged 可否と、下位 3 部品の設定を束ねる。
    【実装方針】: 全フィールド既定値付き frozen dataclass。下位 config は frozen ゆえ共有安全な直接既定。
    🔵 信頼性レベル: interfaces.py L211-221 に直接依拠 (既定値の一部は 🟡: seq_max_cycles / first_frame_staged)。
    """

    orchestration: Literal["independent", "native"] = "independent"  # native は未実装 🔵 REQ-105
    inherit: Literal["phases", "lattice_only"] = "phases"  # warm start 継承対象 🔵 FR-301
    seq_max_cycles: int = 10  # 後続フレームの精密化サイクル 🟡 D2
    first_frame_staged: bool = True  # 初回フレームの staged フル確立 🟡 D2
    changepoint: ChangepointConfig = ChangepointConfig()  # 🔵
    lifecycle: LifecycleConfig = LifecycleConfig()  # 🔵
    search: SearchConfig = SearchConfig()  # 局所木探索設定 🔵 REQ-101


@dataclass(frozen=True)
class SequentialResult:
    """シーケンシャル解析の出力 (frozen・非破壊)。🔵 interfaces.py L224-234

    【機能概要】: トラジェクトリ・採択構成系譜・局所探索結果・初回確立レポート・台帳/スナップショット
      実体・警告を保持する不変の結果契約。
    🔵 信頼性レベル: interfaces.py L224-234 に直接依拠 (first_frame_report のみ 🟡: D2)。
    """

    trajectory: Trajectory
    hypotheses: Mapping[str, Hypothesis]  # 採択構成の系譜 (frame_range 付き) 🔵
    search_results: Mapping[int, SearchResult]  # changepoint フレームの局所探索結果 (key=frame_index) 🔵
    first_frame_report: RefinementReport | None  # 🟡 D2
    ledger: Ledger  # 全操作を理由付き記録 (adopt/reject 含む) 🔵
    snapshots: SnapshotStore  # スナップショットストア実体 🔵
    warnings: tuple[str, ...] = ()  # 失敗フレーム等の警告 (既定 空) 🔵


@dataclass(frozen=True)
class _FrameRefinement:
    """1 フレーム精密化の内部結果束 (run のフェーズ分解用・非公開)。🔵 D2

    【機能概要】: frame0 staged / 後続 direct のどちらの経路でも同一形に正規化した 1 フレームの
      精密化出力を保持し、run 本体のループを短く保つ。
    【設計方針】: staged 経路のみ staged_report を、後続 direct 経路のみ direct_result を持つ
      (もう一方は None)。run はこの識別で first_frame_report 設定と evidence 比較源を選ぶ。
    """

    phases: tuple[PhaseInstance, ...]  # 精密化後の相構成
    metrics: RefinementMetrics  # フレーム指標 (系譜登録・evidence 用)
    rwp_raw: float  # 非有限判定前の生 Rwp
    chi2_raw: float  # 非有限判定前の生 chi2
    direct_result: RefinementResult | None  # 後続 direct のみ非 None (evidence 比較源)
    staged_report: RefinementReport | None  # frame0 staged のみ非 None (first_frame_report 源)


class SequentialEngine:
    """時系列逐次精密化エンジン (D1 オンライン単一パス)。🔵 FR-301〜306

    frame0 は ``StagedRefinementEngine`` フル確立 → 後続は直近成功フレーム warm start + direct refine →
    フレーム指標蓄積 → ``detect_changepoint`` → 発火時のみ ``HypothesisTreeSearch`` (共有 ledger) →
    evidence 改善時のみ採択 → ``LifecycleTracker`` → ``Trajectory`` 組立、を決定論的に行う。
    """

    def __init__(
        self,
        backend: RefinementBackend,
        *,
        candidates: Sequence[PhaseCandidate | PhaseInstance] = (),
        evidence: EvidenceBackend | None = None,
        config: SequentialConfig = SequentialConfig(),
        ledger: Ledger | None = None,
        snapshots: SnapshotStore | None = None,
    ) -> None:
        """逐次エンジンを構築する (キーワード専用の依存を注入可能)。

        【実装方針】: 不変の依存 (backend / 候補プール / evidence / config / ledger / snapshots) を保持する。
          ledger/snapshots は None のとき ``run`` ごとに内部生成する (Persistent 版を注入可能, REQ-012)。
        🔵 信頼性レベル: interfaces.py L237-249 / REQ-012 に依拠。
        @param backend: 精密化バックエンド (refine/simulate)。
        @param candidates: 局所木探索の候補プール (REQ-101)。
        @param evidence: evidence backend。None のとき既定 BICBackend。
        @param config: 逐次エンジン設定。
        @param ledger: 追記専用台帳。None のとき内部生成。
        @param snapshots: スナップショットストア。None のとき内部生成。
        """
        # 【依存束ね】: 探索・精密化・採択で参照する不変依存を保持する 🔵
        self._backend = backend
        self._candidates: tuple[PhaseCandidate | PhaseInstance, ...] = tuple(candidates)
        # 【既定 evidence】: 未指定なら BIC 一次評価 (小さいほど良) を採用する 🔵 REQ-004
        self._evidence: EvidenceBackend = evidence if evidence is not None else BICBackend()
        self._config = config
        self._ledger = ledger
        self._snapshots = snapshots

    # ---- 公開 API ------------------------------------------------------

    def run(
        self, series: FrameSeries, initial_phases: Sequence[PhaseInstance]
    ) -> SequentialResult:
        """フレーム列を単一パスで逐次解析し ``SequentialResult`` を返す。🔵 REQ-001

        【機能概要】: frame0 staged 確立 → 後続 warm start direct refine → changepoint 検出 →
          発火時のみ局所木探索 → evidence 改善時のみ採択 → FrameRecord/lifecycle → Trajectory 組立。
        【テスト対応】: tests/test_sequential_engine.py の 18 ケース (SE-N/E/B 系)。
        🔵 信頼性レベル: dataflow.md 全体フロー / architecture.md D1〜D3 に直接依拠。
        @param series: 共通 2θ グリッド + (n_frames, n_points) 強度行列 + 軸値/channels。
        @param initial_phases: frame 0 の初期相構成 (staged 確立の入力)。
        @returns: SequentialResult (空 series でも例外化せず空値へ縮退)。
        """
        config = self._config
        # 【native 早期拒否】: 協調精密化は M-later スコープ。副作用前に明示的に未実装を通知する 🔵 REQ-105
        if config.orchestration == "native":
            raise NotImplementedError(
                "orchestration='native' (協調精密化) は未実装です (REQ-105 / FR-302 は M-later)。"
            )

        # 【台帳/スナップショットの確保】: 注入があればそれを、無ければ内部生成し監査一貫性のため共有する 🔵
        ledger = self._ledger if self._ledger is not None else Ledger()
        snapshots = (
            self._snapshots if self._snapshots is not None else SnapshotStore(ledger=ledger)
        )

        two_theta = np.asarray(series.two_theta, dtype=float)
        n_frames = series.n_frames

        # 【逐次状態】: 直近成功フレームの確定 phases (warm start 源) と履歴/系譜を保持する 🔵
        tracker = LifecycleTracker(config=config.lifecycle)
        records: list[FrameRecord] = []
        search_results: dict[int, SearchResult] = {}
        warnings: list[str] = []
        rwp_history: list[float] = []  # 成功フレームのみ (非有限を robust z に渡さない) 🔵
        lattice_history: list[dict[str, float]] = []  # 主相 (phases[0]) の格子 a/b/c 🔵
        segments: list[tuple[str, tuple[PhaseInstance, ...], RefinementMetrics | None, int]] = []
        first_frame_report: RefinementReport | None = None
        warm_phases: tuple[PhaseInstance, ...] | None = None  # 直近成功フレームの確定 phases
        config_counter = 0  # 系譜 ID (cfg-XXXX) の決定論採番カウンタ

        for i in range(n_frames):
            intensity_i = np.asarray(series.intensities[i], dtype=float)
            axis_value = series.axis_values[i] if series.axis_values else float(i)
            temperature = self._temperature_for(series, i)

            # 【frame 精密化 (D2 の 2 段構え)】: frame0 staged フル確立 / 後続 warm start direct を
            #   ヘルパへ委譲し、両経路を同一形 (_FrameRefinement) に正規化する 🔵
            fr = self._refine_frame(
                i, tuple(initial_phases), warm_phases, two_theta, intensity_i, ledger, snapshots
            )
            refined = fr.phases
            frame_metrics = fr.metrics
            rwp_raw = fr.rwp_raw
            chi2_raw = fr.chi2_raw
            direct_result = fr.direct_result
            # 【初回確立レポート】: frame0 staged 経路でのみ返る report を出力契約用に保持する 🔵
            if fr.staged_report is not None:
                first_frame_report = fr.staged_report

            # 【失敗フレームの継続 (EDGE-002)】: 非有限は例外化せず None 化して直近成功から継続する 🔵
            if not (math.isfinite(chi2_raw) and math.isfinite(rwp_raw)):
                warnings.append(
                    f"frame {i}: 精密化に失敗しました (非有限 chi2)。直近成功フレームから継続します。"
                )
                carried = warm_phases if warm_phases is not None else ()
                record = FrameRecord(
                    frame_index=i,
                    axis_value=axis_value,
                    temperature=temperature,
                    phases=carried,
                    rwp=None,
                    chi2=None,
                    changepoint=False,
                    changepoint_reasons=(),
                    refine_failed=True,
                )
                records.append(record)
                tracker.observe(i, sorted(self._refs(carried)))
                # warm_phases / history は更新しない (失敗フレームを warm start に採らない) 🔵
                continue

            # 【成功フレーム】: 現行モデルとフレーム指標を確定し履歴へ蓄積する 🔵
            current_phases = refined
            new_unmatched = self._count_unmatched(current_phases, two_theta, intensity_i)
            # 【Rwp 量子化】: ノイズフロア発火抑止のため履歴へは量子化値を渡す (_HISTORY_QUANTIZE_DIGITS
            #   の rationale 参照)。記録用 record.rwp は full precision を保持する 🟡 NFR-102
            rwp_history.append(self._quantize_history(rwp_raw))
            lattice_history.append(self._lattice_map(current_phases))

            # 【系譜の初期セグメント】: 最初の成功フレームで確立構成を系譜へ登録する 🔵
            if not segments:
                segments.append((f"cfg-{config_counter:04d}", current_phases, frame_metrics, i))
                config_counter += 1

            # 【changepoint 検出】: 直近窓のロバスト統計に対する複合指標逸脱を純関数で評価する 🔵 FR-303
            signal = detect_changepoint(
                rwp_history, lattice_history, new_unmatched, config=config.changepoint
            )
            changepoint = signal.triggered
            reasons = signal.reasons
            record_phases = current_phases
            record_rwp: float | None = rwp_raw
            record_chi2: float | None = chi2_raw

            if changepoint:
                # 【局所木探索 (D3)】: 現行相 + 候補プールで共有 ledger 探索を起動する 🔵 REQ-101
                searcher = HypothesisTreeSearch(
                    self._backend,
                    evidence=self._evidence,
                    config=config.search,
                    ledger=ledger,
                    snapshots=snapshots,
                )
                sr = searcher.search(
                    two_theta,
                    intensity_i,
                    list(current_phases) + list(self._candidates),
                )
                search_results[i] = sr

                # 【採択判定 (D3)】: 相集合が現行と異なり evidence 改善時のみ採択、そうでなければ棄却 🔵
                adopted, new_phases, new_metrics = self._decide(sr, current_phases, direct_result)
                if adopted:
                    from_refs = sorted(self._refs(current_phases))
                    to_refs = sorted(self._refs(new_phases))
                    ledger.append(
                        "adopt",
                        {"frame": i, "from": from_refs, "to": to_refs},
                    )
                    current_phases = new_phases
                    record_phases = new_phases
                    record_rwp = self._num_or_none(new_metrics.rwp) if new_metrics else rwp_raw
                    record_chi2 = self._num_or_none(new_metrics.chi2) if new_metrics else chi2_raw
                    # 【系譜更新】: 新構成を採択区間付きで系譜へ追加する (frame_range は末尾で確定) 🔵
                    segments.append(
                        (f"cfg-{config_counter:04d}", new_phases, new_metrics, i)
                    )
                    config_counter += 1
                else:
                    ledger.append(
                        "reject",
                        {"frame": i, "current": sorted(self._refs(current_phases))},
                    )

            record = FrameRecord(
                frame_index=i,
                axis_value=axis_value,
                temperature=temperature,
                phases=record_phases,
                rwp=self._num_or_none(record_rwp),
                chi2=self._num_or_none(record_chi2),
                changepoint=changepoint,
                changepoint_reasons=reasons,
                refine_failed=False,
            )
            records.append(record)
            tracker.observe(i, sorted(self._refs(record_phases)))
            # 【warm start 更新】: 確定した現行構成を直近成功フレームとして引き継ぐ 🔵
            warm_phases = current_phases

        # 【系譜の frame_range 確定】: 各セグメントの終端を次セグメント開始 -1 (末尾は最終フレーム) で埋める 🔵
        hypotheses = self._build_hypotheses(segments, n_frames)

        trajectory = Trajectory(records=tuple(records), lifecycles=tracker.finalize())
        return SequentialResult(
            trajectory=trajectory,
            hypotheses=hypotheses,
            search_results=search_results,
            first_frame_report=first_frame_report,
            ledger=ledger,
            snapshots=snapshots,
            warnings=tuple(warnings),
        )

    # ---- 内部ヘルパ (純関数的) --------------------------------------------

    def _refine_frame(
        self,
        i: int,
        initial_phases: tuple[PhaseInstance, ...],
        warm_phases: tuple[PhaseInstance, ...] | None,
        two_theta: np.ndarray,
        intensity_i: np.ndarray,
        ledger: Ledger,
        snapshots: SnapshotStore,
    ) -> _FrameRefinement:
        """1 フレームを D2 の 2 段構えで精密化し ``_FrameRefinement`` に正規化する。🔵 D2

        【機能概要】: frame0 は ``StagedRefinementEngine`` でフル確立、後続は直近成功フレーム
          warm start + direct refine。両経路の出力を同一形へ揃え run 本体のループを短く保つ。
        【設計方針】: staged 経路は staged_report を、後続経路は direct_result を持たせて
          (もう一方は None) run 側の first_frame_report 設定と evidence 比較源選択を単純化する。
        🔵 信頼性レベル: dataflow.md 後続フレーム / architecture.md D2 に依拠。
        @param i: フレーム index (0 が初回)。
        @param warm_phases: 直近成功フレームの確定 phases (None のとき initial_phases を用いる)。
        @returns: 精密化経路に依らず正規化された 1 フレーム分の精密化結果束。
        """
        config = self._config
        if i == 0 and config.first_frame_staged:
            # 【frame0 staged 確立】: 初期相構成をフル段階解放で確立する (D2) 🔵
            report = StagedRefinementEngine(self._backend, snapshots, ledger).run(
                initial_phases, two_theta, intensity_i
            )
            return _FrameRefinement(
                phases=report.final_phases,
                metrics=report.metrics,
                rwp_raw=float(report.metrics.rwp),
                chi2_raw=float(report.metrics.chi2),
                direct_result=None,
                staged_report=report,
            )
        # 【warm start】: 直近成功フレームの phases を継承 (inherit に従う)。frame0 は initial 直用 🔵
        base = warm_phases if warm_phases is not None else initial_phases
        ws = base if i == 0 else self._warm_start(base, config.inherit)
        direct = self._direct_refine(ws, two_theta, intensity_i)
        return _FrameRefinement(
            phases=direct.phases,
            metrics=self._metrics_from_result(direct),
            rwp_raw=float(direct.rwp),
            chi2_raw=float(direct.chi2),
            direct_result=direct,
            staged_report=None,
        )

    def _direct_refine(
        self, phases: tuple[PhaseInstance, ...], two_theta: np.ndarray, intensity: np.ndarray
    ) -> RefinementResult:
        """後続フレームの direct refine (scale + 格子 a/b/c、max_cycles=seq_max_cycles)。🔵 D2

        【実装方針】: 全相の探索キーのみを解放した RefinementModel を組み、backend.refine を直呼びする。
          StagedRefinementEngine を経由しないため計算量を抑える (P5)。
        🔵 信頼性レベル: dataflow.md 後続フレーム / note.md §3.1 に依拠。
        """
        # 【探索モード free_params】: 全相の scale+格子 a/b/c を解放する (tree.py と同種) 🔵
        free = frozenset(
            param_name(pos, key) for pos in range(len(phases)) for key in _EXPLORE_KEYS
        )
        model = RefinementModel(
            phases=phases, free_params=free, two_theta=two_theta, intensity=intensity
        )
        # 【サイクル数伝播】: 後続フレームは seq_max_cycles を伝播 (frame0 staged=20 / 探索=5 と識別可能) 🔵
        return self._backend.refine(model, max_cycles=self._config.seq_max_cycles)

    def _warm_start(
        self, phases: tuple[PhaseInstance, ...], inherit: str
    ) -> tuple[PhaseInstance, ...]:
        """warm start 継承粒度に応じて前フレーム出力を次フレーム入力へ写像する。🔵 FR-301

        【実装方針】: "phases" は相集合ごと丸ごと継承。"lattice_only" は格子のみ継承し scale 等を
          初期値 (1.0) へリセットする (継承粒度の切替, TC-101-03) 🟡。
        🔵 信頼性レベル: FR-301 / note.md §3.1 に依拠 (lattice_only セマンティクスは 🟡)。
        """
        if inherit == "lattice_only":
            # 【格子のみ継承】: 前フレーム格子を引き継ぎ、scale 等は初期値 1.0 へリセットする 🟡 TC-101-03
            return tuple(
                PhaseInstance(phase_ref=p.phase_ref, lattice=p.lattice, scale=1.0)
                for p in phases
            )
        # 【相集合ごと継承】: 既定は前フレーム出力をそのまま次フレーム入力にする (warm start) 🔵
        return phases

    def _count_unmatched(
        self, phases: tuple[PhaseInstance, ...], two_theta: np.ndarray, intensity: np.ndarray
    ) -> int:
        """現行モデルで説明できない観測ピーク数を求める (changepoint の new_peaks 指標)。🔵

        【実装方針】: 観測ピークを検出し、各相を simulate→find_peaks→match_score で突き合わせ、
          unmatched_peaks でどの相でも説明できない観測ピークを集約して件数を返す (tree.py 踏襲)。
        🔵 信頼性レベル: note.md §3.2 (matcher で算出) / architecture.md 複合指標に依拠。
        """
        search_cfg = self._config.search
        observed = find_peaks(
            two_theta, intensity, min_height_frac=search_cfg.min_peak_height_frac
        )
        # 【空縮退】: 観測ピークが無ければ未マッチも 0 (フラットパターン) 🔵
        if not observed:
            return 0
        match_results = []
        for idx, phase in enumerate(phases):
            calc = self._backend.simulate([phase], two_theta)
            cpeaks = find_peaks(
                two_theta, calc, min_height_frac=search_cfg.min_peak_height_frac
            )
            match_results.append(
                match_score(
                    cpeaks, observed, tol_deg=search_cfg.match_tol_deg, candidate_index=idx
                )
            )
        report = unmatched_peaks(match_results, observed)
        return len(report.unmatched_observed)

    def _decide(
        self,
        sr: SearchResult,
        current_phases: tuple[PhaseInstance, ...],
        current_result: RefinementResult | None,
    ) -> tuple[bool, tuple[PhaseInstance, ...], RefinementMetrics | None]:
        """局所探索の最良仮説を採否判定する (D3: 相集合が異なり evidence 改善時のみ採択)。🔵

        【実装方針】: ranked[0] の相集合が現行と同じなら非採択。異なる場合のみ evidence (BIC, 小さいほど良)
          を現行モデル (direct refine 結果) と比較し、改善 (best < current) 時のみ採択する。境界 (同値) は
          非改善=現行維持とする。
        🔵 信頼性レベル: architecture.md D3 / note.md §3.3 (evidence 改善判定) に依拠。
        @returns: (採択したか, 採択後 phases, 採択後 metrics)。
        """
        # 【空探索の非採択】: 候補ゼロ等で ranked が空なら現行維持 🔵
        if not sr.ranked:
            return False, current_phases, None
        best = sr.ranked[0].hypothesis
        # 【相集合比較】: 現行と同集合なら (改善しても) 新相追加が無いため非採択 🔵
        if self._refs(best.phases) == self._refs(current_phases):
            return False, current_phases, None
        # 【現行 evidence】: direct refine 結果から現行構成の BIC を算出する (同一 backend で公平比較) 🔵
        if current_result is None or best.metrics is None:
            return False, current_phases, None
        current_metrics = self._metrics_from_result(current_result)
        current_ev = self._evidence.score(current_metrics).value
        best_ev = self._evidence.score(best.metrics).value
        # 【改善判定】: BIC は小さいほど良い。厳密改善 (best < current) 時のみ採択 🔵
        if best_ev < current_ev:
            return True, best.phases, best.metrics
        return False, current_phases, None

    def _build_hypotheses(
        self,
        segments: Sequence[tuple[str, tuple[PhaseInstance, ...], RefinementMetrics | None, int]],
        n_frames: int,
    ) -> dict[str, Hypothesis]:
        """採択構成セグメント列を frame_range 付き Hypothesis 系譜へ確定する。🔵 FR-306

        【実装方針】: 各セグメントの終端を「次セグメント開始 -1」、末尾は最終フレーム index とする。
          ID は生成順 (cfg-XXXX) で決定論。
        🔵 信頼性レベル: interfaces.py L229 (採択構成の系譜) / dataflow.md データ整合性に依拠。
        """
        hypotheses: dict[str, Hypothesis] = {}
        for k, (sid, phases, metrics, start) in enumerate(segments):
            end = segments[k + 1][3] - 1 if k + 1 < len(segments) else n_frames - 1
            hypotheses[sid] = Hypothesis(
                id=sid, phases=phases, metrics=metrics, frame_range=(start, end)
            )
        return hypotheses

    @staticmethod
    def _temperature_for(series: FrameSeries, frame_index: int) -> float | None:
        """温度チャネルがあれば当該フレームの温度値を返す (欠損/不在は None)。🔵 REQ-006"""
        # 【温度チャネル探索】: kind=="temperature" の最初のチャネルの同期値を採る (欠損は None) 🔵
        for channel in series.channels:
            if channel.kind == "temperature":
                return channel.value_for(frame_index)
        return None

    @staticmethod
    def _metrics_from_result(result: RefinementResult) -> RefinementMetrics:
        """RefinementResult から RefinementMetrics を組む (gof = sqrt(chi2 / dof))。🔵"""
        # 【GoF 変換】: staged.py _gof / tree.py と同式で dof の下限を 1 に留める 🔵
        dof = max(result.n_obs - result.n_params, 1)
        gof = math.sqrt(result.chi2 / dof) if math.isfinite(result.chi2) else float("inf")
        return RefinementMetrics(
            rwp=result.rwp,
            gof=gof,
            chi2=result.chi2,
            n_obs=result.n_obs,
            n_params=result.n_params,
        )

    @staticmethod
    def _quantize_history(value: float) -> float:
        """changepoint 履歴へ渡す値をノイズフロア量子化する (``_HISTORY_QUANTIZE_DIGITS`` 桁)。🟡 NFR-102

        【ヘルパ関数】: rwp_history / lattice_history 双方の量子化を一元化し、量子化桁と
          rationale を ``_HISTORY_QUANTIZE_DIGITS`` の 1 箇所に集約する (DRY)。
        """
        return round(float(value), _HISTORY_QUANTIZE_DIGITS)

    @classmethod
    def _lattice_map(cls, phases: tuple[PhaseInstance, ...]) -> dict[str, float]:
        """主相 (phases[0]) の格子 a/b/c を changepoint 用のマッピングにする (量子化済)。🔵

        【量子化】: フレーム間差分の robust z が尺度不変ゆえ、完全適合の合成データでは LM の
          ~1e-9 Å ジッタが偽の lattice_jump を生む。ノイズフロア発火抑止のため履歴へは量子化値を
          渡す (``_HISTORY_QUANTIZE_DIGITS`` の rationale 参照)。記録用 record.phases は
          full precision を保持する 🟡 NFR-102。
        """
        # 【主相格子】: フレーム間差分の robust z 対象。相なしは空 dict 🔵
        if not phases:
            return {}
        lat = phases[0].lattice
        return {axis: cls._quantize_history(getattr(lat, axis)) for axis in ("a", "b", "c")}

    @staticmethod
    def _refs(phases: Sequence[PhaseInstance]) -> set[str]:
        """相集合 (phase_ref の集合) を返す。🔵"""
        return {p.phase_ref for p in phases}

    @staticmethod
    def _num_or_none(value: float | None) -> float | None:
        """非有限 (inf/-inf/NaN) / None を None に、有限値は float に写像する (非有限を漏らさない)。🔵"""
        # 【非有限縮退】: FrameRecord / CSV / 下流へ inf/nan を漏らさない (M1 教訓) 🔵
        if value is None:
            return None
        v = float(value)
        return v if math.isfinite(v) else None
