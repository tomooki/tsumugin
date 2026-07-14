"""TASK-0012 store/serialization (phase_to_dict / phase_from_dict) の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/store/serialization.py``: ``phase_to_dict(phase) -> dict[str, Any]`` /
  ``phase_from_dict(data) -> PhaseInstance`` を新設。lattice / sigma / occupancies / scale /
  wt_frac / lifecycle を含む**完全 roundtrip** (``phase_from_dict(phase_to_dict(p)) == p``) を保証。

書式は ``tests/test_model_m2.py`` を範とし、roundtrip は原則 ``==`` で厳密比較、JSON 安全性は
``json.dumps(d, allow_nan=False)`` が例外を出さないことで検証する。テストケース定義
(15 件: 正常系 6 N-01〜N-06 / 異常系 3 E-01〜E-03 / 境界値 6 B-01〜B-06) に 1:1 対応する。

未実装のため ``tsumugin.store.serialization`` の import が collection 時に失敗し、
本ファイルの全テストがエラー(=失敗)になる想定 (Red フェーズ)。
"""

from __future__ import annotations

import json
import math
import pytest

from tsumugin.model import LatticeParams, PhaseInstance, PhaseLifecycle, TofBankParams
from tsumugin.store.ledger import _canonical_json
from tsumugin.store.serialization import (
    bank_params_from_dict,
    bank_params_to_dict,
    phase_from_dict,
    phase_to_dict,
)

# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_full_phase_roundtrip_equal():
    # 【テスト目的】: 全フィールド入り相が dict 往復で完全一致することを確認 (N-01 / 完了条件①)
    # 【テスト内容】: フルスペック相を phase_to_dict → phase_from_dict し == 比較
    # 【期待される動作】: frozen dataclass の構造的 == で一致する
    # 🔵 信頼性: 要件定義 §3 完了条件① / interfaces.py L261-262

    # 【テストデータ準備】: sigma/occupancies/lifecycle を含むフルスペック相を用意
    # 【初期条件設定】: 逐次精密化で全属性が確定した実状況を再現
    p = PhaseInstance(
        "A",
        LatticeParams(5.01, 5.02, 5.03, 91.0, 92.0, 93.0, sigma={"a": 0.002, "c": 0.003}),
        scale=1.25,
        wt_frac=0.35,
        occupancies={"Fe": 0.98, "O": 1.0},
        lifecycle=PhaseLifecycle(birth_frame=10, death_frame=18, confidence=0.87),
    )

    # 【実際の処理実行】: dict へ直列化して再構築 (phase_to_dict → phase_from_dict の往復)
    restored = phase_from_dict(phase_to_dict(p))

    # 【結果検証】: 復元相が元と等価 (全フィールド lossless 往復)
    assert restored == p  # 【確認内容】: 構造的 == で完全一致 🔵


def test_to_dict_schema_keys_and_nesting():
    # 【テスト目的】: phase_to_dict の返り値が期待キー集合とネスト構造を持つことを確認 (N-02)
    # 【テスト内容】: top-level / lattice / lifecycle のキーとネスト dict を検証
    # 【期待される動作】: lattice/lifecycle がフラットでなくネスト dict である
    # 🟡 信頼性: 要件定義 2.1 の dict スキーマ (TASK-0014 が依存するため固定)

    # 【テストデータ準備】: 後続 TASK-0014 が依存する dict スキーマを固定する代表入力
    # 【初期条件設定】: lifecycle は birth_frame のみ確定という部分指定
    d = phase_to_dict(PhaseInstance("A", LatticeParams(5, 5, 5), lifecycle=PhaseLifecycle(birth_frame=3)))

    # 【結果検証】: キー名・ネスト構造・既定値の出力を確認
    assert d["phase_ref"] == "A"  # 【確認内容】: phase_ref が top-level に出力される 🟡
    # 【Issue #66 / FR-306】: σ 由来 sigma_source を lattice スキーマへ追加 🟡
    assert set(d["lattice"]) == {"a", "b", "c", "alpha", "beta", "gamma", "sigma", "sigma_source"}
    assert d["lattice"]["a"] == 5.0  # 【確認内容】: 格子長がネスト dict に出力される 🟡
    assert d["lattice"]["alpha"] == 90.0  # 【確認内容】: 既定角も明示出力される 🟡
    assert d["lifecycle"]["birth_frame"] == 3  # 【確認内容】: lifecycle がネスト dict である 🟡
    assert d["occupancies"] == {}  # 【確認内容】: 空 occupancies は {} で出力 🟡
    assert d["wt_frac"] is None  # 【確認内容】: 未指定 wt_frac は None 🟡


