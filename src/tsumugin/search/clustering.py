"""相候補クラスタリング + FoM 代表選出 + Jenks natural breaks (FR-114 / FR-116)。

候補相のピーク位置集合を ``bin_width_deg`` で bin 化し、Jaccard 類似 |A∩B|/|A∪B| が
``similarity_threshold`` 以上の候補対を union-find で同一クラスタに結合する。各クラスタ内で
FoM = 1/((1-fit)+ΔU) が最大の候補を代表に選び (REQ-103 / FR-114)、代表以外は代替解として
``members`` に保持し削除しない (P2 / NFR-101 非破壊性)。加えて探索完了後の良好解抽出向けに
1 次元 Jenks natural breaks の境界値を DP で返す ``jenks_breaks`` を提供する (REQ-104 / FR-116)。

numpy コアのみ依存 (scipy・jenkspy・scikit-learn・GSAS-II 非依存)。乱数を使わず同一入力に
ビット同一の出力を返す (REQ-403 / NFR-102 決定論)。ドメイン的縮退 (空入力・全同一構造・
空ピーク集合・FoM 分母ゼロ) は例外化せず縮退値へ一元化する (M0 規約)。公開戻り値は素の
``tuple`` / ``int`` / ``float`` で numpy スカラーを露出しない。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..model import PhaseInstance
from .peaks import Peak


@dataclass(frozen=True)
class PhaseCandidate:
    """候補相 + 探索メタ。契約は interfaces.py L103-109。🔵 §4 / FR-114"""

    phase: PhaseInstance  # 候補相インスタンス 🔵
    delta_u: float = 0.0  # hull エネルギー ΔU (eV/atom)。M1 では常に 0 🟡
    label: str | None = None  # 探索メタラベル 🟡


@dataclass(frozen=True)
class ClusterResult:
    """等構造クラスタ。契約は interfaces.py L112-118。🔵 FR-114"""

    representative: int  # 代表候補 index (FoM 最大、同点は index 小優先) 🔵
    members: tuple[int, ...]  # クラスタ全 index (昇順)。代替解も保持し削除しない (REQ-103) 🔵


def _bins(peaks: Sequence[Peak], bin_width_deg: float) -> frozenset[int]:
    """ピーク位置集合を離散 bin index の集合へ変換する。

    【機能概要】: 各ピークの 2θ 位置を ``bin_width_deg`` 幅で丸め、同一 bin に落ちる
      ほぼ同一位置のピークを 1 要素に畳んだ集合を返す (Jaccard 比較の単位)。
    【実装方針】: ``round(position / bin_width_deg)`` で最近傍 bin へ量子化する。丸めにより
      境界付近の微小差 (例 30.00 と 29.98) が同一 bin に落ち等構造が検出できる。🟡
    🟡 信頼性レベル: bin 化方針は requirements §2.2 に依拠、丸め方式は TC-N01 較正。

    Args:
        peaks: 候補相のピーク列 (空可)。位置は 2θ (度)。
        bin_width_deg: 離散化幅 (度)。正値を想定。

    Returns:
        bin index (素の int) の不変集合。空ピーク列なら空集合。
    """
    # 【bin 量子化】: 位置を bin 幅で割って四捨五入し、微小差を吸収した hashable な int キーへ 🟡
    width = float(bin_width_deg)
    return frozenset(int(round(float(p.position) / width)) for p in peaks)


def _jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    """2 つの bin 集合の Jaccard 類似 |A∩B|/|A∪B| を返す。

    【機能概要】: 共有 bin 数を合併 bin 数で割った類似度 [0,1] を計算する。
    【実装方針】: 合併が空 (両集合空) の 0/0 縮退は 0.0 (非類似) に倒し ZeroDivisionError を防ぐ。
    🔵 信頼性レベル: Jaccard 定義は requirements §1、0/0 縮退は §3 に依拠 (空 vs 空非類似は 🟡)。

    Args:
        a: 候補 A の bin 集合。
        b: 候補 B の bin 集合。

    Returns:
        Jaccard 類似 (素の float)。合併が空なら 0.0 に縮退。
    """
    # 【合併ガード】: |A∪B|=0 (両空) は 0/0 になるため 0.0 (非類似) へ縮退 (非例外化) 🟡
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def _fom(fit: float, delta_u: float) -> float:
    """FoM = 1/((1-fit)+ΔU) を計算する (FR-114 / architecture.md D4)。

    【機能概要】: fit が高く ΔU が小さいほど大きくなる代表選出指標を返す。
    【実装方針】: 分母 (1-fit)+ΔU が 0 以下 (fit=1.0,ΔU=0.0 等) のゼロ除算は
      ``float("inf")`` (最大 FoM) へ縮退させ ZeroDivisionError を防ぐ。🔵
    🔵 信頼性レベル: FoM 式は architecture.md D4 L108-114、分母ゼロガードは note.md §6 に依拠。

    Args:
        fit: マッチングスコア ([0,1] 想定)。
        delta_u: hull エネルギー ΔU (>=0 想定)。

    Returns:
        FoM (素の float)。分母が 0 以下なら ``float("inf")``。
    """
    # 【分母ゼロガード】: fit=1.0 かつ ΔU=0.0 で分母 0 → inf を最大 FoM として代表選出に整合 🔵
    denominator = (1.0 - float(fit)) + float(delta_u)
    if denominator <= 0.0:
        return float("inf")
    return 1.0 / denominator


class _UnionFind:
    """union-find (素集合データ構造)。決定論のため根は常に index 小へ寄せる。

    【機能概要】: 候補 index を同一クラスタへ結合し、代表根を index 昇順で正規化する。
    【実装方針】: union 時に小さい index を根に固定することで、結合順に依存しない一意な
      クラスタ分割を得る (REQ-403 決定論)。経路圧縮で find を平坦化する。🔵
    🔵 信頼性レベル: 決定論の入力順非依存は requirements §3 に依拠。
    """

    def __init__(self, size: int) -> None:
        # 【親配列初期化】: 各要素は自分自身を根とする単独集合から開始 🔵
        self._parent = list(range(size))

    def find(self, x: int) -> int:
        # 【根の探索】: 親を辿り、自分自身を親とするノード (根) に到達するまで登る 🔵
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # 【経路圧縮】: 辿った各ノードを根へ直付けし、以降の find を平坦化して高速化する 🔵
        while self._parent[x] != root:
            next_node = self._parent[x]
            self._parent[x] = root
            x = next_node
        return root

    def union(self, a: int, b: int) -> None:
        # 【根の正規化】: 2 根のうち小さい index を親に固定し、結合順非依存の決定論を確保 🔵
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        low, high = (ra, rb) if ra < rb else (rb, ra)
        self._parent[high] = low


def jaccard_clusters(
    peak_sets: Sequence[Sequence[Peak]],
    fits: Sequence[float],
    delta_us: Sequence[float],
    *,
    similarity_threshold: float = 0.85,
    bin_width_deg: float = 0.2,
) -> tuple[ClusterResult, ...]:
    """ピーク位置の Jaccard 類似で候補をクラスタし FoM で代表選出する (REQ-103 / FR-114)。

    【機能概要】: 各候補のピーク位置を ``bin_width_deg`` で bin 化し、Jaccard 類似が
      ``similarity_threshold`` 以上の候補対を union-find で 1 クラスタへ結合する。各クラスタ内で
      FoM=1/((1-fit)+ΔU) が最大の候補を代表とし、代表以外も ``members`` に昇順で保持する。
    【実装方針】: 全対 (i<j) の Jaccard を評価し閾値以上を union。クラスタは代表 index 昇順、
      members は index 昇順に正規化し、FoM 同点は index 小優先で代表を固定して決定論を守る。
      入力を破壊せず (NFR-101)、空入力・空ピーク集合・分母ゼロは例外化せず縮退させる。
    【テスト対応】: tests/test_clustering.py の TC-N01〜07 / TC-E01〜03 / TC-B01〜05 を通す。
    🔵 信頼性レベル: 契約・FoM 式・正規化・決定論は interfaces.py / REQ-103/403 に依拠
      (閾値 0.85・bin 幅 0.2・同点 index 小優先は requirements §3 の妥当な推測 🟡)。

    Args:
        peak_sets: 候補 index 順の各候補相ピーク列 (各要素は空可)。
        fits: 各候補のマッチングスコア ([0,1] 想定、``peak_sets`` と同長)。
        delta_us: 各候補の ΔU (>=0 想定、M1 既定 0.0、``peak_sets`` と同長)。
        similarity_threshold: 同一クラスタ判定の Jaccard 閾値 (キーワード専用, 既定 0.85)。
            ``jaccard >= similarity_threshold`` (閉区間) で結合する。
        bin_width_deg: ピーク位置の離散化幅 (度, キーワード専用, 既定 0.2)。

    Returns:
        ``tuple[ClusterResult, ...]`` を代表 index 昇順で返す。空入力は空タプル ``()``。
    """
    # 【空入力の縮退】: 候補ゼロは空タプルへ倒し IndexError を出さない (M0 規約) 🔵
    n = len(peak_sets)
    if n == 0:
        return ()

    # 【bin 化 (非破壊)】: 各候補のピーク位置集合を bin index 集合へ量子化する (入力は不変) 🔵
    bin_sets = [_bins(peaks, bin_width_deg) for peaks in peak_sets]

    # 【FoM 事前計算】: 各候補の代表適性 FoM を一度だけ求め、代表選出で再利用する 🔵
    fom_values = [_fom(fits[i], delta_us[i]) for i in range(n)]

    # 【Jaccard union-find】: 全対 (i<j) を評価し閾値以上の対を同一クラスタへ結合する 🔵
    threshold = float(similarity_threshold)
    union_find = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if _jaccard(bin_sets[i], bin_sets[j]) >= threshold:
                union_find.union(i, j)

    # 【クラスタ集約】: 根 index ごとにメンバー index を集める。dict の挿入順は昇順 index で安定 🔵
    clusters: dict[int, list[int]] = {}
    for index in range(n):
        clusters.setdefault(union_find.find(index), []).append(index)

    # 【代表選出 + 正規化】: 各クラスタで FoM 最大 (同点 index 小優先) を代表とし、members を昇順化 🔵
    results: list[ClusterResult] = []
    for members in clusters.values():
        ordered_members = sorted(members)  # 【昇順化】: members を index 昇順に正規化 🔵
        # 【FoM 最大選出】: max は同点時に最初の要素を返すため、index 昇順の members では
        #   FoM 同点が自動的に index 小優先へ確定する (決定論・完了条件6) 🔵
        representative = max(ordered_members, key=lambda member: fom_values[member])
        results.append(
            ClusterResult(representative=int(representative), members=tuple(ordered_members))
        )

    # 【出力正規化】: クラスタを代表 index 昇順に並べ、入力順非依存のビット同一出力にする 🔵
    results.sort(key=lambda cluster: cluster.representative)
    return tuple(results)


def _segment_sdcm(prefix_sum: np.ndarray, prefix_sq: np.ndarray, start: int, stop: int) -> float:
    """ソート済み配列の区間 [start, stop) の群内二乗偏差和 (SDCM) を返す。

    【機能概要】: 区間内の平均からの二乗偏差和 SDCM = Σx² - (Σx)²/m を prefix sum で O(1) 算出。
    【実装方針】: 累積和・累積二乗和の差分で区間統計を求め、Jenks DP の各セル評価を定数時間化。🔵
    🔵 信頼性レベル: SDCM 定義は requirements §2.4 (Jenks) に依拠。

    Args:
        prefix_sum: 累積和 (長さ n+1、prefix_sum[0]=0)。
        prefix_sq: 累積二乗和 (長さ n+1、prefix_sq[0]=0)。
        start: 区間開始 index (含む)。
        stop: 区間終了 index (含まない)。

    Returns:
        区間の SDCM (素の float)。
    """
    # 【区間統計】: 累積差分で区間の要素数・総和・二乗和を取得 🔵
    count = stop - start
    total = prefix_sum[stop] - prefix_sum[start]
    total_sq = prefix_sq[stop] - prefix_sq[start]
    # 【SDCM】: Σx² - (Σx)²/m。単一要素・全同値では 0 に縮退 (分散 0) 🔵
    return float(total_sq - (total * total) / count)


def jenks_breaks(values: Sequence[float], *, n_classes: int = 2) -> tuple[float, ...]:
    """1 次元 Jenks natural breaks の境界値を DP で返す (REQ-104 / FR-116)。

    【機能概要】: ``values`` を昇順ソートし、``n_classes`` 群への分割で群内二乗偏差和 (SDCM)
      合計を最小化する連続分割を DP で求め、隣接群の間の中点を境界値として返す。
    【実装方針】: prefix sum で区間 SDCM を O(1) 化し、O(n_classes·n²) の DP で最適分割を計算する。
      外部ライブラリ (jenkspy) を追加せず numpy コアで自前実装。境界は「下群の最大」と
      「上群の最小」の中点とし、群内を割らない一意な区切りを返す (決定論)。空/単一/過大群数は
      例外化せず自然な境界 (空 or 群数-1 個) へ縮退する。
    【テスト対応】: tests/test_clustering.py の TC-N05 / TC-E04-05 / TC-B06 を通す。
    🔵 信頼性レベル: アルゴリズム (SDCM 最小化 DP・昇順ソート・numpy 自前) は requirements
      §2.4 に依拠 (境界=中点・縮退返却形は §4.4 の妥当な推測 🟡)。

    Args:
        values: 分割対象の 1 次元数値列 (順不同・空/少数可、例 evidence 値)。
        n_classes: 分割する群数 (キーワード専用, 既定 2)。

    Returns:
        群間の境界値 ``tuple[float, ...]`` (昇順、長さ ``n_classes-1``)。
        空入力・単一群・過大群数は空タプルや縮小した境界へ縮退し例外は投げない。
    """
    # 【昇順ソート (関数内・非破壊)】: 入力順に依存しない決定論を確保する。np.sort はコピーを返す 🔵
    arr = np.sort(np.asarray(values, dtype=float))
    n = int(arr.size)

    # 【縮退ガード】: 要素なし、または有効群数が 1 以下 (境界不要) は空タプルへ縮退 🟡
    classes = min(int(n_classes), n)
    if n == 0 or classes <= 1:
        return ()

    # 【prefix sum】: 区間 SDCM を O(1) で評価するための累積和・累積二乗和 (先頭 0 詰め) 🔵
    prefix_sum = np.concatenate(([0.0], np.cumsum(arr)))
    prefix_sq = np.concatenate(([0.0], np.cumsum(arr * arr)))

    # 【DP 初期化】: dp[c][i] = 先頭 i 要素を c 群へ分けた最小 SDCM。inf で未到達を表す 🔵
    infinity = float("inf")
    dp = [[infinity] * (n + 1) for _ in range(classes + 1)]
    back = [[0] * (n + 1) for _ in range(classes + 1)]
    dp[0][0] = 0.0

    # 【DP 本体】: c 群目の末端群を arr[j:i] とし、dp[c-1][j] + SDCM(j,i) の最小を取る 🔵
    for c in range(1, classes + 1):
        for i in range(c, n + 1):
            best_cost = infinity
            best_split = c - 1
            # 【分割点走査】: 先頭 c-1 群に j 要素を割り当て、残り arr[j:i] を c 群目とする 🔵
            for j in range(c - 1, i):
                if dp[c - 1][j] == infinity:
                    continue
                cost = dp[c - 1][j] + _segment_sdcm(prefix_sum, prefix_sq, j, i)
                if cost < best_cost:
                    best_cost = cost
                    best_split = j
            dp[c][i] = best_cost
            back[c][i] = best_split

    # 【分割点復元】: 末尾から back を辿り各群の開始 index を集める (境界を張る位置) 🔵
    boundaries_idx: list[int] = []
    cursor = n
    for c in range(classes, 1, -1):
        split = back[c][cursor]
        boundaries_idx.append(split)
        cursor = split

    # 【境界値化】: 各分割点 split で「下群の最大 arr[split-1]」と「上群の最小 arr[split]」の中点を採る 🔵
    boundaries_idx.reverse()  # 【昇順化】: 復元は末尾からのため昇順へ反転 🔵
    return tuple(float((arr[split - 1] + arr[split]) / 2.0) for split in boundaries_idx)
