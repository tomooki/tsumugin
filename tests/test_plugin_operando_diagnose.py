"""③ Claude Code プラグイン (operando-diagnose skill/command) の契約テスト (乾式レビュー)。

skill/command が存在し、参照する ② MCP ツールが実在し、権限境界と**この skill の存在理由**
(Rwp では原理的に検出できない相集合の誤り) が明記されていることを検証する。実 LLM は手動検証。

**skill は「実行者 (③) への指示」であり、誤った指示は実装バグと同等に有害である**。
設計: `docs/design/operando-diagnosis/architecture.md` (§3 判断項目 J1-J8, §4.5 到達可能性)。
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

from tsumugin.mcp.operando_diag_tools import repair_frames
from tsumugin.mcp.tools import MCP_TOOLS

_PLUGIN = Path("plugins/tsumugin")
_SKILL = _PLUGIN / "skills" / "operando-diagnose" / "SKILL.md"
_COMMAND = _PLUGIN / "commands" / "operando-diagnose.md"
_INSITU_SKILL = _PLUGIN / "skills" / "insitu" / "SKILL.md"
_PLAYBOOK = Path("docs/tasks/operando-diagnosis/AGENT_PLAYBOOK.md")

# 本 skill が駆動する ② 診断ツール (architecture.md §2 の 4 ツール)
_DIAG_TOOLS = ("assess_data_quality", "check_phase_set", "repair_frames", "residual_report")

# `repair_frames` の呼び出し例を載せている全ドキュメント (skill 2 種 + 非 Claude 向け playbook)
_REPAIR_FRAMES_DOCS = (_SKILL, _INSITU_SKILL, _PLAYBOOK)

# `appearances` を「読む/監査する」旨の指示 (語は変わりうるので動詞は選択肢で受ける)
_APPEARANCES_AUDIT = re.compile(r"`appearances`[^\n]{0,40}(監査|読む|読み|確認)")


def _call_sites(text: str, func: str) -> list[str]:
    """``func(`` の呼び出し例を**括弧の対応をとって**丸ごと抜き出す (複数行の呼び出しに対応)。

    表 (``| `repair_frames` | ... |``) や散文中の言及は ``func(`` に一致しないので拾わない —
    検証対象は「③ がそのまま真似する呼び出し例」だけである。
    """
    sites: list[str] = []
    for m in re.finditer(re.escape(func) + r"\(", text):
        start = m.end()
        depth = 1
        for i in range(start, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    sites.append(text[start:i])
                    break
        else:  # pragma: no cover - 閉じ括弧の無い壊れた例
            sites.append(text[start:])
    return sites


def _table_rows(text: str, heading: str) -> list[list[str]]:
    """``heading`` 節の markdown 表を ``[セル, ...]`` の行リストへ (区切り行/ヘッダは除く)。"""
    body = text.split(heading, 1)[1].split("\n## ", 1)[0]
    rows: list[list[str]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= {"-", ":"} and c for c in cells):  # 区切り行
            continue
        rows.append(cells)
    return rows


def test_operando_diagnose_skill_and_command_exist():
    assert _SKILL.exists()
    assert _COMMAND.exists()


def test_skill_references_only_existing_mcp_tools():
    """手順表が挙げる ② ツールはすべて実在すること (存在しないツマミを ③ に指示しない)。

    §4.5 到達可能性: ① に実装済でも ② に配線されていない機能を skill に書くと、③ は呼べない
    ツマミを指示され続ける (`auto_freeze_minor_cells`/`warm_start_fractions` が実際にそうだった)。
    """
    text = _SKILL.read_text(encoding="utf-8")
    body = text.split("## 使う MCP ツール", 1)[1].split("## ", 1)[0]
    names = re.findall(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", body, flags=re.MULTILINE)
    assert len(names) >= 4, f"ツール表を抽出できていない: {names}"
    unknown = [n for n in names if n not in MCP_TOOLS]
    assert not unknown, f"skill が実在しない MCP ツールを指示している: {unknown}"


def test_skill_drives_the_four_diagnosis_tools():
    text = _SKILL.read_text(encoding="utf-8")
    for tool in _DIAG_TOOLS:
        assert tool in text, f"operando-diagnose SKILL が {tool} に言及していない"
        # residual_report は auto_rietveld/sequential_rietveld の出力同梱が主経路だが
        # 単独ツールとしても登録されている
        assert tool in MCP_TOOLS, f"{tool} が MCP_TOOLS 未登録"


def test_skill_states_why_rwp_is_insufficient():
    """本 skill の存在理由 = Rwp では原理的に検出できない誤りが実在したこと。

    これが抜けると skill は「もう一つの精密化手順」に退化する。実データでは Rwp 8% (良好) の
    まま tetragonal が monoclinic の強度を肩代わりし非物理な描像を生成し、発見者は人間だった。
    """
    text = _SKILL.read_text(encoding="utf-8")
    assert "Rwp が良くても信じない" in text, "Rwp を信じない旨の明示が無い"
    assert "肩代わり" in text, "計量の近い相が強度を肩代わりする機序の説明が無い"
    assert "check_phase_set" in text, "相集合の完全性確認 (J5) が手順に無い"
    # Rwp 単独での結論を明示的に禁じていること
    assert re.search(r"Rwp が良いことを根拠に相集合を正しいと結論しない", text), (
        "禁止事項に Rwp 単独での相集合判定の禁止が無い"
    )


def test_skill_documents_propose_not_apply_boundary():
    """提案≠適用: 構造改訂・相集合変更はユーザー承認を挟むこと (M8 §4.5 継承)。"""
    text = _SKILL.read_text(encoding="utf-8")
    assert "提案≠適用" in text
    assert "承認" in text
    assert "可逆" in text or "棄却" in text, "受理されない場合の可逆棄却 (P2) の記述が無い"
    assert "原理的に不可" in text, "相の欠落が自律検出できないことが権限境界に無い"


def test_skill_warns_against_adding_phases_to_absorb_residual():
    """`baseline_numerator_fraction` が大きい = データ側の問題。相追加は誤魔化しになる。"""
    text = _SKILL.read_text(encoding="utf-8")
    assert "baseline_numerator_fraction" in text
    assert "残差を説明するためだけに相を足さない" in text


def test_command_references_skill_and_gates_on_data_quality():
    text = _COMMAND.read_text(encoding="utf-8")
    assert "operando-diagnose" in text
    assert "assess_data_quality" in text
    assert "check_phase_set" in text
    assert "承認" in text


# ===========================================================================
# ドキュメント整合の恒久ガード (誤った指示 = 実装バグと同等に有害)
# ===========================================================================


@pytest.mark.parametrize("doc", _REPAIR_FRAMES_DOCS, ids=lambda p: p.as_posix())
def test_repair_frames_examples_always_pass_two_theta_limits(doc):
    """ガード1: `repair_frames` の呼び出し例は必ず `two_theta_limits` を伴うこと。

    省略すると修復試行だけが全域で走り、採用規則 `rwp_after < rwp_before - rwp_tol` が
    **系列側と異なるデータ域の Rwp を比較**する。**例外は出ず、無効な比較のまま「修復成功」が
    採用される** ——「呼べるが黙って間違う」は「呼べない」より悪い (architecture.md §4.5 #2)。
    ③ は例をそのまま真似するので、例から欠けることが即ちこの失敗の再導入になる。
    """
    text = doc.read_text(encoding="utf-8")
    sites = _call_sites(text, "repair_frames")
    assert sites, f"{doc}: repair_frames の呼び出し例が無い (③ が真似する例が必要)"
    bad = [s for s in sites if "two_theta_limits" not in s]
    assert not bad, (
        f"{doc}: two_theta_limits の無い repair_frames 呼び出し例がある: {bad}。"
        "系列を精密化したのと同じレンジを必ず渡すこと (異なるデータ域の Rwp 比較は無効)。"
    )


@pytest.mark.parametrize("doc", _REPAIR_FRAMES_DOCS, ids=lambda p: p.as_posix())
def test_sequential_rietveld_examples_always_pass_warm_start_fractions(doc):
    """ガード8: `sequential_rietveld` の呼び出し例は必ず `warm_start_fractions=True` を伴うこと。

    **既定は False** (`SequentialConfig.warm_start_fractions`)。省略した例をそのまま真似すると、
    相分率が等分 seed (2 相なら 0.500/0.500) に張り付いたまま系列が回る (Issue #82/#96)。
    しかも **Rwp は平凡なまま** (実測 8.4-8.5%) で、GOF も validity も何も言わない —
    `check_phase_set` の `seed_pinned` でしか見えない。例から欠けることが即ちこの失敗の再導入で
    あり、②「呼べるが黙って間違う」の再生産になる (ガード1 の `two_theta_limits` と同じ規律)。

    呼び出し例を持たない文書 (散文で言及するのみ) は対象外 — 検証するのは「③ がそのまま真似する例」。
    """
    text = doc.read_text(encoding="utf-8")
    sites = _call_sites(text, "sequential_rietveld")
    if not sites:
        pytest.skip(f"{doc}: sequential_rietveld の呼び出し例が無い (散文の言及のみ)")
    bad = [s for s in sites if not re.search(r"warm_start_fractions\s*=\s*True", s)]
    assert not bad, (
        f"{doc}: warm_start_fractions=True の無い sequential_rietveld 呼び出し例がある: {bad}。"
        "既定 False なので、省略した例を真似した ③ は分率が seed に張り付いた系列を"
        "「正常」として読む (Rwp は平凡なまま = 気づけない)。"
    )


def _top_level_kwargs(site: str) -> list[str]:
    """呼び出し例の**トップレベル** kwarg 名を抜く (入れ子の dict/list 内は見ない)。"""
    names: list[str] = []
    depth = 0
    for m in re.finditer(r"[\(\[\{\)\]\}]|(\w+)\s*=(?!=)", site):
        tok = m.group(0)
        if tok in "([{":
            depth += 1
        elif tok in ")]}":
            depth -= 1
        elif depth == 0 and m.group(1):
            names.append(m.group(1))
    return names


@pytest.mark.parametrize("doc", _REPAIR_FRAMES_DOCS, ids=lambda p: p.as_posix())
def test_repair_frames_documented_kwargs_exist_in_the_real_signature(doc):
    """ガード4: 呼び出し例の kwarg がすべて `repair_frames` の実シグネチャに在ること。

    **文書が「ツールが提供できない呼び出し」を指示してはならない**。③ は例をそのまま真似するので、
    実在しない引数を書けば `TypeError` が MCP 境界を越える (= ③ にとって回復不能なハード失敗)。

    実際に起きた (Issue #96 レビュー HIGH-1): 3 文書すべてが「`seed_pinned_frames[].frame` を
    `repair_frames` で再フィット」と指示していたが、**当時の `repair_frames` にフレームを指定する
    引数は無かった**。しかも省略時の自動検出は Rwp/分率のジャンプしか見ず、seed 張り付きは
    定義上「平坦」なのでどの閾値でも拾えない — ③ は「直すものは無い」と告げられる。
    """
    text = doc.read_text(encoding="utf-8")
    params = inspect.signature(repair_frames).parameters
    sites = _call_sites(text, "repair_frames")
    assert sites, f"{doc}: repair_frames の呼び出し例が無い"
    for site in sites:
        for kw in _top_level_kwargs(site):
            assert kw in params, (
                f"{doc}: repair_frames の呼び出し例が実在しない引数 {kw!r} を指示している "
                f"(実シグネチャ: {sorted(params)})。③ は例をそのまま真似する — "
                "呼べない指示は TypeError を境界へ漏らす。"
            )


@pytest.mark.parametrize("doc", _REPAIR_FRAMES_DOCS, ids=lambda p: p.as_posix())
def test_pinned_frame_instruction_is_executable_via_target_frames(doc):
    """ガード5: 張り付き/凍結フレームの修復指示が**実行可能**であること (Issue #96 レビュー HIGH-1)。

    `check_phase_set` の `seed_pinned_frames`/`frozen_fraction_frames` に言及して修復を促す文書は、
    **`target_frames` を使う呼び出し例**を持たねばならない。自動検出 (`rwp_delta`/`frac_delta`) は
    張り付きに**原理的に到達できない**:

    - 張り付き区間の Rwp は平凡 (実測 8.4-8.5%) → `rwp_abs` では拾えない。
    - 区間内では局所中央値が当該フレームの Rwp そのもの → `rwp_delta` をどれだけ下げても届かない。
    - 分率も平坦 → `frac_delta` は逆に**健全な**近傍を拾う。

    よって `target_frames` 無しの指示は「呼べるが黙って何もしない」= ③ に「異常なし」と
    答えることになる (② の最悪の失敗様態)。
    """
    text = doc.read_text(encoding="utf-8")
    if "seed_pinned" not in text and "frozen_fraction" not in text:
        pytest.skip(f"{doc}: 張り付き/凍結に言及していない")

    assert "target_frames" in inspect.signature(repair_frames).parameters, (
        "repair_frames に target_frames が無い — 文書の指示が実行不能になる"
    )
    targeted = [s for s in _call_sites(text, "repair_frames") if "target_frames" in s]
    assert targeted, (
        f"{doc}: 張り付き/凍結フレームに言及しながら `target_frames` を使う repair_frames の"
        "呼び出し例が無い。自動検出は「平坦」な張り付きに原理的に到達できないため、"
        "この指示は実行不能 (③ は repairs=[] を「直すものは無い」と読む)。"
    )
    # 対象の出所 (check_phase_set の出力) が例に現れていること = §4.5 到達可能性。
    # 例が複数行にまたがるため `[\s\S]` で改行を跨いで探す (`[^\n]` では re.S でも跨げない)。
    assert re.search(r"seed_pinned_frames|frozen_fraction_frames", "\n".join(targeted)) or re.search(
        r"(seed_pinned_frames|frozen_fraction_frames)[\s\S]{0,400}target_frames", text
    ), (
        f"{doc}: `target_frames` に渡す値が check_phase_set の出力から来ることが例から読めない "
        "(③ は各引数を『どの ② ツールの出力から作るか』が言えなければ組み立てられない)。"
    )


@pytest.mark.parametrize("doc", _REPAIR_FRAMES_DOCS, ids=lambda p: p.as_posix())
def test_docs_warn_against_repairing_pinned_frames_one_at_a_time(doc):
    """ガード6: 「疑わしいフレームは 1 回で全て渡す」旨があること (両隣も同欠陥の罠)。

    指定フレームは互いに warm-start 元から除外される (`repair._nearest_good`)。裏を返せば
    **1 フレームずつ呼ぶと除外が効かず**、両隣も張り付いた区間 (実測 125-130 の 6 連続) で
    欠陥を持つ隣から種を貰い、欠陥を引き継いだまま「修復成功」を報告する。
    """
    text = doc.read_text(encoding="utf-8")
    if "target_frames" not in text:
        pytest.skip(f"{doc}: target_frames に言及していない")
    assert re.search(r"1 回の?呼び出しで(全て|すべて)渡す|1 回で(全て|すべて)渡す", text), (
        f"{doc}: `target_frames` を教えながら「1 回の呼び出しで全て渡す」注意が無い。"
        "1 つずつ呼ぶと両隣も同欠陥の区間で欠陥を持つ隣から warm-start する。"
    )


@pytest.mark.parametrize("doc", _REPAIR_FRAMES_DOCS, ids=lambda p: p.as_posix())
def test_docs_state_that_phase_fractions_is_scale_not_weight_percent(doc):
    """ガード7: `phase_fractions` を wt% と取り違えない指示があること (Issue #96 レビュー HIGH-2)。

    `phase_fractions` は **Scale** であって重量分率ではない。単位胞質量が相間で異なると乖離する
    (実測 K2Mn[Fe(CN)6]: cubic 1103.4 / tetra 517.8 amu → **65.6 Scale% は実は 47.2 wt% = 2.1x**)。
    ③ が知らなければ**報告する定量値がそのまま 2.1x 誤る** — Rwp も validity も何も言わない。
    ② が値を返すだけでは足りず、「どちらを出版値に使うか」が手順書に無ければ ③ は Scale を使う。
    """
    text = doc.read_text(encoding="utf-8")
    assert "phase_weight_fractions" in text, (
        f"{doc}: 出版値 `phase_weight_fractions` に言及していない (③ は Scale を wt% として報告する)"
    )
    assert "phase_weight_fraction_esd" in text, f"{doc}: 重量分率の esd に言及していない (出版に必須)"
    assert re.search(r"phase_fractions[^\n]{0,120}(Scale|scale)", text), (
        f"{doc}: `phase_fractions` が Scale であることの明示が無い"
    )
    # ② が実際にそのキーを返すこと (文書だけ先行して「呼べない指示」にしない)
    from tsumugin.mcp.insitu_tools import seq_result_to_dict as _seq  # noqa: PLC0415

    src = inspect.getsource(_seq)
    for key in ("phase_weight_fractions", "phase_weight_fraction_esd", "cell_esd"):
        assert key in src, f"② の seq_result_to_dict が {key} を返していないのに文書が指示している"


# 「Scale は転移の追跡に使ってよい」という**誤った指示**の指紋 (Issue #96 レビュー第4巡 HIGH)。
# 3 文書すべてのキー表に `| phase_fractions | **Scale** の正規化値 | 相対比較のみ (新相の有意性・
# **転移の追跡**) |` と書かれていた。これは**偽**である: 転移推定 (`estimate_transition`) は
# 絶対レベル 0.50/0.10 の交差軸値を返すため、y 軸を Scale から wt% に替えると答えが動く。
# 実測では同じ精密化から Scale が「midpoint 9.515 h」、wt% が「転移なし」を出した。
#
# 否定語の探索だけ `[\s\S]` (改行可) なのは、否定が次行に折り返しても**否定は否定**だから。
# 前方の距離は `[^\n]` (同一行) — 表の行も散文も `phase_fractions` と「転移の追跡」は同じ行に
# あり、改行を跨がせると無関係な段落同士が誤って結び付く。
_SCALE_FOR_TRANSITION_OK = re.compile(
    r"phase_fractions[^\n]{0,160}転移の追跡(?![\s\S]{0,40}(?:使えない|使わない|不可))"
)


@pytest.mark.parametrize("doc", _REPAIR_FRAMES_DOCS, ids=lambda p: p.as_posix())
def test_docs_do_not_bless_scale_for_transition_tracking(doc):
    """ガード8: `phase_fractions` (Scale) を**転移の追跡に使ってよい**と書いていないこと。

    `parametric_fit` は Scale を消費して onset/midpoint という**出版値を導出する**。転移推定は
    絶対レベル (0.50/0.10) の交差軸値を返すので、「Scale は相対比較なら安全」は**転移には
    当てはまらない**。3 文書のキー表がそろって「相対比較のみ (…転移の追跡)」と Scale を
    祝福しており、③ はそれを信じて Scale 由来の転移温度を報告できてしまった。

    **誤った手順書は実装バグと同等に有害** (CLAUDE.md) — ② を直しても手順書が Scale を
    勧めていれば ③ は `basis="scale"` を明示的に選びに行ける。
    """
    text = doc.read_text(encoding="utf-8")
    bad = _SCALE_FOR_TRANSITION_OK.search(text)
    assert bad is None, (
        f"{doc}: `phase_fractions` (Scale) を「転移の追跡」に使ってよいと書いている "
        f"({bad.group(0)!r})。転移推定は絶対レベル 0.50/0.10 の交差なので basis で答えが変わる "
        "(実測: 同じ fit で Scale=midpoint 9.515 h / wt%=転移なし)"
    )


@pytest.mark.parametrize("doc", _REPAIR_FRAMES_DOCS, ids=lambda p: p.as_posix())
def test_docs_tell_which_basis_to_report_transitions_from(doc):
    """ガード9: 転移温度を**どの基準で取り・報告するか**が書かれていること。

    「Scale を使うな」だけでは ③ は代わりに何をすべきか分からない。② に `basis` があっても
    手順書に無ければ ③ は使わない (Issue #97: 露出していない機能は無いのと同じ)。
    """
    text = doc.read_text(encoding="utf-8")
    if "parametric_fit" not in text:
        pytest.skip(f"{doc}: parametric_fit に言及していない")
    assert "fraction_basis" in text, (
        f"{doc}: `parametric_fit` を教えているが返り値の `fraction_basis` "
        "(どの基準で出したか) の確認を指示していない — ③ は Scale 由来の数字を出版値と信じる"
    )
    assert re.search(r'basis\s*=\s*"weight"|basis="weight"|既定[^\n]{0,30}weight', text), (
        f"{doc}: 転移を重量分率基準で取ること (`basis=\"weight\"` が既定) の指示が無い"
    )
    # ② が実際にその引数/キーを持つこと (文書だけ先行して「呼べない指示」にしない)
    from tsumugin.mcp.insitu_tools import parametric_fit as _pf  # noqa: PLC0415

    sig = inspect.signature(_pf)
    assert "basis" in sig.parameters, "② parametric_fit に basis 引数が無いのに文書が指示している"
    assert sig.parameters["basis"].default == "weight", (
        "② parametric_fit の basis 既定が 'weight' でない — 文書の「既定で出版値」が嘘になる"
    )


@pytest.mark.parametrize("skill", (_SKILL, _INSITU_SKILL), ids=lambda p: p.as_posix())
def test_skill_authority_tables_agree_on_autonomous_phase_addition(skill):
    """ガード2: 2 つの skill の権限境界表が「新相の自動追加」で矛盾しないこと。

    実装は `phase_id` 有効時、**ユーザー承認なしに**受理基準 (frac∧Rwp∧validity) だけで相を
    追加する (`insitu.engine._accept_new_phase`)。「相追加には常に承認が要る」と書く skill が
    あると、③ は**実際に起きた相追加を監査しない** — 追加された相の化学的妥当性は受理基準の
    視野の外 (残差の説明力しか見ない) なので、監査の欠落は誤った相の見逃しに直結する。

    脆くしないため、語ではなく**主張**を見る: 「新相」の行の決定論コア列が (a) 自律採用すると
    言い (b) 受理基準を根拠に挙げ (c) ❌ (=コアは行わない) でないこと。加えて ③ 側に
    `appearances` の監査指示があること。
    """
    text = skill.read_text(encoding="utf-8")
    rows = [r for r in _table_rows(text, "## 権限境界") if "新相" in r[0]]
    assert rows, f"{skill}: 権限境界表に「新相」の追加に関する行が無い"
    for cells in rows:
        core = cells[1]
        assert "自律" in core and "受理基準" in core, (
            f"{skill}: 新相追加が受理基準による自律採用だと書かれていない: {cells!r}。"
            "実装は承認なしに追加する — 表がそれを隠すと ③ が監査をやめる。"
        )
        assert "❌" not in core, (
            f"{skill}: 新相追加をコアが行わない (❌) と書いている: {cells!r}。"
            "実装は phase_id 有効時に自律追加する (常に承認必須ではない)。"
        )
    assert _APPEARANCES_AUDIT.search(text), (
        f"{skill}: 自動追加された相 (`appearances`) を ③ が監査/確認する指示が無い。"
        "自律追加を許す以上、事後監査が唯一の歯止めである。"
    )


@pytest.mark.parametrize(
    "marker",
    [
        pytest.param(re.compile(r"Rwp が良くても信じない"), id="J5: Rwp が良くても信じない"),
        pytest.param(re.compile(r"J5"), id="J5 の見出し"),
        pytest.param(_APPEARANCES_AUDIT, id="appearances の監査"),
        pytest.param(re.compile(r"残差を説明するためだけに相を足さない"), id="相の水増し禁止"),
    ],
)
def test_playbook_and_skill_share_safety_critical_instructions(marker):
    """ガード3: playbook (`内容は本書と同一` と宣言) と operando-diagnose skill が乖離しないこと。

    playbook は非 Claude ハーネス向けの同一内容版であり、**片方にしか無い安全指示は、その
    ハーネスでだけ失敗が再現する**ことを意味する。安全上の要 (J5/Rwp を信じない・`appearances`
    の監査・相の水増し禁止) を双方に要求する。`two_theta_limits` の必須性は
    `test_repair_frames_examples_always_pass_two_theta_limits` が両文書に対して担保する。

    **本ガードの限界**: 表現の同値性は検査できない (語 → 主張の写像は機械化できない)。
    再言明の欠落を捕らえるだけで、意味の食い違いまでは防げない — 最終防波堤は人間のレビュー。
    """
    for doc in (_SKILL, _PLAYBOOK):
        text = doc.read_text(encoding="utf-8")
        assert marker.search(text), (
            f"{doc}: 安全上の要となる指示 ({marker.pattern}) が無い。"
            "playbook と skill は同一内容を宣言している — 片方だけの安全指示は乖離である。"
        )


@pytest.mark.parametrize("doc", (_SKILL, _PLAYBOOK), ids=lambda p: p.as_posix())
def test_instrument_spec_keys_are_documented_where_instrument_is_required(doc):
    """ガード3c: `instrument` を渡せと指示する文書は、そのキーも文書化していること。

    ③ は JSON しか送れず、`instrument` spec の中身は**サーバ側 runner の全設定**である
    (放射光か実験室 X 線か・背景項数・少数相セル凍結)。「`instrument` を明示せよ」とだけ書いて
    キーを書かない文書は、③ に**組み立てられない値**を要求する (§4.5 到達可能性と同型の欠陥)。

    実際 operando-diagnose skill は `auto_freeze_minor_cells` に一切言及しないまま
    `instrument` を要求しており、playbook の「内容は本書と同一」宣言が偽になっていた。

    **限界**: キーが列挙されていることしか見ない。値の意味の正しさは human review。
    """
    text = doc.read_text(encoding="utf-8")
    assert "instrument" in text, f"{doc}: instrument spec への言及が無い"
    for key in ("path", "radiation", "geometry", "background_coeffs", "auto_freeze_minor_cells"):
        assert key in text, (
            f"{doc}: `instrument` を要求しているのにキー `{key}` を文書化していない。"
            "③ は JSON しか送れないため、キーが書かれていなければ組み立てられない。"
        )
    # 置き場所の取り違え (tool の kwarg として渡す → TypeError が境界を越える) を防ぐ
    assert re.search(r"auto_freeze_minor_cells[^\n]{0,200}(閾値|threshold)", text, re.S), (
        f"{doc}: auto_freeze_minor_cells を閾値と説明していない (bool 誤用は全相凍結になる)"
    )


def test_playbook_documents_auto_freeze_as_instrument_spec_threshold():
    """ガード3b: playbook の `auto_freeze_minor_cells` の説明が実装と一致すること。

    2 通りの取り違えがどちらも**黙って**壊す:
    - **tool の kwarg として渡す** → `TypeError` が MCP 境界を越える (置き場所は `instrument` spec)。
    - **bool を渡す** → `float(True)==1.0` = 「分率 1.0 未満の相をすべて凍結」= 全相のセルが
      黙って凍結される (② が bool を拒否するのはこのため)。

    `insitu` SKILL 側の同じ主張は `test_m9_plugin.py` が守っている。
    """
    import inspect  # noqa: PLC0415

    from tsumugin.autorietveld.engine import run_auto_rietveld  # noqa: PLC0415

    ann = inspect.signature(run_auto_rietveld).parameters["auto_freeze_minor_cells"].annotation
    assert "float" in str(ann), f"実装の型が変わった: {ann}"

    text = _PLAYBOOK.read_text(encoding="utf-8")
    assert "auto_freeze_minor_cells" in text
    assert "閾値" in text, "playbook が auto_freeze_minor_cells を閾値と説明していない"
    assert "bool ではない" in text, "playbook に bool との取り違えへの注意が無い"
    assert re.search(r"`instrument` spec のキー", text), (
        "playbook が auto_freeze_minor_cells の置き場所 (instrument spec) を明示していない"
    )


def test_plugin_manifest_advertises_operando_diagnose():
    """plugin.json の description が operando 診断を明記していること (段4)。"""
    manifest = json.loads((_PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    desc = manifest["description"]
    assert "operando-diagnose" in desc
    for tool in ("assess_data_quality", "check_phase_set", "repair_frames"):
        assert tool in desc, f"manifest が {tool} を宣伝していない"
