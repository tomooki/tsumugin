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


def test_glob_special_characters_in_the_gpx_name_do_not_hide_sidecars(tmp_path):
    gpx = tmp_path / "run[1].gpx"
    gpx.write_bytes(b"gpx-1")
    write_claims_sidecar(str(gpx), _PAYLOAD)
    gpx.write_bytes(b"gpx-2")
    path, _ = write_claims_sidecar(str(gpx), {**_PAYLOAD, "claims_version": "w"})
    assert "claims." in path and path.endswith(".json")
    assert read_claims_sidecar(str(gpx))["claims_version"] == "w"


def test_an_undecodable_existing_sidecar_is_kept_and_does_not_raise(tmp_path):
    gpx = _gpx(tmp_path)
    (tmp_path / "run.claims.json").write_bytes(b"\xff\xfe\x83broken")
    path, reason = write_claims_sidecar(str(gpx), _PAYLOAD)
    assert reason == "" and path != str(tmp_path / "run.claims.json")
    assert (tmp_path / "run.claims.json").read_bytes() == b"\xff\xfe\x83broken"


def test_the_newest_state_for_the_same_gpx_wins(tmp_path):
    """同じ gpx を別の相の指定で評価し直した — 最初に書いた既定名ではなく新しい方を返す。"""
    gpx = _gpx(tmp_path)
    write_claims_sidecar(str(gpx), _PAYLOAD)
    write_claims_sidecar(str(gpx), {**_PAYLOAD, "claims_version": "second"})
    assert read_claims_sidecar(str(gpx))["claims_version"] == "second"


def test_a_path_with_a_nul_character_is_state_unknown_not_an_exception(tmp_path):
    """open() は NUL を含むパスで ValueError を出す — ② を越えて例外にしない (2 巡目 L-c)。"""
    assert read_claims_sidecar(str(tmp_path / "a\x00b.gpx")) is None
    path, reason = write_claims_sidecar(str(tmp_path / "a\x00b.gpx"), _PAYLOAD)
    assert path == "" and reason


def test_every_distinct_state_of_one_gpx_is_kept_and_the_latest_is_read(tmp_path):
    """同じ gpx を 3 回以上違う入力で評価しても書け、最後に書いた状態を読む (/code-review #241)。"""
    from tsumugin.claims.sidecar import find_claims_sidecar, write_claims_sidecar

    gpx = tmp_path / "fit.gpx"
    gpx.write_bytes(b"gpx")
    paths = []
    for n in range(4):
        path, reason = write_claims_sidecar(str(gpx), {"claims": {"n": n}})
        assert path and not reason
        paths.append(path)
    assert len(set(paths)) == 4
    assert find_claims_sidecar(str(gpx))[1]["claims"] == {"n": 3}
    # 同じ状態をもう一度書くのは何もしない
    assert write_claims_sidecar(str(gpx), {"claims": {"n": 1}})[0] == paths[1]


def test_the_reader_orders_by_the_recorded_write_time_not_mtime(tmp_path):
    """コピーや復元で mtime が入れ替わっても、中身に記録した書いた順で選ぶ (/code-review #241)。"""
    import os

    from tsumugin.claims.sidecar import find_claims_sidecar, write_claims_sidecar

    gpx = tmp_path / "fit.gpx"
    gpx.write_bytes(b"gpx")
    first, _ = write_claims_sidecar(str(gpx), {"claims": {"n": 0}})
    second, _ = write_claims_sidecar(str(gpx), {"claims": {"n": 1}})
    os.utime(first, (2_000_000_000, 2_000_000_000))  # 古い方の mtime を未来に
    assert find_claims_sidecar(str(gpx))[1]["claims"] == {"n": 1}


def test_the_sidecar_bytes_are_deterministic(tmp_path):
    """同じ解析を回し直せば同じ sidecar になる (書いた時刻を中身に入れない。/code-review #245)。"""
    from tsumugin.claims.sidecar import write_claims_sidecar

    outs = []
    for d in ("a", "b"):
        gpx = tmp_path / d / "fit.gpx"
        gpx.parent.mkdir()
        gpx.write_bytes(b"gpx")
        write_claims_sidecar(str(gpx), {"claims": {"n": 0}})
        path, _ = write_claims_sidecar(str(gpx), {"claims": {"n": 1}})
        outs.append(open(path, "rb").read())
    assert outs[0] == outs[1]


def test_a_deleted_sidecar_does_not_make_sequences_collide(tmp_path):
    """消したあとの書き込みが既存の番号と重ならず、最後に書いた状態が読まれる (/code-review #245)。"""
    import os

    from tsumugin.claims.sidecar import find_claims_sidecar, write_claims_sidecar

    gpx = tmp_path / "fit.gpx"
    gpx.write_bytes(b"gpx")
    paths = [write_claims_sidecar(str(gpx), {"claims": {"n": n}})[0] for n in range(3)]
    os.remove(paths[0])  # 既定名が空く — 新しい状態はそこに書かれ、名前の順では最も前になる
    write_claims_sidecar(str(gpx), {"claims": {"n": 9}})
    assert find_claims_sidecar(str(gpx))[1]["claims"] == {"n": 9}
