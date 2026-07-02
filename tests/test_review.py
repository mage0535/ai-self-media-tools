import tempfile
import time
import unittest
from pathlib import Path

from content_platform.review import ReviewTokens


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tokens = ReviewTokens(Path(self.tmp.name) / "review.key")

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_token_round_trip(self):
        token = self.tokens.issue("job-1", "approve", ttl=60, now=100)
        payload = self.tokens.verify(token, "approve", now=120)
        self.assertEqual(payload["job_id"], "job-1")

    def test_tampered_expired_and_wrong_action_tokens_fail(self):
        token = self.tokens.issue("job-1", "approve", ttl=10, now=100)
        for candidate, action, now in ((token + "x", "approve", 101), (token, "approve", 111), (token, "reject", 101)):
            with self.assertRaises(ValueError):
                self.tokens.verify(candidate, action, now=now)


if __name__ == "__main__":
    unittest.main()

