"""TASK-0005 Jaccard クラスタリング + FoM 代表選出 + Jenks の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/search/clustering.py``（未実装）。
`PhaseCandidate` / `ClusterResult` の frozen dataclass、
`jaccard_clusters(peak_sets, fits, delta_us, *, similarity_threshold=0.85, bin_width_deg=0.2)`、
`jenks_breaks(values, *, n_classes=2)` を検証する。

ピーク位置集合を ``bin_width_deg`` で bin 化した Jaccard 類似 |A∩B|/|A∪B| ≥ threshold で
union-find クラスタリングし、各クラスタ内で FoM = 1/((1−fit)+ΔU) 最大の候補を代表に選ぶ純関数。
代表以外は代替解として ``members`` に保持し削除しない (REQ-103 非破壊性)。

書式は `tests/test_pruning.py` / `tests/test_matcher.py` を範とする
（モジュールレベルヘルパ + pytest.approx / 決定論の ``==`` ビット同一検証）。
本タスクは GSAS-II 非依存で、`Peak` リストと fits/delta_us を素の list で直接構築する。
テストケース定義 (19 件: 正常系 7 / 異常系 6 / 境界値 6) に 1:1 対応する。
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.search.peaks import Peak

# 未実装のため、この import が collection 時に失敗し全テストがエラー(=失敗)になる想定。
from tsumugin.search.clustering import (
    ClusterResult,
    PhaseCandidate,
    jaccard_clusters,
    jenks_breaks,
)

# ---------------------------------------------------------------------------
# 共通テストヘルパ・テストデータ（複数ケースで再利用）
# ---------------------------------------------------------------------------


# 【テストデータ準備】: 位置のみ与えて一定 height で Peak 列に包む (height は bin 化に不使用)
def _peaks(positions: list[float], height: float = 1.0) -> list[Peak]:
    return [Peak(position=float(p), height=height) for p in positions]


# 【テストデータ準備】: TC-N06 用の最小 PhaseInstance (test_matcher.py の _phase を踏襲)
def _phase(a: float = 5.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=1.0)


# 【結果検証補助】: クラスタを「メンバー相の位置集合 + 代表相の位置」で識別する署名に変換
# （TC-B04 で入力順に依存しないクラスタ構造の同一性を index 非依存に比較するため）
def _positions(peak_set: list[Peak]) -> tuple[float, ...]:
    return tuple(round(p.position, 6) for p in peak_set)


def _cluster_signatures(peak_sets, result) -> frozenset:
    sigs = set()
    for cluster in result:
        members = frozenset(_positions(peak_sets[i]) for i in cluster.members)
        representative = _positions(peak_sets[cluster.representative])
        sigs.add((members, representative))
    return frozenset(sigs)


# 【共有入力例】: bin_width_deg=0.2 で同一 bin に落ちほぼ同一集合になる 2 候補 (Jaccard≈1.0)
IDENTICAL_A = _peaks([10.00, 20.00, 30.00])
IDENTICAL_B = _peaks([10.05, 20.03, 29.98])
# 【共有入力例】: A/B と全く別の bin に落ちる候補 (Jaccard=0 < 0.85)
DIFFERENT_C = _peaks([15.0, 25.0, 35.0])
# 【共有入力例】: 既知 2 群 (低群 {1,2,3} / 高群 {100,110})。境界は 3〜100 の間
JENKS_TWO_GROUP = [1.0, 2.0, 3.0, 100.0, 110.0]


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_near_identical_peaks_merge_into_one_cluster():
    # 【テスト目的】: ほぼ同一ピークの 2 候補が 1 クラスタに縮約され FoM 最大が代表 (TC-N01/TC-004-01)
    # 【テスト内容】: bin 一致する 2 候補 + fit 差で jaccard_clusters の代表/members を検証
    # 【期待される動作】: len==1, representative=0, members=(0,1)
    # 🔵 信頼性レベル: 受け入れ基準 TC-004-01 / 完了条件1 / requirements §4.1 に直接依拠

    # 【テストデータ準備】: bin 化で同一集合になる 2 候補、index0 の fit が高く FoM 最大=代表
    # 【前提条件確認】: similarity_threshold は既定 0.85、Jaccard≈1.0 で結合
    peak_sets = [IDENTICAL_A, IDENTICAL_B]
    fits = [0.9, 0.6]
    delta_us = [0.0, 0.0]

    # 【実際の処理実行】: bin 化 → 集合化 → Jaccard union-find → FoM 最大を代表選出
    result = jaccard_clusters(peak_sets, fits, delta_us)

    # 【結果検証】: 2 候補が 1 クラスタに縮約され代替解 (index1) が members から欠落しない
    # 【期待値確認】: FoM(0)=1/0.1=10 > FoM(1)=1/0.4=2.5 で index0 が代表
    assert len(result) == 1  # 【確認内容】: 2 候補が 1 クラスタに縮約 🔵
    assert result[0].representative == 0  # 【確認内容】: FoM 最大が代表 🔵
    assert result[0].members == (0, 1)  # 【確認内容】: 全 index を昇順保持 (代替解削除なし) 🔵


def test_different_peaks_form_separate_clusters():
    # 【テスト目的】: Jaccard < threshold の候補対が別クラスタに分かれることを確認 (TC-N02/TC-004-02)
    # 【テスト内容】: bin が全く重ならない 2 候補で単独クラスタ 2 個が返るか検証
    # 【期待される動作】: len==2, 各 members 長 1, 各 representative が自身の index
    # 🔵 信頼性レベル: 受け入れ基準 TC-004-02 / requirements §4.1 に直接依拠

    # 【テストデータ準備】: Jaccard=0 (bin 非重複) の 2 候補
    peak_sets = [IDENTICAL_A, DIFFERENT_C]
    fits = [0.8, 0.7]
    delta_us = [0.0, 0.0]

    # 【実際の処理実行】: 閾値未満は union されず単独クラスタになるはず
    result = jaccard_clusters(peak_sets, fits, delta_us)

    # 【結果検証】: 誤って 1 クラスタに統合しないこと。出力は代表 index 昇順
    assert len(result) == 2  # 【確認内容】: 別クラスタに分割 🔵
    assert result[0].members == (0,)  # 【確認内容】: index0 単独クラスタ 🔵
    assert result[1].members == (1,)  # 【確認内容】: index1 単独クラスタ 🔵
    assert result[0].representative == 0  # 【確認内容】: 各代表が自身 🔵
    assert result[1].representative == 1  # 【確認内容】: 各代表が自身 🔵


def test_large_delta_u_cannot_be_representative():
    # 【テスト目的】: fit 同値でも delta_u 大の候補は FoM が下がり代表にならない (TC-N03/完了条件3)
    # 【テスト内容】: fit を同値に固定し ΔU のみ差をつけ FoM 差の原因を ΔU に限定して検証
    # 【期待される動作】: ΔU=0.0 の index1 が representative
    # 🔵 信頼性レベル: 完了条件3 / FR-114 式 / requirements §4.2 に直接依拠

    # 【テストデータ準備】: fits 同値 [0.8,0.8]、delta_us のみ [0.5,0.0] で差をつける
    peak_sets = [IDENTICAL_A, IDENTICAL_B]
    fits = [0.8, 0.8]
    delta_us = [0.5, 0.0]

    # 【実際の処理実行】: FoM=1/((1−fit)+ΔU) で代表選出
    result = jaccard_clusters(peak_sets, fits, delta_us)

    # 【結果検証】: FoM(0)=1/0.7≈1.43 < FoM(1)=1/0.2=5.0 で ΔU 大の index0 は代表になれない
    assert len(result) == 1  # 【確認内容】: 同一クラスタに縮約 🔵
    assert result[0].representative == 1  # 【確認内容】: ΔU 小の候補が代表 (代表反転) 🔵
    assert result[0].members == (0, 1)  # 【確認内容】: 全 index を昇順保持 🔵


def test_fom_value_matches_formula():
    # 【テスト目的】: FoM の大小が式 1/((1−fit)+ΔU) に一致し代表選出に反映されることを確認 (TC-N04)
    # 【テスト内容】: 手計算で分離する fit で FoM 最大の候補が代表になるか検証
    # 【期待される動作】: FoM(1)=4.0 > FoM(0)=2.0 で index1 が代表
    # 🔵 信頼性レベル: FoM 式 (architecture.md D4 L108-114) に直接依拠

    # 【テストデータ準備】: FoM(0)=1/0.5=2.0, FoM(1)=1/0.25=4.0 に明確分離する fit
    peak_sets = [IDENTICAL_A, IDENTICAL_B]
    fits = [0.5, 0.75]
    delta_us = [0.0, 0.0]

    # 【実際の処理実行】: fit 単調性が代表選出に効くことを検証
    result = jaccard_clusters(peak_sets, fits, delta_us)

    # 【結果検証】: fit 増で FoM 増、index1 が代表
    assert len(result) == 1  # 【確認内容】: 同一クラスタに縮約 🔵
    assert result[0].representative == 1  # 【確認内容】: FoM 最大 (式通り) が代表 🔵
    assert result[0].members == (0, 1)  # 【確認内容】: 全 index を昇順保持 🔵


def test_jenks_breaks_separates_two_known_groups():
    # 【テスト目的】: jenks_breaks が既知 2 群の間に境界値を返すことを確認 (TC-N05/TC-004-03)
    # 【テスト内容】: [1,2,3,100,110] を n_classes=2 で分割し境界が両群の間に入るか検証
    # 【期待される動作】: 境界 b が 3.0 < b <= 100.0 (群内を割らない)
    # 🔵 信頼性レベル: 受け入れ基準 TC-004-03 / requirements §4.3 に直接依拠

    # 【テストデータ準備】: 群内分散が明確に小さい 2 群 (境界が一意に定まる典型入力)
    values = list(JENKS_TWO_GROUP)

    # 【実際の処理実行】: SDCM 最小化 DP で {1,2,3} と {100,110} に分割
    result = jenks_breaks(values, n_classes=2)

    # 【結果検証】: 返り値が素の float タプルで境界が両群の間に入る
    assert isinstance(result, tuple)  # 【確認内容】: 戻り値は tuple 🔵
    assert len(result) == 1  # 【確認内容】: n_classes=2 の境界は 1 個 🔵
    boundary = result[0]
    assert isinstance(boundary, float)  # 【確認内容】: numpy スカラー非露出 (素の float) 🔵
    assert 3.0 < boundary <= 100.0  # 【確認内容】: 境界が低群 (max3) と高群 (min100) の間 🔵


def test_value_objects_frozen_and_defaults():
    # 【テスト目的】: PhaseCandidate の既定値と両 dataclass の frozen 契約を確認 (TC-N06)
    # 【テスト内容】: 既定引数省略の構築と、フィールド再代入で FrozenInstanceError を検証
    # 【期待される動作】: delta_u=0.0, label=None、再代入で dataclasses.FrozenInstanceError
    # 🟡 信頼性レベル: 既定値・型は interfaces.py 🔵 だが frozen 例外検証は妥当な推測 🟡

    # 【テストデータ準備】: 契約 (interfaces.py L103-118) の最小構築
    candidate = PhaseCandidate(phase=_phase())
    cluster = ClusterResult(representative=0, members=(0, 1))

    # 【結果検証】: PhaseCandidate の既定値 (M1 は ΔU=0 / label 無し前提)
    assert candidate.delta_u == 0.0  # 【確認内容】: delta_u 既定 0.0 🔵
    assert candidate.label is None  # 【確認内容】: label 既定 None 🔵
    assert cluster.representative == 0  # 【確認内容】: ClusterResult フィールド保持 🔵
    assert cluster.members == (0, 1)  # 【確認内容】: members フィールド保持 🔵

    # 【結果検証】: 値オブジェクトは不変 (再代入は FrozenInstanceError)
    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.delta_u = 1.0  # 【確認内容】: PhaseCandidate は frozen 🟡
    with pytest.raises(dataclasses.FrozenInstanceError):
        cluster.representative = 1  # 【確認内容】: ClusterResult は frozen 🟡


def test_output_normalized_and_sorted():
    # 【テスト目的】: members 昇順・出力が代表 index 昇順に正規化されることを確認 (TC-N07)
    # 【テスト内容】: 単独 {0} とクラスタ {1,2} が混在する入力で決定論的順序を検証
    # 【期待される動作】: result[0].rep==0, result[1].rep==1, result[1].members==(1,2)
    # 🔵 信頼性レベル: requirements §2.3 正規化規則に依拠 (順序詳細の一部は 🟡)

    # 【テストデータ準備】: C 単独 (index0) と A,B クラスタ (index1,2)、A の FoM が最大
    peak_sets = [DIFFERENT_C, IDENTICAL_A, IDENTICAL_B]
    fits = [0.7, 0.9, 0.6]
    delta_us = [0.0, 0.0, 0.0]

    # 【実際の処理実行】: クラスタ縮約 + 正規化
    result = jaccard_clusters(peak_sets, fits, delta_us)

    # 【結果検証】: members は入力順でなく index 昇順、出力は代表 index 昇順
    assert len(result) == 2  # 【確認内容】: 単独 + クラスタで 2 個 🔵
    assert result[0].representative == 0  # 【確認内容】: C 単独が先頭 (代表 index 昇順) 🔵
    assert result[1].representative == 1  # 【確認内容】: A,B クラスタの代表は FoM 最大の index1 🔵
    assert result[1].members == (1, 2)  # 【確認内容】: members は index 昇順 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（縮退・エラーハンドリング）
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_tuple():
    # 【テスト目的】: 空入力 peak_sets==[] で空タプルに縮退することを確認 (TC-E01)
    # 【テスト内容】: 候補ゼロの空入力で IndexError を出さず () を返すか検証
    # 【期待される動作】: jaccard_clusters([], [], []) == ()、例外を送出しない
    # 🔵 信頼性レベル: M0 規約 / requirements §3・§4.4 に依拠

    # 【実際の処理実行】: 上流の枝刈りで全候補が除外された縮退シナリオ
    result = jaccard_clusters([], [], [])

    # 【結果検証】: 空タプルを空ループで安全に処理できる縮退値
    assert result == ()  # 【確認内容】: 空入力は空タプルに縮退 🔵


def test_fom_zero_denominator_guarded_as_inf():
    # 【テスト目的】: fit=1.0,ΔU=0.0 の FoM 分母ゼロを inf 扱いし例外を出さない (TC-E02)
    # 【テスト内容】: 完全一致候補で ZeroDivisionError を出さず inf 最大 FoM として代表選出を検証
    # 【期待される動作】: 例外なし、result[0].representative==0 (inf は最大 FoM)
    # 🔵 信頼性レベル: note.md §6 / requirements §3 FoM 分母ゼロガードに依拠

    # 【テストデータ準備】: index0 が fit=1.0,ΔU=0.0 で FoM 分母 (1−fit)+ΔU=0
    peak_sets = [IDENTICAL_A, IDENTICAL_B]
    fits = [1.0, 0.9]
    delta_us = [0.0, 0.0]

    # 【実際の処理実行】: ゼロ除算を float("inf") へ縮退させて代表選出
    result = jaccard_clusters(peak_sets, fits, delta_us)

    # 【結果検証】: inf が最大 FoM として代表選出に整合
    assert len(result) == 1  # 【確認内容】: 同一クラスタに縮約 🔵
    assert result[0].representative == 0  # 【確認内容】: inf (fit=1.0) が代表 🔵


def test_empty_peak_set_jaccard_degenerate():
    # 【テスト目的】: 空ピーク集合を含む候補の Jaccard 縮退 (0/0) を確認 (TC-E03)
    # 【テスト内容】: 空 Peak 列を含む候補で ZeroDivisionError を出さず別クラスタ化するか検証
    # 【期待される動作】: 例外なし、空候補は非空候補と結合せず len==2
    # 🟡 信頼性レベル: 縮退の必要性は note.md §6 🔵 だが「空 vs 非空は非類似」は実装時較正 🟡

    # 【テストデータ準備】: index0 が空 Peak 列 (find_peaks が空を返した候補)
    peak_sets = [[], IDENTICAL_A]
    fits = [0.5, 0.8]
    delta_us = [0.0, 0.0]

    # 【実際の処理実行】: |A∪B|=0 の 0/0 を縮退規則で処理
    result = jaccard_clusters(peak_sets, fits, delta_us)

    # 【結果検証】: 空候補も index を保持し members から消えない (非破壊性)
    assert len(result) == 2  # 【確認内容】: 空 vs 非空は非類似で別クラスタ 🟡


def test_jenks_breaks_empty_input_degenerate():
    # 【テスト目的】: jenks_breaks の空入力を空タプルに縮退することを確認 (TC-E04)
    # 【テスト内容】: values=[] で分割対象なしのとき例外を出さず () を返すか検証
    # 【期待される動作】: jenks_breaks([], n_classes=2) == ()、例外を送出しない
    # 🟡 信頼性レベル: requirements §4.4 縮退の精神 🔵 だが空返却の具体値は妥当な推測 🟡

    # 【実際の処理実行】: evidence 列が空 (良好解ゼロ) の縮退シナリオ
    result = jenks_breaks([], n_classes=2)

    # 【結果検証】: 呼び出し側 (TASK-0007) が空を安全に扱える自然な縮退境界
    assert result == ()  # 【確認内容】: 空入力は空タプルに縮退 🟡


def test_jenks_breaks_n_classes_ge_len_degenerate():
    # 【テスト目的】: n_classes >= 要素数の過大群数指定で縮退することを確認 (TC-E05)
    # 【テスト内容】: 2 要素を 5 群に分割不能なとき例外を出さず縮退境界を返すか検証
    # 【期待される動作】: 例外なし、返り値が tuple[float, ...]
    # 🟡 信頼性レベル: requirements §4.4 縮退規則 🔵 だが具体的な返却形は実装時確定 🟡

    # 【テストデータ準備】: 良好解が少数のとき既定より大きい群数指定
    values = [5.0, 7.0]

    # 【実際の処理実行】: 有効分割が定義できない過大 n_classes で縮退
    result = jenks_breaks(values, n_classes=5)

    # 【結果検証】: IndexError を出さず健全な float タプルを返す
    assert isinstance(result, tuple)  # 【確認内容】: 戻り値は tuple 🟡
    assert all(isinstance(b, float) for b in result)  # 【確認内容】: 各境界が素の float 🟡


def test_never_returns_nan_none_or_raises():
    # 【テスト目的】: あらゆる縮退で戻り値が健全な型に一元化されることを確認 (TC-E06)
    # 【テスト内容】: 縮退寄りの最小入力で jaccard_clusters/jenks_breaks の型健全性を横断検証
    # 【期待される動作】: ClusterResult タプル・int/tuple[int]・float タプル・NaN/None なし
    # 🔵 信頼性レベル: requirements §3 (素の tuple/int/float・numpy 非露出) / §4.5 に依拠

    # 【実際の処理実行】: 単一候補 + 単一 evidence の縮退経路で型を確認
    clusters = jaccard_clusters([IDENTICAL_A], [0.7], [0.0])
    breaks = jenks_breaks([42.0], n_classes=2)

    # 【結果検証】: jaccard_clusters は tuple[ClusterResult, ...] で素の int/tuple[int]
    assert isinstance(clusters, tuple)  # 【確認内容】: 戻り値は tuple 🔵
    assert all(isinstance(c, ClusterResult) for c in clusters)  # 【確認内容】: 要素は ClusterResult 🔵
    representative = clusters[0].representative
    assert type(representative) is int  # 【確認内容】: 代表は素の int (numpy 非露出) 🔵
    assert isinstance(clusters[0].members, tuple)  # 【確認内容】: members は tuple 🔵
    assert all(type(i) is int for i in clusters[0].members)  # 【確認内容】: members 要素は素の int 🔵

    # 【結果検証】: jenks_breaks は tuple[float, ...] で NaN/None を返さない
    assert isinstance(breaks, tuple)  # 【確認内容】: 戻り値は tuple 🔵
    assert breaks is not None  # 【確認内容】: None を返さない 🔵
    assert all(type(b) is float for b in breaks)  # 【確認内容】: 各境界は素の float 🔵
    assert all(not math.isnan(b) for b in breaks)  # 【確認内容】: NaN を返さない 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（全同一・単一・閾値境界・決定論・タイ）
# ---------------------------------------------------------------------------


def test_all_identical_structure_single_cluster():
    # 【テスト目的】: 全候補同一構造が 1 クラスタに潰れ全 index を保持することを確認 (TC-B01)
    # 【テスト内容】: 全対 Jaccard>=0.85 の N=3 で代表 1 + 代替 N−1 の形になるか検証
    # 【期待される動作】: len==1, members==(0,1,2), representative==1 (FoM 最大)
    # 🔵 信頼性レベル: 受け入れ基準 TC-004-04 / EDGE-103 / requirements §4.4 に直接依拠

    # 【テストデータ準備】: 全候補が同一 bin 集合 (完全 Jaccard 重複)、index1 の fit が最大
    peak_sets = [IDENTICAL_A, IDENTICAL_B, IDENTICAL_A]
    fits = [0.7, 0.9, 0.5]
    delta_us = [0.0, 0.0, 0.0]

    # 【実際の処理実行】: 最大縮約ケース (同一相の微小バリアント多数)
    result = jaccard_clusters(peak_sets, fits, delta_us)

    # 【結果検証】: N=3 全 index が members に保持され欠落ゼロ (非破壊性)
    assert len(result) == 1  # 【確認内容】: 1 クラスタに潰れる 🔵
    assert result[0].members == (0, 1, 2)  # 【確認内容】: 全 index を昇順保持 (長 N) 🔵
    assert result[0].representative == 1  # 【確認内容】: FoM 最大 (fit=0.9) が代表 🔵


def test_single_candidate_single_cluster():
    # 【テスト目的】: 候補 1 個の最小非空入力が単独クラスタになることを確認 (TC-B02/EDGE-102)
    # 【テスト内容】: N=1 で自己ループなく単独クラスタ化し例外を出さないか検証
    # 【期待される動作】: len==1, representative==0, members==(0,)
    # 🟡 信頼性レベル: EDGE-102 / requirements §4.4 に依拠 (具体挙動は妥当な推測 🟡)

    # 【テストデータ準備】: union-find の下限 N=1 (候補が 1 相に絞られた探索終端)
    peak_sets = [IDENTICAL_A]
    fits = [0.7]
    delta_us = [0.0]

    # 【実際の処理実行】: 単独候補のクラスタ化
    result = jaccard_clusters(peak_sets, fits, delta_us)

    # 【結果検証】: 代表と members が同一 index
    assert len(result) == 1  # 【確認内容】: 単独クラスタ 🟡
    assert result[0].representative == 0  # 【確認内容】: 代表は唯一の index 🟡
    assert result[0].members == (0,)  # 【確認内容】: members も唯一の index 🟡


def test_jaccard_exactly_threshold_merges():
    # 【テスト目的】: Jaccard が閾値ちょうどのとき同一クラスタに結合することを確認 (TC-B03)
    # 【テスト内容】: |A∩B|/|A∪B| を閾値と厳密一致させ >= 判定 (境界包含) を検証
    # 【期待される動作】: len==1 (等号で結合)
    # 🟡 信頼性レベル: 判定式は requirements §2.2/§4.1 🔵 だが「等号を含む」は実装時較正 🟡

    # 【テストデータ準備】: A={10,20,30} bin、B={10,20,30,40} bin で共有3/合併4 → Jaccard=0.75
    # 【前提条件確認】: similarity_threshold=0.75 を明示し等号境界を狙う
    peak_a = _peaks([10.0, 20.0, 30.0])
    peak_b = _peaks([10.0, 20.0, 30.0, 40.0])
    peak_sets = [peak_a, peak_b]
    fits = [0.8, 0.7]
    delta_us = [0.0, 0.0]

    # 【実際の処理実行】: Jaccard=0.75 == threshold=0.75 の等号側を検証
    result = jaccard_clusters(
        peak_sets, fits, delta_us, similarity_threshold=0.75, bin_width_deg=0.2
    )

    # 【結果検証】: 閾値ちょうどは >= 比較で同一クラスタ (境界包含)
    assert len(result) == 1  # 【確認内容】: Jaccard==threshold は結合 🟡
    assert result[0].members == (0, 1)  # 【確認内容】: 両 index を保持 🟡


def test_deterministic_regardless_of_input_order():
    # 【テスト目的】: 入力順を入れ替えても同一クラスタ構造・ビット同一を返す (TC-B04/完了条件6)
    # 【テスト内容】: 基準と並べ替えで正規化クラスタ構造 (相 identity) が一致するか検証
    # 【期待される動作】: 署名が一致、同一入力 2 回で result_a == result_b (ビット同一)
    # 🔵 信頼性レベル: 完了条件6 / REQ-403 / NFR-102 に依拠 (index 再マップ設計は 🟡)

    # 【テストデータ準備】: A,B が結合 C 単独の基準 [A,C,B] と、その並べ替え [B,A,C]
    # （fits/delta_us も候補に追随して並べ替え、相 identity ベースで構造を比較）
    base_sets = [IDENTICAL_A, DIFFERENT_C, IDENTICAL_B]
    base_fits = [0.9, 0.7, 0.6]
    base_us = [0.0, 0.0, 0.0]
    perm_sets = [IDENTICAL_B, IDENTICAL_A, DIFFERENT_C]
    perm_fits = [0.6, 0.9, 0.7]
    perm_us = [0.0, 0.0, 0.0]

    # 【実際の処理実行】: 基準と並べ替えでクラスタリング
    result_base = jaccard_clusters(base_sets, base_fits, base_us)
    result_perm = jaccard_clusters(perm_sets, perm_fits, perm_us)

    # 【結果検証】: index 非依存の署名 (メンバー相集合 + 代表相) が並べ替えで一致
    assert _cluster_signatures(base_sets, result_base) == _cluster_signatures(
        perm_sets, result_perm
    )  # 【確認内容】: 入力順に依存しないクラスタ構造 🔵

    # 【結果検証】: 同一入力を 2 回呼べばビット同一 (呼び出し回数非依存)
    assert jaccard_clusters(base_sets, base_fits, base_us) == result_base
    # 【確認内容】: 再実行でビット同一 (決定論) 🔵


def test_fom_tie_breaks_by_smaller_index():
    # 【テスト目的】: FoM が完全同点のとき index 小優先で代表を決めることを確認 (TC-B05/完了条件6)
    # 【テスト内容】: fit・ΔU とも同値で FoM が厳密同点のときタイ処理を単独検証
    # 【期待される動作】: representative==0 (index 小優先), members==(0,1)
    # 🟡 信頼性レベル: 完了条件6 のタイ規則 (index 小優先) は 🟡 (要件で残る唯一の 🟡)

    # 【テストデータ準備】: fits=[0.8,0.8], delta_us=[0.0,0.0] で FoM が厳密同点
    peak_sets = [IDENTICAL_A, IDENTICAL_B]
    fits = [0.8, 0.8]
    delta_us = [0.0, 0.0]

    # 【実際の処理実行】: 同点で非決定にならず一意規則で代表確定
    result = jaccard_clusters(peak_sets, fits, delta_us)

    # 【結果検証】: 同点は index 0 が確定的に代表 (TC-B04 の決定論と整合)
    assert len(result) == 1  # 【確認内容】: 同一クラスタに縮約 🟡
    assert result[0].representative == 0  # 【確認内容】: FoM 同点は index 小優先 🟡
    assert result[0].members == (0, 1)  # 【確認内容】: 全 index を昇順保持 🟡


def test_jenks_breaks_singleton_and_uniform_degenerate():
    # 【テスト目的】: 単一要素・全同値の退化入力で例外化せず縮退することを確認 (TC-B06)
    # 【テスト内容】: 分散 0 で群分割の実益が無い退化ケースで自然な境界に縮退するか検証
    # 【期待される動作】: 例外なし、返り値が tuple[float, ...]
    # 🟡 信頼性レベル: requirements §4.4 縮退の精神 🔵 だが具体的縮退値は実装時確定 🟡

    # 【実際の処理実行】: 単一要素 (evidence 1 件) の退化入力
    singleton = jenks_breaks([5.0], n_classes=2)
    # 【実際の処理実行】: 全同値 (SDCM=0) の退化入力
    uniform = jenks_breaks([3.0, 3.0, 3.0], n_classes=2)

    # 【結果検証】: ゼロ分散・単一要素で DP が破綻せず健全な float タプルを返す
    assert isinstance(singleton, tuple)  # 【確認内容】: 単一要素は tuple に縮退 🟡
    assert all(type(b) is float for b in singleton)  # 【確認内容】: 各要素は素の float 🟡
    assert isinstance(uniform, tuple)  # 【確認内容】: 全同値は tuple に縮退 🟡
    assert all(type(b) is float for b in uniform)  # 【確認内容】: 各要素は素の float 🟡
