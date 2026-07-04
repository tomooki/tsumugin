"""TASK-0028 multistart/basin — 収束解の basin (吸引域) クラスタリング (FR-232 / 設計 D3)。

マルチスタート精密化で得た複数の収束解を、**正規化パラメータ距離**で union-find
クラスタリングし、各クラスタ (= basin) を ``BasinInfo`` (代表 = chi2 最小解) に畳む純関数を
提供する。単一 basin なら「大域最適の傍証あり」、複数 basin なら多峰性 (別解の存在) を示す。

- ``BasinInfo``: 1 つの basin の要約 (代表解 / 所属 start index 群 / chi2 / evidence)。
- ``cluster_basins(results, *, basin_rel_tol)``: 収束解列を basin へ分割し evidence 昇順で返す。

正規化は「chi2 最小解 (アンカー) を基準に各パラメータを無次元化」し、格子は相対比・scale は
対数比・占有率は差分でベクトル化する。2 解の L∞ 相対距離が ``basin_rel_tol`` **未満** (strict `<`)
なら同一 basin へ連結する。乱数不使用・安定順で決定論 (同一入力にビット同一出力)。

🔵 信頼性レベル: interfaces.py L143-151 (BasinInfo) / architecture.md D3 / REQ-002 に依拠
  (正規化距離式・L∞・strict `<` は tdd-testcases TC-BV01 で較正済 🟡→🔵)。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from tsumugin.backends.base import RefinementResult
from tsumugin.evidence.ic import BICBackend
from tsumugin.model import RefinementMetrics

from ..search.clustering import _UnionFind

# 【0 除算・log 定義域ガード】: 格子/scale が 0 近傍でも例外化しないための下限値 🔵
_TINY = 1e-12

# 【evidence バックエンド】: basin 代表の evidence は BIC で算出 (小さいほど良い / FR-121) 🔵
_BIC = BICBackend()


@dataclass(frozen=True)
class BasinInfo:
    """【機能概要】: 1 つの basin (吸引域) の要約を保持する不変値オブジェクト。

    【実装方針】: interfaces.py L143-151 の 4 フィールドをそのまま frozen dataclass 化。
    代表は chi2 最小解、member_starts は所属 start index の昇順 tuple。
    【テスト対応】: test_basininfo_and_result_are_frozen ほか basin 系 6 件。
    🔵 信頼性レベル: interfaces.py L143-151 / REQ-002 に直接依拠。
    """

    representative: RefinementResult  # 【代表】: クラスタ内 chi2 最小解 (同点は start index 小)
    member_starts: tuple[int, ...]  # 【所属】: この basin に属する start index 群 (昇順)
    chi2: float  # 【適合度】: 代表の chi2
    evidence: float  # 【evidence】: 代表の bic (BICBackend、小さいほど良い)


def _evidence_of(result: RefinementResult) -> float:
    """【機能概要】: 収束解の evidence (BIC) を算出する。

    【実装方針】: RefinementResult の chi2/n_obs/n_params を RefinementMetrics へ詰め替え
    BICBackend.score の value を取る。BIC = chi2 + n_params·ln(max(n_obs,1))。
    🔵 信頼性レベル: evidence/ic.py BICBackend / note §3 に依拠。
    """
    # 【メトリクス詰め替え】: BIC は chi2/n_params/n_obs のみ参照 (rwp/gof は評価に無関与) 🔵
    metrics = RefinementMetrics(
        rwp=result.rwp,
        gof=0.0,
        chi2=result.chi2,
        n_obs=result.n_obs,
        n_params=result.n_params,
    )
    return _BIC.score(metrics).value


def _normalized_vector(result: RefinementResult, anchor: RefinementResult) -> list[float]:
    """【機能概要】: 収束解をアンカー (chi2 最小解) 基準の正規化パラメータベクトルへ変換する。

    【実装方針】: 相ごとに格子 a/b/c は相対比 (value/anchor)、scale は対数比の差分、占有率は
    差分でベクトル化する。2 ベクトルの差分 L∞ が相対距離となり、アンカーの選択でスケールが
    決まる (格子は anchor 値で無次元化)。乱数不使用・入力非破壊 (読み取りのみ)。
    【テスト対応】: TC-BV01 (格子相対距離の strict 境界)。
    🔵 信頼性レベル: architecture.md D3 (正規化パラメータベクトル) / note §6 に依拠 (式は 🟡 較正)。

    @param result: 正規化対象の収束解。
    @param anchor: 基準となる収束解 (chi2 最小解)。相数・相順は result と一致を前提。
    @returns: 無次元化パラメータの float ベクトル。
    """
    vec: list[float] = []
    # 【相ごと展開】: 相数・相順は generate_starts が保存するため zip で対応づく 🔵
    for phase, aphase in zip(result.phases, anchor.phases):
        # 【格子相対比】: a/b/c を anchor の同軸値で割り無次元化 (差分 |v_i-v_j|/anchor が相対距離) 🔵
        for axis in ("a", "b", "c"):
            ref = float(getattr(aphase.lattice, axis))
            denom = ref if abs(ref) > _TINY else _TINY
            vec.append(float(getattr(phase.lattice, axis)) / denom)
        # 【scale 対数比】: log10(scale) - log10(anchor.scale) (差分で anchor が相殺、相対倍率) 🔵
        s = float(phase.scale) if float(phase.scale) > _TINY else _TINY
        a_s = float(aphase.scale) if float(aphase.scale) > _TINY else _TINY
        vec.append(math.log10(s) - math.log10(a_s))
        # 【占有率差分】: 両者の site 和集合を昇順に走査し占有率の絶対差分を成分化 🔵🟡
        keys = sorted(set(phase.occupancies) | set(aphase.occupancies))
        for key in keys:
            vec.append(float(phase.occupancies.get(key, 0.0)) - float(aphase.occupancies.get(key, 0.0)))
    return vec


def _distance(vec_i: list[float], vec_j: list[float]) -> float:
    """【機能概要】: 2 正規化ベクトルの L∞ (最大成分) 相対距離を返す。

    【実装方針】: 成分ごとの絶対差の最大値。空ベクトル (パラメータなし) は距離 0 に縮退。
    🔵 信頼性レベル: note §3「相対距離 (例 L2 or 最大成分)」の最大成分 (L∞) を採用。
    """
    # 【L∞】: 最大成分差を相対距離とする (単一パラメータ差では L2 と一致し境界較正に整合) 🔵
    if not vec_i:
        return 0.0
    return max(abs(x - y) for x, y in zip(vec_i, vec_j))


def cluster_basins(
    results: Sequence[RefinementResult], *, basin_rel_tol: float = 1e-2
) -> tuple[BasinInfo, ...]:
    """【機能概要】: 収束解列を正規化パラメータ距離で basin クラスタし evidence 昇順で返す。

    【実装方針】: chi2 最小解をアンカーに各解を正規化ベクトル化 → 全対 (i<j) の L∞ 相対距離が
    ``basin_rel_tol`` **未満** の対を union-find で連結 → 連結成分ごとに代表 (chi2 最小、同点は
    start index 小) と evidence (BIC) を求め、evidence 昇順 (同点は先頭 member index 小) に整列。
    入力破壊なし・乱数不使用で決定論。空入力は空タプルへ縮退し例外化しない。
    【テスト対応】: basin 系 6 件 (単一/2 群/代表選出/境界 strict/空/単一解)。
    🔵 信頼性レベル: architecture.md D3 / REQ-002 / clustering.py union-find パターンに依拠。

    @param results: 各 start の収束解列 (発散除外後を想定、空可)。
    @param basin_rel_tol: 同一 basin と判定する正規化相対距離の閾値 (strict `<`, 既定 1e-2)。
    @returns: evidence 昇順の ``tuple[BasinInfo, ...]``。空入力は ``()``。
    """
    # 【空入力の縮退】: 収束解ゼロ (全滅後など) は空タプルへ倒し例外を投げない (M0 規約) 🔵
    seq = list(results)
    n = len(seq)
    if n == 0:
        return ()

    # 【アンカー選出】: chi2 最小解 (同点は index 小) を正規化の基準に固定し決定論を確保 🔵
    anchor_index = min(range(n), key=lambda i: (seq[i].chi2, i))
    anchor = seq[anchor_index]

    # 【正規化 (非破壊)】: 各収束解をアンカー基準の無次元ベクトルへ変換 (入力は不変) 🔵
    vectors = [_normalized_vector(result, anchor) for result in seq]

    # 【union-find 連結】: 全対 (i<j) の L∞ 相対距離が tol 未満 (strict `<`) の対を同一 basin へ 🔵
    tol = float(basin_rel_tol)
    union_find = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if _distance(vectors[i], vectors[j]) < tol:
                union_find.union(i, j)

    # 【クラスタ集約】: 根 index ごとに member index を昇順で集める (挿入順 = index 昇順で安定) 🔵
    clusters: dict[int, list[int]] = {}
    for index in range(n):
        clusters.setdefault(union_find.find(index), []).append(index)

    # 【代表選出 + evidence】: 各 basin で chi2 最小 (同点 index 小) を代表とし evidence を算出 🔵
    basins: list[BasinInfo] = []
    for members in clusters.values():
        ordered = sorted(members)  # 【昇順化】: member_starts を index 昇順に正規化 🔵
        rep_index = min(ordered, key=lambda m: (seq[m].chi2, m))
        representative = seq[rep_index]
        basins.append(
            BasinInfo(
                representative=representative,
                member_starts=tuple(ordered),
                chi2=representative.chi2,
                evidence=_evidence_of(representative),
            )
        )

    # 【出力正規化】: evidence 昇順 (同点は先頭 member index 小) でビット同一出力を保証 🔵
    basins.sort(key=lambda basin: (basin.evidence, basin.member_starts[0]))
    return tuple(basins)
