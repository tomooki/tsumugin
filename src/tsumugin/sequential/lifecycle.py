"""相ライフサイクル・ヒステリシス追跡 (仕様 §2 / interfaces.py L118-133 / TC-103 系)。

各相 (phase_ref) が「いつ出現 (birth) し、いつ消滅 (death) したか」を、フレーム列を通じて
ヒステリシス (連続 N フレームの存在/不在で確定) 付きで追跡する ``LifecycleTracker`` を提供する
(REQ-004 / REQ-201 / FR-305)。フレーム間ノイズによる相の点滅 (1〜2 フレームの偽出現/偽消失) を
抑制し、相の実在区間を安定同定する。乱数・I/O・外部状態を持たず、同一入力・同一 Config で
``finalize()`` 出力がビット同一になる (REQ-402 決定論)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from tsumugin.model.phase import PhaseLifecycle


@dataclass(frozen=True)
class LifecycleConfig:
    """ヒステリシス追跡の設定 (窓幅/存在判定下限)。

    【機能概要】: birth/death を確定する連続フレーム窓幅と、存在判定の wt_frac 下限を保持する不変設定。
    【実装方針】: interfaces.py L118-121 の既定値 (hysteresis=3 / presence_wt_frac=1e-3) に一致させる。
    【テスト対応】: test_lifecycle_config_defaults_frozen_and_reexport (N-06) を通す。
    🔵 信頼性レベル: interfaces.py L118-121 / CLAUDE.md frozen 規約に依拠。
    """

    hysteresis: int = 3  # 【確定窓幅】: 連続 N フレームの存在/不在で birth/death 確定 🔵 FR-305 (N は 🟡)
    presence_wt_frac: float = 1e-3  # 【存在判定下限】: wt_frac の存在閾値 (上位が present 判定に利用) 🟡


@dataclass
class _PhaseState:
    """1 相分の可変観測状態 (finalize までの途中集計)。

    【機能概要】: 相ごとの present/absent 連続ラン・確定済み birth/death・存在フレーム数を保持する内部状態。
    【実装方針】: 公開せず LifecycleTracker 内部でのみ使う。ヒステリシス判定を O(1) で逐次更新する。
    🔵 信頼性レベル: 仕様 §2 出力セマンティクス (連続開始フレーム記録) に依拠。
    """

    present_count: int = 0  # 【存在フレーム数】: confidence 分子 (present であったフレーム総数)
    birth_frame: int | None = None  # 【出現確定】: 連続 present が窓を満たした連続開始 frame
    death_frame: int | None = None  # 【消滅確定】: birth 後に連続 absent が窓を満たした不在連続の先頭 frame
    present_run: int = 0  # 【現在の present ラン長】: 連続 present フレーム数 (absent で 0 リセット)
    present_run_start: int | None = None  # 【present ラン先頭】: 現在の present 連続の開始 frame
    absent_run: int = 0  # 【現在の absent ラン長】: 連続 absent フレーム数 (present で 0 リセット)
    absent_run_start: int | None = None  # 【absent ラン先頭】: 現在の absent 連続の開始 frame


class LifecycleTracker:
    """相ごとの出現/消滅をヒステリシス付きで追跡するステートフル・トラッカー (REQ-004/201)。

    【機能概要】: 毎フレーム ``observe(frame_index, present_refs)`` を呼び相ごとの連続ランを更新し、
      終了時 ``finalize()`` で ``{phase_ref: PhaseLifecycle}`` を返す。death 確定前の窓内再出現は連続扱い。
    【実装方針】: 相ごとに _PhaseState を保持し、present/absent を逐次判定する状態機械として実装。
      birth 確定 (連続 N present) した相のみを出力に含め、点滅の偽出現を除去する (TC-103-03)。
    【テスト対応】: test_lifecycle.py 全 13 件 (正常系 6 / 異常系 3 / 境界値 4) を通す。
    🔵 信頼性レベル: interfaces.py L124-133 契約 / requirements §2 セマンティクスに依拠。
    """

    def __init__(self, *, config: LifecycleConfig = LifecycleConfig()) -> None:
        """トラッカーを構築する (キーワード専用 config)。

        【実装方針】: 設定を保持し、相状態 (初出順を保つ dict) と総観測フレーム数を空初期化する。
        🔵 信頼性レベル: interfaces.py L131 (キーワード専用 config) に依拠。
        @param config: ヒステリシス窓幅/存在判定下限 (既定 LifecycleConfig())
        """
        # 【設定保持】: hysteresis 窓幅を判定で参照する 🔵
        self._config = config
        # 【相状態辞書】: 初出順を保つ dict で相間非干渉の独立状態を保持 (決定論のため反復順は初出順) 🔵
        self._states: dict[str, _PhaseState] = {}
        # 【総観測フレーム数】: observe 呼び出し回数。confidence の分母 (存在フレーム率) となる 🟡
        self._total_frames = 0

    def observe(self, frame_index: int, present_refs: Sequence[str]) -> None:
        """1 フレーム分の存在相集合を取り込み、各相の present/absent ランを更新する。

        【機能概要】: present_refs に含まれる相は present、既登録で含まれない相は absent として逐次判定。
        【実装方針】: 初出相はここで登録し present 処理。既登録の非存在相のみ absent 処理する
          (未登録相に absent を蓄積しない)。呼び出しは frame_index 昇順を想定する。
        【テスト対応】: 全テストの観測ドライバ。birth/death/取り消しの状態遷移をここで進める。
        🔵 信頼性レベル: interfaces.py L132 / requirements §2 (連続ラン更新・戻り値なし) に依拠。
        @param frame_index: 当該フレーム番号 (昇順想定)
        @param present_refs: そのフレームで存在する相 ref の列
        """
        # 【総フレーム加算】: confidence の分母となる観測フレーム数を 1 増やす 🟡
        self._total_frames += 1

        # 【存在集合化】: present 判定を O(1) にし、初出相を登録する 🔵
        present_set = set(present_refs)
        for ref in present_refs:
            if ref not in self._states:
                # 【初出登録】: 初めて存在した相を初出順で登録 (以降 absent も追跡対象になる) 🔵
                self._states[ref] = _PhaseState()

        # 【全登録相の更新】: 既登録の各相を present/absent に振り分けて状態遷移させる 🔵
        for ref, state in self._states.items():
            if ref in present_set:
                self._mark_present(state, frame_index)
            else:
                self._mark_absent(state, frame_index)

    def _mark_present(self, state: _PhaseState, frame_index: int) -> None:
        """相を present として更新し、連続 present が窓に達したら birth を確定する。

        【実装方針】: present ラン継続 (先頭 frame は連続開始で記録)、absent ランはリセット (death 取り消し)。
          birth 未確定かつ present ランが hysteresis 以上で birth 成立 (記録は連続開始フレーム)。
        【テスト対応】: TC-103-01 (birth=連続開始) / TC-103-03,04 (点滅抑制/death 取り消し) を支える。
        🔵 信頼性レベル: requirements §2 birth_frame / death 取り消しセマンティクスに依拠。
        """
        # 【present ラン開始検出】: 直前が absent (ラン 0) なら新しい連続の先頭フレームを記録 🔵
        if state.present_run == 0:
            state.present_run_start = frame_index
        state.present_run += 1
        state.present_count += 1
        # 【absent ランリセット】: 窓未満の不在は present 復帰で連続扱いに戻す (REQ-201 death 取り消し) 🔵
        state.absent_run = 0
        state.absent_run_start = None
        # 【birth 確定】: 連続 present が窓 (hysteresis) に達したら連続開始フレームで birth を確定 🔵
        if state.birth_frame is None and state.present_run >= self._config.hysteresis:
            state.birth_frame = state.present_run_start

    def _mark_absent(self, state: _PhaseState, frame_index: int) -> None:
        """相を absent として更新し、birth 済み相の連続 absent が窓に達したら death を確定する。

        【実装方針】: absent ラン継続 (先頭 frame は不在連続の開始で記録)、present ランはリセット。
          birth 済みかつ death 未確定で absent ランが hysteresis 以上のとき death 成立 (記録は不在連続の先頭)。
        【テスト対応】: TC-103-02 (death=不在先頭) / E-03 (窓充足で取り消さない) を支える。
        🔵 信頼性レベル: requirements §2 death_frame / REQ-201 の対偶に依拠。
        """
        # 【absent ラン開始検出】: 直前が present (ラン 0) なら不在連続の先頭フレームを記録 🔵
        if state.absent_run == 0:
            state.absent_run_start = frame_index
        state.absent_run += 1
        # 【present ランリセット】: 存在連続を断つ 🔵
        state.present_run = 0
        state.present_run_start = None
        # 【death 確定】: birth 済み・death 未確定で連続 absent が窓に達したら不在先頭で death を確定 🔵
        if (
            state.birth_frame is not None
            and state.death_frame is None
            and state.absent_run >= self._config.hysteresis
        ):
            state.death_frame = state.absent_run_start

    def finalize(self) -> Mapping[str, PhaseLifecycle]:
        """観測列を相ごとの PhaseLifecycle に縮約して返す。

        【機能概要】: birth が確定した相のみを対象に、birth/death と存在フレーム率 (confidence) を確定する。
        【実装方針】: birth 未確定 (点滅の偽出現・単一フレーム等) の相はキーに含めない (TC-103-03/EDGE-101)。
          confidence = 存在フレーム数 / 総観測フレーム数 (全存在で 1.0、空観測は空 Mapping)。
        【テスト対応】: 全 13 件の検証点。空観測→{}、点滅→キーなし、部分存在→存在フレーム率。
        🔵 信頼性レベル: requirements §2 出力セマンティクス / confidence 算出式は 🟡 (存在フレーム率で固定)。
        @returns: {phase_ref: PhaseLifecycle} (birth 確定相のみ、初出順)
        """
        # 【結果構築】: birth 確定相のみを初出順で縮約する 🔵
        result: dict[str, PhaseLifecycle] = {}
        for ref, state in self._states.items():
            # 【birth 未確定除外】: 連続 present が窓に届かなかった相は出力に含めない (点滅抑制) 🔵
            if state.birth_frame is None:
                continue
            # 【存在フレーム率】: 分母は総観測フレーム数。observe があれば必ず正で 0 除算しない 🟡
            confidence = state.present_count / self._total_frames if self._total_frames else 0.0
            result[ref] = PhaseLifecycle(
                birth_frame=state.birth_frame,
                death_frame=state.death_frame,
                confidence=confidence,
            )
        return result
