"""TASK-0025 model 拡張 (CellConfig / channel kind / multistart / MuCalculator) の失敗テスト (TDD Red)。

対象実装:
- ``src/tsumugin/model/cell.py``: ``CellLayer`` / ``BeamConfig`` / ``CellConfig`` /
  ``MuCalculator`` Protocol / ``XraylibMuCalculator`` スタブ 新設 (未実装)
- ``src/tsumugin/model/channel.py``: ``ChannelKind`` Literal 末尾に
  voltage/current/capacity/composition を追加 (未実装)
- ``src/tsumugin/model/hypothesis.py``: ``RefinementMetrics.multistart`` 追加 (未実装)
- ``src/tsumugin/model/__init__.py``: 新規 5 シンボルの re-export (未実装)

すべて既定値付きの非破壊追加 (REQ-404) で、既存モデルの位置引数・比較・生成を壊さない。
書式は ``tests/test_model.py`` / ``tests/test_model_m2.py`` を範とし、frozen 検証は
``FrozenInstanceError``、近似は ``pytest.approx`` を用いる。
テストケース定義 (21 件: 正常系 10 / 異常系 4 / 境界値 7) に 1:1 対応する。

未実装のため ``CellLayer`` / ``BeamConfig`` / ``CellConfig`` / ``MuCalculator`` /
``XraylibMuCalculator`` の import が collection 時に失敗し、
本ファイルの全テストがエラー(=失敗)になる想定 (Red フェーズ)。
"""

from __future__ import annotations

import dataclasses

import pytest
from dataclasses import FrozenInstanceError

from tsumugin.model import (
    BeamConfig,
    CellConfig,
    CellLayer,
    ExternalChannel,
    MuCalculator,
    RefinementMetrics,
    XraylibMuCalculator,
)


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_cell_layer_explicit_construction_holds_attributes():
    # 【テスト目的】: CellLayer が指定値で生成でき各属性を独立に読み出せることを確認 (N-01)
    # 【テスト内容】: role/material/thickness_mm/density を明示指定して生成し属性値を検証
    # 【期待される動作】: frozen dataclass として生成され 4 フィールドが指定どおり保持される
    # 🔵 信頼性: 要件定義 2.1 / interfaces.py L40-48 に依拠

    # 【テストデータ準備】: Be 窓 (層厚 0.5mm・密度 1.85) という代表的な operando セル層
    # 【初期条件設定】: 4 フィールドすべてを明示指定した状態を再現
    layer = CellLayer(role="window", material="Be", thickness_mm=0.5, density=1.85)

    # 【結果検証】: 各フィールドが指定値どおり独立に保持されること
    # 【期待値確認】: interfaces.py のフィールド定義に一致する値を保持
    assert layer.role == "window"  # 【確認内容】: 層の役割が指定どおり保持される 🔵
    assert layer.material == "Be"  # 【確認内容】: 物質名が指定どおり保持される 🔵
    assert layer.thickness_mm == pytest.approx(0.5)  # 【確認内容】: 層厚が指定どおり保持される 🔵
    assert layer.density == pytest.approx(1.85)  # 【確認内容】: 密度が指定どおり保持される 🔵


def test_cell_layer_equality_is_structural():
    # 【テスト目的】: 同一フィールド値は ==、異なる値は != となる値等価を確認 (N-02)
    # 【テスト内容】: 同値 2 インスタンスの等価と thickness_mm 違いの不等価を検証
    # 【期待される動作】: dataclass 自動生成の __eq__ が既定値 (density=None) 込みで構造的に比較する
    # 🔵 信頼性: 要件定義 2.1 に依拠

    # 【テストデータ準備】: 値オブジェクトとしての等価性 (M0〜M2 不変値オブジェクト規約) を代表
    # 【初期条件設定】: density は既定 None のまま比較 (既定値も比較に寄与)
    same_a = CellLayer("window", "Be", 0.5)
    same_b = CellLayer("window", "Be", 0.5)
    other = CellLayer("window", "Be", 0.6)

    # 【結果検証】: 構造的等価と不等価が成立すること
    # 【期待値確認】: dataclass eq=True (既定) による値比較
    assert same_a == same_b  # 【確認内容】: 同値インスタンスが等価 (既定 density=None も比較に含む) 🔵
    assert same_a != other  # 【確認内容】: thickness_mm が異なれば不等価 🔵