def test_full_phase_dict_json_dumps_allow_nan_false():
    # 【テスト目的】: 有限フル相の dict が json.dumps(allow_nan=False) 可能なことを確認 (N-03 / 完了条件③)
    # 【テスト内容】: フル相を dict 化し JSON 直列化 → json.loads → phase_from_dict で == 往復
    # 【期待される動作】: 例外を出さず文字列を返し、JSON 経由でも元相と等価
    # 🔵 信頼性: 要件定義 §3 JSON 安全性 / TC-104-03

    # 【テストデータ準備】: 永続化 (JSONL) の前提となる JSON 純度を正常データで確認
    p = PhaseInstance(
        "A",
        LatticeParams(5.01, 5.02, 5.03, 91.0, 92.0, 93.0, sigma={"a": 0.002, "c": 0.003}),
        scale=1.25,
        wt_frac=0.35,
        occupancies={"Fe": 0.98, "O": 1.0},
        lifecycle=PhaseLifecycle(birth_frame=10, death_frame=18, confidence=0.87),
    )

    # 【実際の処理実行】: dict 化 → JSON 直列化 → 復元
    d = phase_to_dict(p)
    text = json.dumps(d, allow_nan=False)  # 【確認内容】: 例外なく直列化できる (素の型のみ) 🔵
    restored = phase_from_dict(json.loads(text))

    # 【結果検証】: JSON 文字列を得られ、JSON 経由の往復でも元相と等価
    assert isinstance(text, str)  # 【確認内容】: JSON 文字列が返る 🔵
    assert restored == p  # 【確認内容】: json.loads 経由でも roundtrip 等価 🔵


def test_lifecycle_roundtrip_preserved():
    # 【テスト目的】: PhaseLifecycle が dict 往復で完全一致することを確認 (N-04)
    # 【テスト内容】: birth のみ確定・death 未確定の相の lifecycle を往復
    # 【期待される動作】: ネストされた lifecycle が PhaseLifecycle として復元される
    # 🔵 信頼性: 要件定義 2.1/2.2 / phase.py PhaseLifecycle

    # 【テストデータ準備】: FR-305 相ライフサイクル (birth 確定・death 未確定) を再現
    p = PhaseInstance(
        "A",
        LatticeParams(5, 5, 5),
        lifecycle=PhaseLifecycle(birth_frame=7, death_frame=None, confidence=0.5),
    )

    # 【実際の処理実行】: dict 往復
    q = phase_from_dict(phase_to_dict(p))

    # 【結果検証】: lifecycle が PhaseLifecycle として復元され death=None も保存される
    assert q.lifecycle == PhaseLifecycle(birth_frame=7, death_frame=None, confidence=0.5)  # 🔵
    assert isinstance(q.lifecycle, PhaseLifecycle)  # 【確認内容】: dict のままにせず型復元 🔵


