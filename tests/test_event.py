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
    assert frames[-1]["function"] == "_boom"  # newest call last (reversed)
    assert all("filename" in f and "lineno" in f for f in frames)
    assert ev["tags"]["surface"] == "test"
    assert "api_key" not in ev  # no PII fields


def test_message_event_shape():
    ev = build_event(message="hello world", level="info")
    assert ev["message"] == "hello world"
    assert ev["level"] == "info"
    assert "exception" not in ev


def test_trace_context_attached():
    ev = build_event(message="m", trace_id="ab" * 16, span_id="cd" * 8)
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
                "Content-Type": "application/json",
            },
        },
    )
    h = ev["request"]["headers"]
    assert h["Authorization"] == "[redacted]"
    assert h["X-Api-Key"] == "[redacted]"
    assert h["Cookie"] == "[redacted]"
    assert h["Content-Type"] == "application/json"


def test_injected_redactor_scrubs_nested_strings():
    ev = build_event(
        message="the key is sk-live-123",
        tags={"note": "uses sk-live-123"},
        redact=lambda s: s.replace("sk-live-123", "***"),
    )
    assert "sk-live-123" not in ev["message"]
    assert ev["tags"]["note"] == "uses ***"


def test_broken_redactor_never_breaks_event():
    def boom(_s):
        raise RuntimeError("redactor exploded")

    ev = build_event(message="m", redact=boom)
    assert ev["message"] == "m"  # scrub failure falls back to unredacted event


def test_breadcrumbs_tail_capped():
    crumbs = [{"timestamp": i, "message": str(i)} for i in range(60)]
    ev = build_event(message="m", breadcrumbs=crumbs)
    assert len(ev["breadcrumbs"]["values"]) == 50
    assert ev["breadcrumbs"]["values"][-1]["message"] == "59"