def test_beam_config_construction_wavelength_and_energy_variants():
    # 【テスト目的】: BeamConfig が波長系/エネルギー系の部分指定で生成でき属性を保持することを確認 (N-03)
    # 【テスト内容】: wavelength のみ指定と energy_kev+size_mm 指定の 2 通りを生成し検証
    # 【期待される動作】: 全フィールド既定値付きのため部分指定でも生成でき、未指定は None に縮退
    # 🔵 信頼性: 要件定義 2.2 / interfaces.py L50-57 に依拠

    # 【テストデータ準備】: 波長系 (実験室系) とエネルギー系 (放射光) の 2 通りのビーム条件を代表
    # 【初期条件設定】: energy/wavelength 一方必須のバリデーションは課さない (器のみ)
    by_wavelength = BeamConfig(wavelength=0.7)
    by_energy = BeamConfig(energy_kev=20.0, size_mm=(0.5, 0.5))

    # 【結果検証】: 指定フィールドが保持され未指定フィールドが既定 None であること
    # 【期待値確認】: interfaces.py のフィールド定義に一致
    assert by_wavelength.wavelength == pytest.approx(0.7)  # 【確認内容】: 波長が指定どおり保持される 🔵
    assert by_wavelength.energy_kev is None  # 【確認内容】: 未指定の energy_kev は既定 None 🔵
    assert by_wavelength.size_mm is None  # 【確認内容】: 未指定の size_mm は既定 None 🔵
    assert by_energy.energy_kev == pytest.approx(20.0)  # 【確認内容】: エネルギーが指定どおり保持される 🔵
    assert by_energy.size_mm == (0.5, 0.5)  # 【確認内容】: ビームサイズが tuple で保持される 🔵
    assert by_energy.wavelength is None  # 【確認内容】: 未指定の wavelength は既定 None 🔵


def test_cell_config_explicit_construction_holds_attributes():
    # 【テスト目的】: CellConfig が geometry/layers/beam/mu_t_calc 指定で生成できることを確認 (N-04)
    # 【テスト内容】: 透過セル (Be 窓 1 層・μt=1.2) を明示生成し各属性を検証
    # 【期待される動作】: frozen dataclass として生成されネスト値オブジェクト (layers/beam) を保持する
    # 🔵 信頼性: 要件定義 2.3 / interfaces.py L59-67 に依拠

    # 【テストデータ準備】: 吸収補正 v1 (TASK-0026) の代表入力となる透過セル構成
    # 【初期条件設定】: layers は tuple、beam はネスト BeamConfig として指定
    config = CellConfig(
        geometry="transmission",
        layers=(CellLayer("window", "Be", 0.5),),
        beam=BeamConfig(wavelength=0.7),
        mu_t_calc=1.2,
    )

    # 【結果検証】: 各フィールドが指定値どおり保持されること
    # 【期待値確認】: interfaces.py のフィールド定義に一致
    assert config.geometry == "transmission"  # 【確認内容】: セル形状が指定どおり保持される 🔵
    assert config.layers == (CellLayer("window", "Be", 0.5),)  # 【確認内容】: layers が tuple で保持 🔵
    assert config.beam == BeamConfig(wavelength=0.7)  # 【確認内容】: beam がネスト値オブジェクトで保持 🔵
    assert config.mu_t_calc == pytest.approx(1.2)  # 【確認内容】: 計算済み μt が指定どおり保持される 🔵