def test_sigma_occupancies_roundtrip_preserved():
    # 【テスト目的】: 非空の sigma / occupancies が dict 往復で保存されることを確認 (N-05)
    # 【テスト内容】: Mapping フィールドを素の dict にコピーして往復
    # 【期待される動作】: Mapping が等価な dict として復元され相全体も == になる
    # 🔵 信頼性: 要件定義 2.1 / phase.py sigma/occupancies

    # 【テストデータ準備】: ±σ・占有率という定量情報を持つ相の永続化を再現
    p = PhaseInstance(
        "A",
        LatticeParams(5, 5, 5, sigma={"a": 0.01, "b": 0.02}),
        occupancies={"Na": 0.9},
    )

    # 【実際の処理実行】: dict 往復
    q = phase_from_dict(phase_to_dict(p))

    # 【結果検証】: Mapping フィールドが lossless に往復し相全体も等価
    assert q.lattice.sigma == {"a": 0.01, "b": 0.02}  # 【確認内容】: sigma が保存される 🔵
    assert q.occupancies == {"Na": 0.9}  # 【確認内容】: occupancies が保存される 🔵
    assert q == p  # 【確認内容】: 相全体が == で一致 🔵


def test_sigma_source_roundtrip_preserved():
    # 【テスト目的】: sigma_source ("covariance"/"proxy") が dict 往復で保存されることを確認
    #   (Issue #66 / FR-306 / NFR-107)。
    # 🔵 信頼性: Issue #66 本文 / phase.py LatticeParams.sigma_source

    p = PhaseInstance(
        "A",
        LatticeParams(5, 5, 5, sigma={"a": 0.01}, sigma_source="covariance"),
    )

    q = phase_from_dict(phase_to_dict(p))

    assert q.lattice.sigma_source == "covariance"  # 【確認内容】: σ 由来が保存される 🔵
    assert q == p  # 【確認内容】: 相全体が == で一致 🔵


def test_deterministic_to_dict_and_canonical_json():
    # 【テスト目的】: phase_to_dict の決定論と _canonical_json 互換を確認 (N-06 / NFR-102・REQ-402)
    # 【テスト内容】: 同一相に 2 回適用した dict の等価と canonical JSON 文字列一致を検証
    # 【期待される動作】: 純関数・sort_keys により決定論的、素の型なので _canonical_json が通る
    # 🟡 信頼性: 要件定義 §3 決定論 / D-Q5 (_canonical_json を私的 import する点が 🟡)

    # 【テストデータ準備】: ハッシュチェーン (TASK-0014) の前提を確認する代表相
    p = PhaseInstance(
        "A",
        LatticeParams(5.01, 5.02, 5.03, 91.0, 92.0, 93.0, sigma={"a": 0.002, "c": 0.003}),
        scale=1.25,
        wt_frac=0.35,
        occupancies={"Fe": 0.98, "O": 1.0},
        lifecycle=PhaseLifecycle(birth_frame=10, death_frame=18, confidence=0.87),
    )

    # 【実際の処理実行】: 2 回の直列化と canonical JSON 変換
    d1 = phase_to_dict(p)
    d2 = phase_to_dict(p)

    # 【結果検証】: dict 等価かつ canonical JSON が一致 (= 素の型のみである証跡)
    assert d1 == d2  # 【確認内容】: 同一入力で等価 dict 🟡
    assert _canonical_json(d1) == _canonical_json(d2)  # 【確認内容】: 決定論的 JSON 一致 🟡


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（非有限 → None、M1 レビュー教訓）
# ---------------------------------------------------------------------------


def test_non_finite_scale_becomes_none_and_json_safe():
    # 【テスト目的】: 非有限 scale が None 化され json.dumps(allow_nan=False) が通ることを確認 (E-01)
    # 【テスト内容】: scale=inf の相を phase_to_dict し None + JSON 直列化
    # 【期待される動作】: d["scale"] is None、json.dumps が成功する (例外を出さない)
    # 🔵 信頼性: 要件定義 §3 JSON 安全性 / search/tree.py _finite_or_none / M1 教訓

    # 【テストデータ準備】: 精密化発散で scale=inf となった相を再現
    p = PhaseInstance("A", LatticeParams(5, 5, 5), scale=math.inf)

    # 【実際の処理実行】: dict 化
    d = phase_to_dict(p)

    # 【結果検証】: 非有限が None へ縮退し JSON 安全であること
    assert d["scale"] is None  # 【確認内容】: inf → None へ写像 🔵
    json.dumps(d, allow_nan=False)  # 【確認内容】: 例外を出さず直列化できる 🔵


