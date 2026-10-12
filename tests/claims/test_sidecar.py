"""fit-then-judge P1-1A タスク 8: gpx の隣の sidecar ``<stem>.claims.json`` (REQ-FTJ-1A-502)。

.gpx は出版状態を持てないので sidecar に置く。gpx の内容ハッシュで 1 対 1 に結び、読み手は
ハッシュが一致するものだけを採る (gpx が上書きされたら古い sidecar は「状態不明」)。上書きしない。
"""

from __future__ import annotations

import json

from tsumugin.claims.sidecar import read_claims_sidecar, write_claims_sidecar

_PAYLOAD = {"claims_version": "v", "policy": "D", "claims": {}, "judgment_requests": [],
            "publishable_values": {}}


def _gpx(tmp_path, content=b"gpx-1"):
    p = tmp_path / "run.gpx"
    p.write_bytes(content)
    return p


def test_sidecar_sits_next_to_the_gpx_and_round_trips(tmp_path):
    gpx = _gpx(tmp_path)
    path, reason = write_claims_sidecar(str(gpx), _PAYLOAD)
    assert path == str(tmp_path / "run.claims.json") and reason == ""
    got = read_claims_sidecar(str(gpx))
    assert got is not None and got["claims_version"] == "v"
    assert got["gpx_sha256"] and got["gpx_name"] == "run.gpx"


def test_a_sidecar_for_other_gpx_content_is_not_read(tmp_path):
    """gpx を上書きした (keep_gpx での再実行など) ら、古い sidecar は今の gpx の状態ではない。"""
    gpx = _gpx(tmp_path)
    write_claims_sidecar(str(gpx), _PAYLOAD)
    gpx.write_bytes(b"gpx-2")
    assert read_claims_sidecar(str(gpx)) is None


def test_an_existing_sidecar_is_never_overwritten(tmp_path):
    gpx = _gpx(tmp_path)
    first, _ = write_claims_sidecar(str(gpx), _PAYLOAD)
    before = (tmp_path / "run.claims.json").read_bytes()
    gpx.write_bytes(b"gpx-2")
    second, _ = write_claims_sidecar(str(gpx), {**_PAYLOAD, "claims_version": "w"})
    assert second != first
    assert (tmp_path / "run.claims.json").read_bytes() == before
    assert read_claims_sidecar(str(gpx))["claims_version"] == "w"


def test_writing_the_same_state_twice_is_idempotent(tmp_path):
    gpx = _gpx(tmp_path)
    first, _ = write_claims_sidecar(str(gpx), _PAYLOAD)
    second, reason = write_claims_sidecar(str(gpx), _PAYLOAD)
    assert second == first and reason == ""


def test_missing_gpx_gives_a_reason_not_an_exception(tmp_path):
    path, reason = write_claims_sidecar(str(tmp_path / "nope.gpx"), _PAYLOAD)
    assert path == "" and reason
    assert read_claims_sidecar(str(tmp_path / "nope.gpx")) is None
    path, reason = write_claims_sidecar("", _PAYLOAD)
    assert path == "" and reason


def test_sidecar_is_strict_json(tmp_path):
    gpx = _gpx(tmp_path)
    path, _ = write_claims_sidecar(str(gpx), _PAYLOAD)
    json.loads(open(path, encoding="utf-8").read())


def test_unreadable_sidecar_is_state_unknown(tmp_path):
    gpx = _gpx(tmp_path)
    (tmp_path / "run.claims.json").write_text("{broken", encoding="utf-8")
    assert read_claims_sidecar(str(gpx)) is None