def test_cell_config_equality_including_nested_values():
    # 【テスト目的】: 同一 geometry/layers の 2 インスタンスがネスト込みで == となることを確認 (N-05)
    # 【テスト内容】: tuple 内 CellLayer を持つ 2 つの CellConfig の等価比較を検証
    # 【期待される動作】: tuple と CellLayer の == が再帰的に要素比較し構造的等価が成立する
    # 🔵 信頼性: 要件定義 2.3 に依拠

    # 【テストデータ準備】: tuple 内 dataclass を持つ frozen 値オブジェクトの構造的等価性を代表
    # 【初期条件設定】: 同一内容の毛細管セル構成を 2 つ独立に生成
    cfg_a = CellConfig("capillary", layers=(CellLayer("window", "Be", 0.5),))
    cfg_b = CellConfig("capillary", layers=(CellLayer("window", "Be", 0.5),))

    # 【結果検証】: ネスト要素込みで構造的に等価であること
    # 【期待値確認】: tuple 要素の CellLayer も値比較される
    assert cfg_a == cfg_b  # 【確認内容】: layers 内 CellLayer も含めて値等価が成立 🔵


def test_cell_config_asdict_serializes_nested_to_json_native():
    # 【テスト目的】: dataclasses.asdict が CellConfig を JSON 互換型のネスト dict へ展開することを確認 (N-06)
    # 【テスト内容】: 層・ビーム・μt を持つ透過セルを asdict で直列化し展開結果を検証
    # 【期待される動作】: layers が tuple[dict]、beam が dict へ再帰展開される (TC-207-01)
    # 🔵 信頼性: 要件定義 2.3/3 / TC-207-01。asdict は tuple 型を保持する (CPython 仕様: _asdict_inner が type(obj)(...) で再生成)

    # 【テストデータ準備】: 永続化・エクスポート時の直列化経路を代表する透過セル構成
    # 【初期条件設定】: 専用 to_dict/from_dict なしで asdict のみ用いる
    cfg = CellConfig(
        geometry="transmission",
        layers=(CellLayer("window", "Be", 0.5),),
        beam=BeamConfig(wavelength=0.7),
        mu_t_calc=1.2,
    )

    # 【実際の処理実行】: dataclasses.asdict で素の dict へ再帰展開
    # 【処理内容】: ネスト dataclass → dict、tuple → list の標準変換
    d = dataclasses.asdict(cfg)

    # 【結果検証】: JSON 互換型 (dict/tuple/str/float/None) のみで構成されること
    # 【期待値確認】: asdict はネスト dataclass を dict へ再帰変換し tuple 型は保持する (Python 仕様)
    assert d["geometry"] == "transmission"  # 【確認内容】: geometry が素の str で保持される 🔵
    # 【Python 仕様】: dataclasses.asdict は tuple を list へ変換せず tuple のまま再帰生成する
    # (_asdict_inner が (list, tuple) 分岐で type(obj)(...) を用いるため)。よって tuple を期待する。
    assert d["layers"] == (
        {"role": "window", "material": "Be", "thickness_mm": 0.5, "density": None},
    )  # 【確認内容】: layers が tuple[dict] へ展開される (Python 仕様上 tuple 型は保持) 🔵
    assert d["beam"] == {
        "wavelength": 0.7,
        "energy_kev": None,
        "size_mm": None,
    }  # 【確認内容】: beam が素の dict へ展開される 🔵
    assert d["mu_t_calc"] == pytest.approx(1.2)  # 【確認内容】: μt が素の float で保持される 🔵