def test_non_finite_lattice_and_sigma_become_none():
    # 【テスト目的】: 非有限 lattice / sigma 値が None 化され JSON 安全になることを確認 (E-02)
    # 【テスト内容】: lattice.a=nan / sigma["a"]=inf の相を dict 化し純化を検証
    # 【期待される動作】: ネスト dict / Mapping 内も None へ縮退し json.dumps が成功
    # 🔵 信頼性: 要件定義 4.3 EDGE / TC-104-03

    # 【テストデータ準備】: 発散した格子精密化・σ 推定不能フレームを再現
    p = PhaseInstance("A", LatticeParams(math.nan, 5, 5, sigma={"a": math.inf}))

    # 【実際の処理実行】: dict 化
    d = phase_to_dict(p)

    # 【結果検証】: ネスト構造の隅々まで非有限を漏らさないこと
    assert d["lattice"]["a"] is None  # 【確認内容】: nan → None (ネスト dict) 🔵
    assert d["lattice"]["sigma"]["a"] is None  # 【確認内容】: inf → None (Mapping 内) 🔵
    json.dumps(d, allow_nan=False)  # 【確認内容】: 例外を出さず直列化できる 🔵


def test_non_finite_wt_frac_occupancy_confidence_become_none():
    # 【テスト目的】: 残る全 float フィールドの非有限が None 化されることを網羅確認 (E-03)
    # 【テスト内容】: wt_frac=inf / occupancy=nan / confidence=nan の相を dict 化
    # 【期待される動作】: いずれも None へ縮退し json.dumps(allow_nan=False) が成功
    # 🟡 信頼性: 要件定義 4.3/4.4 からの網羅化 (純化漏れフィールドがないことの保証)

    # 【テストデータ準備】: 相分率発散・占有率推定不能・確信度未算出の縮退を再現
    p = PhaseInstance(
        "A",
        LatticeParams(5, 5, 5),
        wt_frac=math.inf,
        occupancies={"Fe": math.nan},
        lifecycle=PhaseLifecycle(confidence=math.nan),
    )

    # 【実際の処理実行】: dict 化
    d = phase_to_dict(p)

    # 【結果検証】: 全 float フィールドが漏れなく None へ縮退すること
    assert d["wt_frac"] is None  # 【確認内容】: wt_frac inf → None 🟡
    assert d["occupancies"]["Fe"] is None  # 【確認内容】: occupancy nan → None 🟡
    assert d["lifecycle"]["confidence"] is None  # 【確認内容】: confidence nan → None 🟡
    json.dumps(d, allow_nan=False)  # 【確認内容】: 例外を出さず直列化できる 🟡


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（最小値、null、既定値等）
# ---------------------------------------------------------------------------


def test_degenerate_roundtrip_minimal_phase():
    # 【テスト目的】: 全 optional が既定の最小相が roundtrip 等価になることを確認 (B-01 / 完了条件②)
    # 【テスト内容】: lifecycle=None / sigma 空 / occupancies 空の相を往復
    # 【期待される動作】: 空 Mapping・None lifecycle でも lossless に往復する
    # 🔵 信頼性: 要件定義 §3 完了条件② / phase.py 既定値

    # 【テストデータ準備】: sigma/occupancies/lifecycle 未確定の初期相 (M0/M1 が多用) を再現
    p = PhaseInstance("x", LatticeParams(5, 5, 5))

    # 【実際の処理実行】: dict 往復
    q = phase_from_dict(phase_to_dict(p))

    # 【結果検証】: 空・None が既定として正しく往復すること
    assert q == p  # 【確認内容】: 縮退相も == で往復 🔵
    assert q.lifecycle is None  # 【確認内容】: None lifecycle が保存される 🔵
    assert q.occupancies == {}  # 【確認内容】: 空 occupancies が保存される 🔵
    assert q.lattice.sigma == {}  # 【確認内容】: 空 sigma が保存される 🔵
    assert q.wt_frac is None  # 【確認内容】: None wt_frac が保存される 🔵


