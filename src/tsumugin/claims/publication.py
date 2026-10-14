"""出版状態の計算と記録の唯一の入口 (fit-then-judge P1c)。

② (`mcp.rietveld_tools._attach_claims`) とワークベンチの精密化 (`workbench.session`) の両方がここを使う。
2 箇所で別に組むと、写像・判断要求・sidecar の書き方が片方だけずれる (以前は GUI の精密化が出版状態を一度も
作っていなかった)。

- `publication_state`: 結果から出版状態を作り、精密化済み gpx の隣に sidecar を書く。**例外にしない** —
  組み立てに失敗したら何も出版できない側 (``claims: None``・``publishable_values: {}``) に倒し、理由を
  ``error`` に載せる。
- `input_publication`: 精密化済み gpx を入力に取るツール (MEM 等) が、その gpx の出版状態を**読むだけ**の要約。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["input_publication", "publication_state"]

_STRUCTURE_CLASSES = frozenset({"coord", "uiso", "occupancy"})


def publication_state(
    result: object,
    phases: "Sequence[object] | None",
    *,
    gpx_path: str = "",
    multistart: object | None = None,
    derivation: "Mapping[str, object] | None" = None,
    probe: object | None = None,
) -> dict[str, Any]:
    """出版状態を作り sidecar を書く。② の結果に足すキーと同じ形の dict を返す。

    キー: ``claims_version``・``claims``・``judgment_requests``・``publishable_values``・
    (成功時) ``claims_policy``・``claims_sidecar``・``claims_sidecar_reason``・(失敗時) ``error``。
    """
    from .build import CLAIMS_VERSION
    from .requests import assess
    from .sidecar import write_claims_sidecar

    try:
        body = assess(result, phases, multistart, derivation=derivation, probe=probe).to_dict()
    except Exception as exc:  # noqa: BLE001 — 出版状態の失敗でフィット結果を落とさない
        return {
            "claims_version": CLAIMS_VERSION, "claims": None, "judgment_requests": [],
            "publishable_values": {}, "claims_sidecar": "", "claims_sidecar_reason": "",
            "error": f"{type(exc).__name__}: {exc}",
        }
    out: dict[str, Any] = {k: body[k] for k in (
        "claims_version", "claims", "judgment_requests", "publishable_values",
    )}
    out["claims_policy"] = body["policy"]
    try:
        path, reason = ("", "") if not gpx_path else write_claims_sidecar(str(gpx_path), body)
    except Exception as exc:  # noqa: BLE001 — sidecar の失敗でフィット結果を落とさない
        path, reason = "", f"{type(exc).__name__}: {exc}"
    out["claims_sidecar"] = path
    out["claims_sidecar_reason"] = reason
    return out


def input_publication(gpx_path: str) -> dict[str, Any]:
    """入力 gpx の出版状態の要約 (読むだけ)。gpx の内容と一致する sidecar が無ければ ``state: "unknown"``。

    MEM は精密化済みの構造の上で密度を読むので、構造値が止められた fit・状態の分からない fit からの結果は
    「決まっていない構造の上の診断」になる。呼び手 (③) がそれを見分けられるようにする。
    """
    from .sidecar import find_claims_sidecar

    unknown: dict[str, Any] = {
        "state": "unknown", "sidecar": "", "n_values": None, "n_publishable": None,
        "structure_held": None, "blocking_requests": None,
    }
    try:
        found = find_claims_sidecar(str(gpx_path or ""))
    except Exception:  # noqa: BLE001 — 読めないなら状態不明 (例外にしない)
        return unknown
    if found is None:
        return unknown
    path, body = found
    claims = body.get("claims")
    if not isinstance(claims, Mapping):
        return {**unknown, "sidecar": path}
    from .model import Claim

    n_pub = 0
    held: list[str] = []
    for key, raw in sorted(claims.items()):
        try:
            claim = Claim.from_dict(raw)
        except Exception:  # noqa: BLE001 — 読めない値は出版不可として数える
            if str(key).split(":", 1)[0] in _STRUCTURE_CLASSES:
                held.append(str(key))
            continue
        if claim.publishable:
            n_pub += 1
        elif claim.param_class in _STRUCTURE_CLASSES:
            held.append(claim.key)
    blocking = [
        {"id": r.get("id"), "kind": r.get("kind")}
        for r in body.get("judgment_requests") or ()
        if isinstance(r, Mapping) and r.get("blocking")
    ]
    return {
        "state": "known", "sidecar": path, "n_values": len(claims), "n_publishable": n_pub,
        "structure_held": held, "blocking_requests": blocking,
    }