def test_external_channel_voltage_kind_value_for():
    # 【テスト目的】: 拡張 kind "voltage" で ExternalChannel を生成し value_for が従来どおり動くことを確認 (N-07)
    # 【テスト内容】: 電圧チャネルを生成し存在フレームの値と欠損フレームの None 縮退を検証
    # 【期待される動作】: kind Literal 拡張のみで新 kind が合法値となり同期挙動は不変 (REQ-007)
    # 🔵 信頼性: 要件定義 2.4 / REQ-007 / channel.py value_for に依拠

    # 【テストデータ準備】: 充放電電圧のフレーム同期という operando の中核チャネルを代表
    # 【初期条件設定】: frame 0→3.2V, frame 1→3.5V の電圧同期 (frame 9 は欠損)
    channel = ExternalChannel(kind="voltage", sync_map={0: 3.2, 1: 3.5})

    # 【結果検証】: 新 kind でも value_for の契約 (存在→値 / 欠損→None) が保たれること
    # 【期待値確認】: ExternalChannel 本体・value_for は無改変 (sync_map.get)
    assert channel.kind == "voltage"  # 【確認内容】: 新 kind が合法値として保持される 🔵
    assert channel.value_for(1) == pytest.approx(3.5)  # 【確認内容】: 存在フレームは対応値を返す 🔵
    assert channel.value_for(9) is None  # 【確認内容】: 欠損フレームは None (例外なし) 🔵


def test_refinement_metrics_multistart_explicit_construction():
    # 【テスト目的】: RefinementMetrics(..., multistart={...}) が生成でき値を保持することを確認 (N-08)
    # 【テスト内容】: multistart メタ情報を明示付与して生成し値と既存フィールドの保持を検証
    # 【期待される動作】: 末尾追加フィールドに Mapping を渡して生成でき保持される (TC-201-06)
    # 🔵 信頼性: 要件定義 2.5 / REQ-006 / TC-201-06 / interfaces.py L84-87 に依拠

    # 【テストデータ準備】: マルチスタート精密化 (N=8・単一 basin・発散なし) の記録を代表 (REQ-006)
    # 【初期条件設定】: 既存 5 フィールド + multistart を指定 (evidence は既定のまま)
    metrics = RefinementMetrics(
        rwp=1.0,
        gof=1.1,
        chi2=1.2,
        n_obs=100,
        n_params=5,
        multistart={"n": 8, "n_basins": 1, "n_diverged": 0},
    )

    # 【結果検証】: multistart が保持され既存フィールドが崩れないこと
    # 【期待値確認】: interfaces.py L84-87 の追加フィールド定義に一致
    assert metrics.multistart == {
        "n": 8,
        "n_basins": 1,
        "n_diverged": 0,
    }  # 【確認内容】: multistart メタ情報が Mapping のまま保持される 🔵
    assert metrics.rwp == pytest.approx(1.0)  # 【確認内容】: 既存フィールド rwp の保持が崩れない 🔵
    assert metrics.evidence == {}  # 【確認内容】: 既存フィールド evidence の既定 {} が不変 🔵


def test_xraylib_mu_calculator_satisfies_mu_calculator_protocol():
    # 【テスト目的】: XraylibMuCalculator が MuCalculator Protocol の構造的契約を満たすことを確認 (N-09)
    # 【テスト内容】: インスタンスが mu_t メソッドを持ち MuCalculator へ代入可能であることを検証
    # 【期待される動作】: hasattr/callable が成立し交換境界 (Protocol) が確立する (REQ-019)
    # 🟡 信頼性: 要件定義 2.6 / REQ-019 / interfaces.py L69-76。構造的適合の検証手段は妥当な推測

    # 【テストデータ準備】: μt 計算の交換境界 (Protocol) が確立していることを代表
    # 【初期条件設定】: スタブ実装をインスタンス化 (実行結果の検証は E-04)
    x = XraylibMuCalculator()

    # 【結果検証】: 構造的部分型 (duck typing) として mu_t シグネチャを備えること
    # 【期待値確認】: @runtime_checkable を課さないため hasattr/呼出可能性で確認
    assert hasattr(x, "mu_t")  # 【確認内容】: mu_t メソッドが存在する 🟡
    assert callable(x.mu_t)  # 【確認内容】: mu_t が呼び出し可能である 🟡
    calc: MuCalculator = x  # 【確認内容】: MuCalculator への代入が型エラーにならない (静的境界) 🟡
    assert calc is x  # 【確認内容】: 代入後も同一インスタンスを指す 🟡