def test_wt_frac_none_roundtrip_not_confused_with_zero():
    # 【テスト目的】: wt_frac の None (未定) と 0.0 (消失) が混同されず往復することを確認 (B-02)
    # 【テスト内容】: wt_frac=None と wt_frac=0.0 の 2 相を往復し区別を検証
    # 【期待される動作】: None は None のまま、0.0 は 0.0 のまま往復し両者は !=
    # 🟡 信頼性: 要件定義 2.2 からの妥当な推測 (None/0.0 区別を明示化)

    # 【テストデータ準備】: 相分率が未計算 (None) か消失 (0.0) かの区別を再現
    p_none = PhaseInstance("A", LatticeParams(5, 5, 5), wt_frac=None)
    p_zero = PhaseInstance("A", LatticeParams(5, 5, 5), wt_frac=0.0)

    # 【実際の処理実行】: それぞれ dict 往復
    q_none = phase_from_dict(phase_to_dict(p_none))
    q_zero = phase_from_dict(phase_to_dict(p_zero))

    # 【結果検証】: None と 0.0 が保存され混同されないこと
    assert q_none.wt_frac is None  # 【確認内容】: None は None のまま 🟡
    assert q_zero.wt_frac == 0.0  # 【確認内容】: 有限 0.0 は純化対象外で保持 🟡
    assert q_none != q_zero  # 【確認内容】: 未定と消失が区別される 🟡


def test_from_dict_ignores_unknown_keys():
    # 【テスト目的】: 未知キーを無視して復元することを確認 (B-03 / 完了条件④ 前方互換)
    # 【テスト内容】: 定義外キー (top-level / lattice 内) を含む dict を phase_from_dict
    # 【期待される動作】: 例外なし・既知フィールドのみで baseline と等価に復元
    # 🟡 信頼性: 要件定義 2.2/§3 前方互換 / 完了条件④ (実装方式は 🟡)

    # 【テストデータ準備】: 新バージョンが書いた JSONL を旧実装が読む状況を再現
    base = phase_to_dict(PhaseInstance("A", LatticeParams(5, 5, 5)))
    data = {**base, "future_field": 123, "lattice": {**base["lattice"], "gamma_star": 88.0}}

    # 【実際の処理実行】: 未知キー入り dict を復元
    restored = phase_from_dict(data)

    # 【結果検証】: 未知キーが無視され baseline と等価であること
    assert restored == PhaseInstance("A", LatticeParams(5, 5, 5))  # 【確認内容】: 未知キー無視 🟡


def test_from_dict_fills_missing_optional_keys():
    # 【テスト目的】: 欠損 optional キーを既定で補完することを確認 (B-04 / 後方互換)
    # 【テスト内容】: 必須キー (phase_ref/lattice の a,b,c) のみの旧スキーマ dict を復元
    # 【期待される動作】: scale/wt_frac/occupancies/lifecycle/sigma/角 が既定で補完される
    # 🟡 信頼性: 要件定義 2.2 欠損補完 / §4.3 (後方互換は 🟡)

    # 【テストデータ準備】: lifecycle 導入前 (TASK-0011 以前) に書かれた永続データを再現
    restored = phase_from_dict({"phase_ref": "A", "lattice": {"a": 5.0, "b": 5.0, "c": 5.0}})

    # 【結果検証】: 欠損キーが既定補完され明示既定相と等価であること
    assert restored == PhaseInstance("A", LatticeParams(5, 5, 5))  # 【確認内容】: 既定補完で等価 🟡
    assert restored.scale == 1.0  # 【確認内容】: scale 欠落 → 既定 1.0 🟡
    assert restored.wt_frac is None  # 【確認内容】: wt_frac 欠落 → None 🟡
    assert restored.occupancies == {}  # 【確認内容】: occupancies 欠落 → {} 🟡
    assert restored.lifecycle is None  # 【確認内容】: lifecycle 欠落 → None 🟡
    assert restored.lattice.alpha == 90.0  # 【確認内容】: 角欠落 → 既定 90.0 🟡
    assert restored.lattice.sigma == {}  # 【確認内容】: sigma 欠落 → {} 🟡


