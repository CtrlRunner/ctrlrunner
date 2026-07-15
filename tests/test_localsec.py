import unittest

from ctrlrunner.ui.localsec import (
    host_allowed,
    new_session_token,
    origin_allowed,
    token_matches,
)

PORT = 54321


class HostAllowedTests(unittest.TestCase):
    def test_accepts_own_loopback_names(self):
        for host in (f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"):
            self.assertTrue(host_allowed(host, PORT), host)

    def test_rejects_rebound_attacker_hostname(self):
        # The DNS-rebinding case: attacker.tld resolves to 127.0.0.1, so
        # the socket connects, but the browser sends the attacker's own
        # hostname in Host -- which is never one of our loopback names.
        self.assertFalse(host_allowed(f"attacker.tld:{PORT}", PORT))

    def test_rejects_right_host_wrong_port(self):
        self.assertFalse(host_allowed(f"127.0.0.1:{PORT + 1}", PORT))

    def test_rejects_missing_host(self):
        self.assertFalse(host_allowed(None, PORT))
        self.assertFalse(host_allowed("", PORT))


class OriginAllowedTests(unittest.TestCase):
    def test_allows_matching_origin(self):
        self.assertTrue(origin_allowed(f"http://127.0.0.1:{PORT}", None, PORT))
        self.assertTrue(origin_allowed(f"http://localhost:{PORT}", None, PORT))

    def test_rejects_cross_site_origin(self):
        self.assertFalse(origin_allowed("http://evil.example", None, PORT))

    def test_rejects_host_echo_bypass(self):
        # The previous implementation compared Origin against the
        # request's OWN Host header, so an attacker setting both to their
        # value passed. Here Origin is validated against the known bound
        # port instead, so an attacker-controlled origin fails regardless
        # of what Host they send.
        self.assertFalse(origin_allowed("http://evil.example", None, PORT))

    def test_falls_back_to_referer_when_no_origin(self):
        self.assertTrue(origin_allowed(None, f"http://127.0.0.1:{PORT}/index.html", PORT))
        self.assertFalse(origin_allowed(None, "http://evil.example/page", PORT))

    def test_allows_when_neither_header_present(self):
        # Non-browser clients (curl, tests) send neither -- allowed here;
        # the token/Host checks constrain them instead.
        self.assertTrue(origin_allowed(None, None, PORT))

    def test_origin_takes_precedence_over_referer(self):
        # A present-but-bad Origin is rejected even if Referer would pass.
        self.assertFalse(origin_allowed("http://evil.example", f"http://127.0.0.1:{PORT}/x", PORT))


class TokenTests(unittest.TestCase):
    def test_new_token_is_long_and_unique(self):
        a, b = new_session_token(), new_session_token()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 32)

    def test_matches_only_exact_token(self):
        tok = new_session_token()
        self.assertTrue(token_matches(tok, tok))
        self.assertFalse(token_matches(tok + "x", tok))
        self.assertFalse(token_matches(None, tok))
        self.assertFalse(token_matches("", tok))


if __name__ == "__main__":
    unittest.main()
