from usr.plugins.glitchtip.helpers.dsn import parse_dsn


def test_parse_valid_dsn():
    d = parse_dsn("https://pubkey123@glitchtip.example.com/42")
    assert d is not None
    assert d.base == "https://glitchtip.example.com"
    assert d.project_id == "42"
    assert d.public_key == "pubkey123"
    assert d.store_url == "https://glitchtip.example.com/api/42/store/"
    assert "sentry_key=pubkey123" in d.auth_header
    assert "sentry_version=7" in d.auth_header


def test_parse_dsn_with_port_and_subpath():
    d = parse_dsn("http://k@localhost:8000/nested/7")
    assert d is not None
    assert d.base == "http://localhost:8000"
    assert d.project_id == "7"  # last path segment


def test_parse_rejects_empty_and_malformed():
    assert parse_dsn(None) is None
    assert parse_dsn("") is None
    assert parse_dsn("   ") is None
    assert parse_dsn("notaurl") is None
    assert parse_dsn("ftp://k@host/1") is None
    assert parse_dsn("https://host/1") is None       # no public key
    assert parse_dsn("https://k@host") is None        # no project id
    assert parse_dsn("https://k@host/") is None


def test_dsn_never_leaks_to_str():
    d = parse_dsn("https://supersecret@gt.io/1")
    assert "supersecret" not in str(d.base)
