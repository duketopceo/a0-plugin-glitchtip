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
    for bad in ["", "garbage", "00-123-456-01", "zz-" + "a" * 32 + "-" + "b" * 16 + "-01",
                "00-" + "0" * 32 + "-" + "b" * 16 + "-01"]:  # all-zero trace_id invalid
        tc.reset()
        tid, _sid = tc.ensure(bad)
        assert tid and len(tid) == 32  # fell back to fresh generation


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