def test_default_lattice_angles_roundtrip():
    # 【テスト目的】: 既定角 90.0 が明示出力され往復後も保持されることを確認 (B-05)
    # 【テスト内容】: 角を省略した相 (既定 90.0) を dict 化し往復
    # 【期待される動作】: 既定角が dict へ明示出力され、復元時に 90.0 で戻る
    # 🔵 信頼性: 要件定義 2.1 dict スキーマ / phase.py LatticeParams 既定角

    # 【テストデータ準備】: 立方/正方/斜方晶など角固定 90° の相の永続化を再現
    p = PhaseInstance("A", LatticeParams(4.0, 5.0, 6.0))

    # 【実際の処理実行】: dict 化 → 往復
    d = phase_to_dict(p)

    # 【結果検証】: 既定角も dict に含まれ往復すること (既定省略で欠落させない)
    assert d["lattice"]["alpha"] == 90.0  # 【確認内容】: alpha 既定角が明示出力 🔵
    assert d["lattice"]["beta"] == 90.0  # 【確認内容】: beta 既定角が明示出力 🔵
    assert d["lattice"]["gamma"] == 90.0  # 【確認内容】: gamma 既定角が明示出力 🔵
    assert phase_from_dict(d) == p  # 【確認内容】: 既定角込みで roundtrip 等価 🔵


def test_confidence_boundary_values_roundtrip():
    # 【テスト目的】: confidence の端点 0.0 / 1.0 が純化されず保持されることを確認 (B-06)
    # 【テスト内容】: confidence=0.0 と 1.0 の相をそれぞれ往復
    # 【期待される動作】: 有限端点は math.isfinite で True のため None 化されず往復する
    # 🟡 信頼性: 要件定義 §4.3 境界値保持 / interfaces.py L37 の [0,1] 注記

    # 【テストデータ準備】: LifecycleTracker が算出した確信度 0.0〜1.0 の永続化を再現
    p0 = PhaseInstance("A", LatticeParams(5, 5, 5), lifecycle=PhaseLifecycle(confidence=0.0))
    p1 = PhaseInstance("A", LatticeParams(5, 5, 5), lifecycle=PhaseLifecycle(confidence=1.0))

    # 【実際の処理実行】: それぞれ dict 往復
    q0 = phase_from_dict(phase_to_dict(p0))
    q1 = phase_from_dict(phase_to_dict(p1))

    # 【結果検証】: 端点が丸め・クランプ・偽陽性 None なく保持されること
    assert q0.lifecycle.confidence == 0.0  # 【確認内容】: 下限 0.0 を保持 (None 化しない) 🟡
    assert q1.lifecycle.confidence == 1.0  # 【確認内容】: 上限 1.0 を保持 🟡


# ---------------------------------------------------------------------------
# 4. PR #2 レビュー指摘対応 (往復非対称の解消)
# ---------------------------------------------------------------------------


def test_from_dict_rejects_none_lattice_fail_loud():
    # 【テスト目的】: 非有限で None 化された格子 a/b/c を from_dict が既定値で捏造せず
    #   fail-loud で拒否することの検証 (PR #2 レビュー MEDIUM: 往復非対称の解消)
    # 【期待される動作】: ValueError (LatticeParams(a=None) の沈黙生成を許さない)
    p = PhaseInstance("A", LatticeParams(math.nan, 5, 5))
    d = phase_to_dict(p)
    assert d["lattice"]["a"] is None  # to_dict 側は既存契約どおり None 化
    with pytest.raises(ValueError, match="lattice.a"):
        phase_from_dict(d)


