"""★規定「全解析で gpx を保存する」の M10 アンカー双方向側 (stub runner, GSAS 非依存)。

アンカー基準解析は**同じフレームを 2 回以上精密化する** (アンカー確定 / 前方パス / 後方パス /
FR-318 の制約有無 A/B)。採用されたのはどちらか一方だけなので、**採られなかった側の fit が
残っていないと bic crossover の妥当性を後から検算できない** — 相集合が違う経路を比べる
判断そのものが検算不能になる。
"""

from __future__ import annotations

from pathlib import Path

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.gpxstore import active_context
from tsumugin.insitu.anchor import run_anchored_sequential
from tsumugin.insitu.anchor.model import AnchorConfig
from tsumugin.insitu.model import FrameSpec

ALPHA = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
DELTA = PhaseSpec(structure_path="delta.cif", phase_name="new_delta")


def _res(rwp, cells, fracs, *, gof=1.0, n_obs=2000, gpx_path=""):
    return AutoRietveldResult(
        stage_results=(), final_rwp=rwp, final_gof=gof, refined_cells=cells,
        validity=ValidityReport(passed=True), phase_fractions=fracs, n_obs=n_obs,
        gpx_path=gpx_path,
    )


def _frames(n):
    return [FrameSpec(data_path=f"f{i}.xye", axis_value=float(300 + i * 30)) for i in range(n)]


def test_anchored_series_labels_every_pass(tmp_path):
    """アンカー・前方・後方が**別々の成果物**として名前を持ち、run ディレクトリは 1 つ。"""
    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=15.0)
    conf = {0: 0.9, 1: 0.2, 2: 0.2, 3: 0.9}
    specs = {0: (ALPHA,), 1: (ALPHA,), 2: (ALPHA, DELTA), 3: (ALPHA, DELTA)}
    seen: list[tuple[str, int | None]] = []

    def identifier(frame):
        i = int((frame.axis_value - 300) / 30)
        return (conf[i], specs[i])

    def runner(frame, phases, cells):
        ctx = active_context()
        seen.append((ctx.role, ctx.index))
        cells_out = {p.phase_name: (5.0, 5.0, 5.0, 90, 90, 90) for p in phases}
        fr = {p.phase_name: 1.0 / len(phases) for p in phases}
        return _res(9.0, cells_out, fr, gpx_path=f"/out/{ctx.role}{ctx.index}.gpx")

    res = run_anchored_sequential(
        _frames(4), [ALPHA], runner=runner, identifier=identifier, cfg=cfg,
        gpx_dir=str(tmp_path),
    )

    roles = {r for r, _ in seen}
    assert "anchor" in roles
    assert {"forward", "backward"} & roles, f"双方向パスに名前が付いていない: {roles}"
    assert res.gpx_dir and Path(res.gpx_dir).parent == tmp_path
    # 採用されたフレームは自分の fit の成果物を指す (どのパスが採られたかも名前で分かる)
    assert all(f.gpx_path for f in res.frames), [f.gpx_path for f in res.frames]


def test_anchor_frames_carry_their_gpx(tmp_path):
    """アンカーフレームの成果物パスが結果に載る (アンカーは Anchor 経由でしか届かない)。"""

    def runner(frame, phases, cells):
        ctx = active_context()
        return _res(
            9.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0},
            gpx_path=f"/out/a{ctx.index}.gpx",
        )

    def identifier(frame):
        return (0.9, (ALPHA,))

    res = run_anchored_sequential(
        _frames(3), [ALPHA], runner=runner, identifier=identifier, gpx_dir=str(tmp_path)
    )

    assert [f.gpx_path for f in res.frames] == ["/out/a0.gpx", "/out/a1.gpx", "/out/a2.gpx"]


def test_save_gpx_false_disables_the_anchored_series(tmp_path):
    """opt-out は M10 経路でも効く。"""
    enabled: list[bool] = []

    def runner(frame, phases, cells):
        enabled.append(active_context().enabled)
        return _res(9.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0})

    res = run_anchored_sequential(
        _frames(2), [ALPHA], runner=runner, identifier=None, save_gpx=False,
        gpx_dir=str(tmp_path),
    )

    assert enabled and not any(enabled)
    assert res.gpx_dir == ""
