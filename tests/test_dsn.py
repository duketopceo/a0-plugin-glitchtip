"""Sentry/GlitchTip DSN parsing — scheme, host (incl. IPv6), path-prefix
preservation, project_id validation, public-key hygiene in reprs."""

from usr.plugins.glitchtip.helpers.dsn import parse_dsn


def test_parse_valid_dsn():
    d = parse_dsn("https://pubkey123@glitchtip.example.com/42")
    assert d is not None
    assert d.base == "https://glitchtip.example.com"
    assert d.project_id == "42"
    assert d.public_key == "pubkey123"
    assert d.scheme == "https"
    assert d.store_url == "https://glitchtip.example.com/api/42/store/"
    assert "sentry_key=pubkey123" in d.auth_header
    assert "sentry_version=7" in d.auth_header


def test_parse_dsn_with_port_and_subpath():
    # Reverse-proxied self-hosted installs: the path before the project id
    # is the instance's URL prefix and must stay in base.
    d = parse_dsn("http://k@localhost:8000/nested/7")
    assert d is not None
    assert d.base == "http://localhost:8000/nested"
    assert d.project_id == "7"
    assert d.store_url == "http://localhost:8000/nested/api/7/store/"


def test_parse_ipv6_host():
    d = parse_dsn("http://k@[::1]:8000/1")
    assert d is not None
    assert d.base == "http://[::1]:8000"


def test_parse_rejects_empty_and_malformed():
    assert parse_dsn(None) is None
    assert parse_dsn("") is None
    assert parse_dsn("   ") is None
    assert parse_dsn("notaurl") is None
    assert parse_dsn(42) is None                 # non-string yaml scalar
    assert parse_dsn("ftp://k@host/1") is None
    assert parse_dsn("https://host/1") is None       # no public key
    assert parse_dsn("https://k@host") is None        # no project id
    assert parse_dsn("https://k@host/") is None
    assert parse_dsn("https://k@host/../") is None    # project_id must be sane
    assert parse_dsn("https://k@host/../7") is None   # '..' as path segment rejected


def test_dsn_repr_omits_public_key():
    d = parse_dsn("https://supersecret@gt.io/1")
    assert "supersecret" not in repr(d)
    assert "supersecret" not in str(d)
    assert "supersecret" not in str(d.base)