def test_model_reexports_cell_symbols_in_dunder_all():
    # 【テスト目的】: model パッケージから新 5 シンボルが re-export され __all__ に収載されることを確認 (N-10)
    # 【テスト内容】: tsumugin.model 経由の解決と __all__ 収載を検証
    # 【期待される動作】: model/__init__.py で import + __all__ 追加済み
    # 🔵 信頼性: 要件定義 2.7 / __init__.py に依拠

    # 【テストデータ準備】: 後続タスク (TASK-0026/0027/0029) が公開 API 経由で参照する経路を代表
    # 【初期条件設定】: model パッケージをモジュールとして取得
    import tsumugin.model as m

    # 【結果検証】: 5 シンボルすべて解決可能かつ __all__ に収載されていること
    # 【期待値確認】: 要件定義 2.7 の re-export スコープ (top-level 昇格はテストしない)
    assert m.CellLayer is CellLayer  # 【確認内容】: CellLayer が解決可能 🔵
    assert m.BeamConfig is BeamConfig  # 【確認内容】: BeamConfig が解決可能 🔵
    assert m.CellConfig is CellConfig  # 【確認内容】: CellConfig が解決可能 🔵
    assert m.MuCalculator is MuCalculator  # 【確認内容】: MuCalculator が解決可能 🔵
    assert m.XraylibMuCalculator is XraylibMuCalculator  # 【確認内容】: スタブが解決可能 🔵
    for name in ("CellLayer", "BeamConfig", "CellConfig", "MuCalculator", "XraylibMuCalculator"):
        assert name in m.__all__  # 【確認内容】: 各シンボルが __all__ に収載 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（エラーハンドリング）
# ---------------------------------------------------------------------------


def test_cell_layer_is_frozen():
    # 【テスト目的】: CellLayer のフィールド再代入が禁止されることを確認 (E-01)
    # 【テスト内容】: thickness_mm へ再代入を試みる
    # 【期待される動作】: dataclasses.FrozenInstanceError が送出される
    # 🔵 信頼性: 要件定義 3 frozen 制約 / test_model.py の frozen 検証パターンに依拠

    # 【テストデータ準備】: セル層設定を後から書き換える誤用の防御を検証する対象を用意
    # 【初期条件設定】: 必須 3 フィールドのみで生成した Be 窓層
    cl = CellLayer("window", "Be", 0.5)

    # 【結果検証】: 再代入で FrozenInstanceError が送出されること
    # 【期待値確認】: frozen=True では属性再代入が禁止され変更は新インスタンス生成へ強制される
    with pytest.raises(FrozenInstanceError):
        cl.thickness_mm = 0.6  # type: ignore[misc]  # 【確認内容】: frozen のため再代入不可 🔵


def test_beam_config_is_frozen():
    # 【テスト目的】: BeamConfig のフィールド再代入が禁止されることを確認 (E-02)
    # 【テスト内容】: wavelength へ再代入を試みる
    # 【期待される動作】: dataclasses.FrozenInstanceError が送出される
    # 🔵 信頼性: 要件定義 3 frozen 制約に依拠

    # 【テストデータ準備】: ビーム条件を後から書き換える誤用の防御を検証する対象を用意
    # 【初期条件設定】: 波長のみ指定したビーム条件
    bc = BeamConfig(wavelength=0.7)

    # 【結果検証】: 再代入で FrozenInstanceError が送出されること
    # 【期待値確認】: frozen=True のため再代入不可でビーム条件の一貫性を破壊しない
    with pytest.raises(FrozenInstanceError):
        bc.wavelength = 0.8  # type: ignore[misc]  # 【確認内容】: frozen のため再代入不可 🔵