def test_from_dict_rejects_non_finite_lattice_value():
    # 【テスト目的】: 外部生成 dict が非有限格子を直接持つ場合も復元を拒否する
    p = PhaseInstance("A", LatticeParams(5, 5, 5))
    d = phase_to_dict(p)
    d["lattice"]["b"] = math.inf
    with pytest.raises(ValueError, match="lattice.b"):
        phase_from_dict(d)


# ---------------------------------------------------------------------------
# 5. TASK-0036 TofBankParams 往復 (TC-401-04 / EDGE-002)
# ---------------------------------------------------------------------------


def test_bank_params_roundtrip_full():
    # 【テスト目的】: 全フィールド入り TofBankParams が dict 往復で完全一致することを確認 (TC-401-04)
    # 【期待される動作】: frozen dataclass の構造的 == で一致する
    p = TofBankParams(difc=5000.0, difa=1.5, zero=-3.0)
    restored = bank_params_from_dict(bank_params_to_dict(p))
    assert restored == p


def test_bank_params_to_dict_schema_and_json_safe():
    # 【テスト目的】: bank_params_to_dict のキー集合と JSON 安全性を確認 (TC-401-04)
    # 【期待される動作】: difc/difa/zero を持つ素の dict で json.dumps(allow_nan=False) 可能
    d = bank_params_to_dict(TofBankParams(difc=5000.0))
    assert set(d) == {"difc", "difa", "zero"}
    assert d["difc"] == 5000.0
    assert d["difa"] == 0.0  # 【既定明示】: 既定 difa も省略せず出力
    assert d["zero"] == 0.0
    json.dumps(d, allow_nan=False)  # 【確認内容】: 例外なく直列化できる


def test_bank_params_from_dict_fills_missing_defaults():
    # 【テスト目的】: 欠損 optional キー (difa/zero) を既定値補完することを確認 (EDGE-002 欠損補完)
    # 【期待される動作】: difc のみの dict から difa=0.0/zero=0.0 で復元される
    restored = bank_params_from_dict({"difc": 5000.0})
    assert restored == TofBankParams(difc=5000.0)
    assert restored.difa == 0.0
    assert restored.zero == 0.0


def test_bank_params_from_dict_ignores_unknown_keys():
    # 【テスト目的】: 未知キーを無視して復元することを確認 (前方互換)
    restored = bank_params_from_dict({"difc": 5000.0, "difa": 1.0, "zero": 2.0, "future": 99})
    assert restored == TofBankParams(difc=5000.0, difa=1.0, zero=2.0)


def test_bank_params_non_finite_becomes_none_and_json_safe():
    # 【テスト目的】: 非有限値が None 化され json.dumps(allow_nan=False) が通ることを確認 (M1 教訓踏襲)
    d = bank_params_to_dict(TofBankParams(difc=math.inf, difa=math.nan, zero=5.0))
    assert d["difc"] is None
    assert d["difa"] is None
    assert d["zero"] == 5.0
    json.dumps(d, allow_nan=False)


def test_bank_params_from_dict_none_difc_fills_default():
    # 【テスト目的】: 非有限で None 化された difc/difa/zero が既定値補完で復元されることを確認
    # 【期待される動作】: to_dict が None 化した値も from_dict で既定 (difc=0.0/difa=0.0/zero=0.0) に補完
    restored = bank_params_from_dict({"difc": None, "difa": None, "zero": None})
    assert restored == TofBankParams(difc=0.0, difa=0.0, zero=0.0)


def test_bank_params_boundary_zero_values_preserved():
    # 【テスト目的】: 有限 0.0 が純化・欠損補完で誤って潰されず保持されることを確認 (境界値)
    p = TofBankParams(difc=0.0, difa=0.0, zero=0.0)
    restored = bank_params_from_dict(bank_params_to_dict(p))
    assert restored == p
