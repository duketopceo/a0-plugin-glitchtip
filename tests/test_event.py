from usr.plugins.glitchtip.helpers.event import build_event


def _boom():
    try:
        raise ValueError("kaboom")
    except ValueError as e:
        return e


def test_exception_event_shape():
    ev = build_event(exc=_boom(), tags={"surface": "test"}, environment="test")
    assert ev["level"] == "error"
    assert ev["platform"] == "python"
    assert len(ev["event_id"]) == 32
    val = ev["exception"]["values"][0]
    assert val["type"] == "ValueError"
    assert val["value"] == "kaboom"
    frames = val["stacktrace"]["frames"]
    assert frames[-1]["function"] == "_boom"  # extract_tb order preserved: raise site last
    assert all("filename" in f and "lineno" in f for f in frames)
    assert ev["tags"]["surface"] == "test"
    assert "api_key" not in ev  # no PII fields


def test_stack_frame_order_oldest_first():
    # Regression: extract_tb already yields caller→callee (oldest→newest).
    # A reversal here puts the raise site FIRST and inverts every trace —
    # pin the contract with a real 3-deep chain.
    def outer():
        return middle()

    def middle():
        return inner()

    def inner():
        raise RuntimeError("deep end")

    try:
        outer()
    except RuntimeError as e:
        ev = build_event(exc=e)
    frames = ev["exception"]["values"][0]["stacktrace"]["frames"]
    names = [f["function"] for f in frames]
    assert names[-3:] == ["outer", "middle", "inner"]
    assert names.index("outer") < names.index("middle") < names.index("inner")
    assert names[0] == "test_stack_frame_order_oldest_first"  # caller first


def test_message_event_shape():
    ev = build_event(message="hello world", level="info")
    assert ev["message"] == "hello world"
    assert ev["level"] == "info"
    assert "exception" not in ev


def test_trace_context_attached():
    ev = build_event(message="m", trace_id="ab" * 16, span_id="cd" * 8)
    assert ev["contexts"]["trace"]["type"] == "trace"
    assert ev["contexts"]["trace"]["trace_id"] == "ab" * 16
    assert ev["contexts"]["trace"]["span_id"] == "cd" * 8
    assert ev["tags"]["trace_id"] == "ab" * 16


def test_sensitive_headers_redacted():
    ev = build_event(
        message="m",
        request={
            "url": "/api/x",
            "headers": {
                "Authorization": "Bearer SECRET",
                "X-Api-Key": "SECRET2",
                "Cookie": "session=SECRET3",
                "Set-Cookie": "s=SECRET4",
                "X-CSRF-Token": "SECRET5",
                "Proxy-Authorization": "SECRET6",
                "WWW-Authenticate": "Bearer realm",
                "Content-Type": "application/json",
            },
        },
    )
    h = ev["request"]["headers"]
    for name in ("Authorization", "X-Api-Key", "Cookie", "Set-Cookie",
                 "X-CSRF-Token", "Proxy-Authorization", "WWW-Authenticate"):
        assert h[name] == "[redacted]", name
    assert h["Content-Type"] == "application/json"


def test_caller_request_dict_not_mutated():
    req = {"url": "/api/x", "headers": {"Authorization": "Bearer S", "X": "1"}}
    build_event(message="m", request=req)
    assert req["headers"]["Authorization"] == "Bearer S"  # untouched


def test_injected_redactor_scrubs_nested_strings():
    ev = build_event(
        message="the key is sk-live-123",
        tags={"note": "uses sk-live-123"},
        redact=lambda s: s.replace("sk-live-123", "***"),
    )
    assert "sk-live-123" not in ev["message"]
    assert ev["tags"]["note"] == "uses ***"


def test_broken_redactor_fails_closed_per_field():
    def boom(_s):
        raise RuntimeError("redactor exploded")

    ev = build_event(message="m", redact=boom)
    # Per-field fail-closed: the string the redactor choked on is replaced
    # with "[redacted]" — the event must NEVER ship unredacted.
    assert ev["message"] == "[redacted]"


def test_breadcrumbs_passed_verbatim():
    # Cap ownership lives in breadcrumbs.py's deque maxlen — build_event
    # embeds whatever snapshot it is given without re-truncating.
    crumbs = [{"timestamp": i, "message": str(i)} for i in range(60)]
    ev = build_event(message="m", breadcrumbs=crumbs)
    assert len(ev["breadcrumbs"]["values"]) == 60
    assert ev["breadcrumbs"]["values"][-1]["message"] == "59"


def test_breadcrumb_ring_buffer_enforces_max():
    from usr.plugins.glitchtip.helpers import breadcrumbs

    breadcrumbs.configure(5)
    for i in range(9):
        breadcrumbs.crumb("t", f"m{i}")
    snap = breadcrumbs.snapshot()
    assert [c["message"] for c in snap] == ["m4", "m5", "m6", "m7", "m8"]


def test_stack_frames_capped():
    def rec(n):
        if n == 0:
            raise ValueError("deep")
        return rec(n - 1)

    try:
        rec(300)
    except ValueError as e:
        ev = build_event(exc=e)
    assert len(ev["exception"]["values"][0]["stacktrace"]["frames"]) <= 100