def test_cell_config_is_frozen():
    # 【テスト目的】: CellConfig のフィールド再代入が禁止されることを確認 (E-03)
    # 【テスト内容】: mu_t_calc へ再代入を試みる
    # 【期待される動作】: dataclasses.FrozenInstanceError が送出される
    # 🔵 信頼性: 要件定義 3 frozen 制約に依拠

    # 【テストデータ準備】: μt を後から直接代入する誤用の防御 (更新は新インスタンス生成へ強制)
    # 【初期条件設定】: geometry のみ指定した最小の透過セル構成
    cc = CellConfig("transmission")

    # 【結果検証】: 再代入で FrozenInstanceError が送出されること
    # 【期待値確認】: frozen=True のため再代入不可で吸収補正入力の一貫性を破壊しない
    with pytest.raises(FrozenInstanceError):
        cc.mu_t_calc = 1.5  # type: ignore[misc]  # 【確認内容】: frozen のため再代入不可 🔵


def test_xraylib_mu_calculator_mu_t_raises_not_implemented():
    # 【テスト目的】: XraylibMuCalculator.mu_t が M3 未実装として NotImplementedError を出すことを確認 (E-04)
    # 【テスト内容】: スタブの mu_t を CellConfig 付きで呼び出す (TC-207-07)
    # 【期待される動作】: NotImplementedError を送出する (沈黙した誤値を返さない fail-loud)
    # 🔵 信頼性: 要件定義 2.6/4.4 / REQ-019 / TC-207-07 / interfaces.py L75-76 に依拠

    # 【テストデータ準備】: 最小 CellConfig を用意 (geometry のみ)
    # 【初期条件設定】: M3 では xraylib 連携が未実装である状況を再現 (REQ-403 コア依存 numpy のみ)
    config = CellConfig(geometry="transmission")

    # 【実際の処理実行】: 未実装スタブの mu_t を呼び出す
    # 【処理内容】: XraylibMuCalculator().mu_t(config)
    # 【結果検証】: NotImplementedError が送出されること
    with pytest.raises(NotImplementedError):  # 【確認内容】: 未実装機能は明示エラーで拒否 🔵
        XraylibMuCalculator().mu_t(config)


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（最小値、最大値、null 等）
# ---------------------------------------------------------------------------


def test_beam_config_all_defaults():
    # 【テスト目的】: 引数なし生成 BeamConfig() が既定 (None/None/None) で成立することを確認 (B-01)
    # 【テスト内容】: 全フィールド既定値での縮退生成を検証
    # 【期待される動作】: すべて既定値でも frozen 値オブジェクトとして生成可能
    # 🔵 信頼性: 要件定義 2.2/4.3 / interfaces.py L54-56 に依拠

    # 【テストデータ準備】: ビーム条件未指定のセル構成という縮退ケースを代表
    # 【初期条件設定】: 引数を一切指定せず生成 (全フィールド既定値付きの前提)
    bc = BeamConfig()

    # 【結果検証】: 既定値が interfaces.py の定義どおりであること
    # 【期待値確認】: wavelength/energy_kev/size_mm すべて None
    assert bc.wavelength is None  # 【確認内容】: 波長既定 None 🔵
    assert bc.energy_kev is None  # 【確認内容】: エネルギー既定 None 🔵
    assert bc.size_mm is None  # 【確認内容】: ビームサイズ既定 None 🔵


