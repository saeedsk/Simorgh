"""`review_timeout_s` and `max_concurrent_reviews` were absent from
`Config.from_mapping`'s `cls(...)` call entirely -- not read into a
nested or differently-named key, simply never passed at all, so the
dataclass default always won regardless of simorgh.toml. Confirmed live
by an observer 2026-09-08: writing max_concurrent_reviews=6 left the
running semaphore at the default of 2.
"""

from __future__ import annotations

import unittest

from simorgh.reflection.config import Config


class TestEveryFieldFromMappingActuallyReads(unittest.TestCase):
    def test_review_timeout_s_is_read(self) -> None:
        self.assertEqual(Config.from_mapping({"review_timeout_s": 45.0}).review_timeout_s, 45.0)

    def test_max_concurrent_reviews_is_read(self) -> None:
        self.assertEqual(Config.from_mapping({"max_concurrent_reviews": 6}).max_concurrent_reviews, 6)

    def test_both_together_alongside_an_already_working_field(self) -> None:
        config = Config.from_mapping({
            "review_timeout_s": 45.0, "max_concurrent_reviews": 6, "denial_window_seconds": 111.0,
        })
        self.assertEqual((config.review_timeout_s, config.max_concurrent_reviews, config.denial_window_seconds),
                        (45.0, 6, 111.0))

    def test_absent_keys_keep_the_dataclass_default(self) -> None:
        config = Config.from_mapping({})
        self.assertEqual(config.review_timeout_s, Config.review_timeout_s)
        self.assertEqual(config.max_concurrent_reviews, Config.max_concurrent_reviews)


if __name__ == "__main__":
    unittest.main()
