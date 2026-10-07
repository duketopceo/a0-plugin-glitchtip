from usr.plugins.glitchtip.helpers import trace_context as tc


def test_generate_fresh_context():
    tid, sid = tc.ensure()
    assert tid and len(tid) == 32
    assert sid and len(sid) == 16
    assert tc.current() == (tid, sid)


def test_adopt_inbound_traceparent():
    inbound = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    tid, sid = tc.ensure(inbound)
    assert tid == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert sid != "00f067aa0ba902b7"  # new span id, same trace
    assert len(sid) == 16


def test_traceparent_roundtrip():
    tc.ensure()
    tp = tc.traceparent()
    assert tp and tp.startswith("00-")
    parsed = tc.parse_traceparent(tp)
    assert parsed is not None
    assert parsed[0] == tc.current()[0]


def test_malformed_traceparent_ignored():
    tid32 = "4bf92f3577b34da6a3ce929d0e0e4736"
    sid16 = "00f067aa0ba902b7"
    for bad in [
        "", "garbage", "00-123-456-01",
        "zz-" + "a" * 32 + "-" + "b" * 16 + "-01",          # non-hex version
        "ff-" + tid32 + "-" + sid16 + "-01",                 # version ff forbidden
        f"00-{tid32}-{sid16}-1",                             # flags must be 2 hex
        f"00-{tid32}-{sid16}-zz",                            # non-hex flags
        f"00-{tid32}-{sid16}",                               # missing flags field
        "00-" + "0" * 32 + "-" + sid16 + "-01",              # all-zero trace_id
        "00-" + tid32 + "-" + "0" * 16 + "-01",              # all-zero span_id
        f"0-{tid32}-{sid16}-01",                             # version must be 2 hex
    ]:
        tc.reset()
        tid, _sid = tc.ensure(bad)
        assert tid and len(tid) == 32  # fell back to fresh generation
        assert tid != "0" * 32


def test_parse_normalizes_case():
    parsed = tc.parse_traceparent(
        "00-4BF92F3577B34DA6A3CE929D0E0E4736-00F067AA0BA902B7-01")
    assert parsed == ("4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7")


def test_ensure_reuses_trace_but_new_span():
    tid1, sid1 = tc.ensure()
    tid2, sid2 = tc.ensure()
    assert tid2 == tid1      # same trace within one context
    assert sid2 != sid1      # child span per ensure()


def test_reset_clears():
    tc.ensure()
    tc.reset()
    assert tc.current() == (None, None)


def test_context_isolation():
    import asyncio

    async def worker(tag):
        tc.reset()
        tc.ensure()
        await asyncio.sleep(0)
        return tc.current()[0] + tag

    async def main():
        return await asyncio.gather(worker("a"), worker("b"))

    ids = asyncio.run(main())
    assert ids[0][:32] != ids[1][:32]  # separate contextvars per coroutine