def test_cell_config_minimal_construction_defaults():
    # 【テスト目的】: geometry のみ指定した最小生成が既定 (()/None/None) で成立することを確認 (B-02)
    # 【テスト内容】: 位置必須 geometry のみで CellConfig を生成し既定値縮退を検証
    # 【期待される動作】: 追加フィールドが既定値のため最小構成で生成できる
    # 🔵 信頼性: 要件定義 2.3/4.3 / interfaces.py L63-66 に依拠

    # 【テストデータ準備】: 毛細管セル (層構成なし) という最小の器を代表
    # 【初期条件設定】: 層情報・ビーム条件・μt を持たない単純セル
    cc = CellConfig(geometry="capillary")

    # 【結果検証】: 生成成功かつ各既定値が interfaces.py の定義どおりであること
    # 【期待値確認】: layers=()/beam=None/mu_t_calc=None
    assert cc.geometry == "capillary"  # 【確認内容】: セル形状が指定どおり保持される 🔵
    assert cc.layers == ()  # 【確認内容】: layers 既定は空 tuple 🔵
    assert cc.beam is None  # 【確認内容】: beam 既定 None 🔵
    assert cc.mu_t_calc is None  # 【確認内容】: mu_t_calc 既定 None 🔵


def test_cell_layer_density_default_none():
    # 【テスト目的】: 任意フィールド density を省略した生成で既定 None に縮退することを確認 (B-03)
    # 【テスト内容】: 必須 3 フィールドのみで CellLayer を生成し density 既定を検証
    # 【期待される動作】: density 省略でクラッシュせず None に縮退する
    # 🔵 信頼性: 要件定義 2.1/4.3 / interfaces.py L47 に依拠

    # 【テストデータ準備】: 密度情報を持たない電極層の登録 (計算しない/未知) を代表
    # 【初期条件設定】: role/material/thickness_mm のみ指定
    layer = CellLayer(role="electrode", material="LiFePO4", thickness_mm=0.1)

    # 【結果検証】: density が既定 None、他フィールドは指定どおりであること
    # 【期待値確認】: 既定 None が interfaces.py L47 どおり
    assert layer.density is None  # 【確認内容】: 密度既定 None 🔵
    assert layer.role == "electrode"  # 【確認内容】: 役割が指定どおり保持される 🔵
    assert layer.material == "LiFePO4"  # 【確認内容】: 物質名が指定どおり保持される 🔵
    assert layer.thickness_mm == pytest.approx(0.1)  # 【確認内容】: 層厚が指定どおり保持される 🔵


def test_existing_temperature_kind_backward_compatible():
    # 【テスト目的】: kind Literal 拡張後も既存 kind "temperature" の生成が無改変で通ることを確認 (B-04)
    # 【テスト内容】: 既存テスト同型の temperature チャネル生成と value_for を検証
    # 【期待される動作】: Literal への末尾値追加が既存値の型・意味を狭めない (REQ-404)
    # 🔵 信頼性: 要件定義 2.4/4.3 / REQ-404 / channel.py に依拠

    # 【テストデータ準備】: M2 の高温モードが従来どおり temperature チャネルを構築する経路を再現
    # 【初期条件設定】: frame 0→300.0K の温度同期 (既存 tests/test_model_m2.py と同型の呼び出し)
    channel = ExternalChannel(kind="temperature", sync_map={0: 300.0})

    # 【結果検証】: 既存 kind の合法性・value_for 挙動が不変であること
    # 【期待値確認】: 後方互換 (kind 拡張の非破壊性) の smoke
    assert channel.kind == "temperature"  # 【確認内容】: 既存 kind が従来どおり合法値 🔵
    assert channel.value_for(0) == pytest.approx(300.0)  # 【確認内容】: value_for 挙動が不変 🔵


def test_refinement_metrics_minimal_construction_multistart_default_none():
    # 【テスト目的】: 既存キーワード生成が multistart 追加後も無改変で通ることを確認 (B-05)
    # 【テスト内容】: 既存 5 フィールドのみで RefinementMetrics を生成し後方互換と既定を検証
    # 【期待される動作】: 追加フィールドが末尾・既定 None のため既存呼び出しを壊さない (REQ-404)
    # 🔵 信頼性: 要件定義 2.5/4.3 / REQ-404 / hypothesis.py L14-22 に依拠

    # 【テストデータ準備】: マルチスタート非適用 (単発精密化) の既存経路を再現
    # 【初期条件設定】: 既存 RefinementMetrics 生成と同型の最小構成
    metrics = RefinementMetrics(rwp=1.0, gof=1.1, chi2=1.2, n_obs=100, n_params=5)

    # 【結果検証】: 生成成功かつ multistart 既定 None、既存既定が維持されること
    # 【期待値確認】: 既存の既定値が変わっていない
    assert metrics.multistart is None  # 【確認内容】: 追加フィールド multistart が既定 None 🔵
    assert metrics.evidence == {}  # 【確認内容】: 既存フィールド evidence の既定 {} が不変 🔵
    assert metrics.n_obs == 100  # 【確認内容】: 既存フィールド n_obs の保持が不変 🔵


def test_cell_config_empty_layers_asdict():
    # 【テスト目的】: layers=() (空 tuple) の CellConfig が asdict で安全に直列化されることを確認 (B-06)
    # 【テスト内容】: 最小構成 (geometry のみ) を asdict で直列化し展開結果を検証
    # 【期待される動作】: 空 tuple でも例外なく空 tuple へ展開され None フィールドはそのまま None
    # 🔵 信頼性: 要件定義 4.3 / TC-207-01。asdict は tuple 型を保持する (Python 仕様: 空 tuple → 空 tuple)

    # 【テストデータ準備】: 毛細管セルなど層情報を持たない構成の永続化を代表
    # 【初期条件設定】: 層なしセル (最小構成) のシリアライズ境界
    d = dataclasses.asdict(CellConfig(geometry="capillary"))

    # 【結果検証】: JSON 互換型のみの dict が返り空入力でクラッシュしないこと
    # 【期待値確認】: 非空 layers (N-06) と同じ展開規則で一貫 (tuple は tuple のまま保持)
    assert d == {
        "geometry": "capillary",
        "layers": (),  # dataclasses.asdict は tuple を list へ変換しない (Python 仕様) ため空 tuple を期待
        "beam": None,
        "mu_t_calc": None,
    }  # 【確認内容】: 空 tuple → 空 tuple、None フィールドはそのまま None 🔵


def test_all_four_new_channel_kinds_constructible():
    # 【テスト目的】: 追加した全 kind (voltage/current/capacity/composition) で生成可能なことを確認 (B-07)
    # 【テスト内容】: 4 新 kind すべてで ExternalChannel を生成し kind 保持と value_for を検証
    # 【期待される動作】: どの新 kind でも生成でき合法値として扱われる (REQ-007 の 4 種網羅)
    # 🔵 信頼性: 要件定義 2.4 / REQ-007 / interfaces.py L83-84 に依拠

    # 【テストデータ準備】: echem CSV マッパ (TASK-0029) が V/I/Q/x を各 kind で同期する経路を代表
    # 【初期条件設定】: kind Literal 拡張の全端点 (4 値) を明示的に網羅 (漏れ検出)
    kinds = ("voltage", "current", "capacity", "composition")

    for kind in kinds:
        # 【実際の処理実行】: 各新 kind でチャネルを生成し同期値を要求
        # 【処理内容】: ExternalChannel(kind=kind, sync_map={0: 1.0}).value_for(0)
        channel = ExternalChannel(kind=kind, sync_map={0: 1.0})

        # 【結果検証】: 生成成功・kind 保持・既存 kind と同じ同期挙動であること
        # 【期待値確認】: 4 新 kind すべてが Literal に含まれ生成可能
        assert channel.kind == kind  # 【確認内容】: 渡した kind がそのまま保持される 🔵
        assert channel.value_for(0) == pytest.approx(1.0)  # 【確認内容】: 同期挙動が既存 kind と一貫 🔵
