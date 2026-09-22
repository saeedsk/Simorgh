"""`--providers` pins a paid benchmark run to the providers it names.

Stage 2's comparison on Gemini has to be Gemini: with the library order
a refused call falls through to the next provider unannounced, and the
run measures a different model while looking like the one it named.
"""

import unittest

from simorgh.evals.house.bench import PAID_PROVIDERS, provider_order


class TheOrder(unittest.TestCase):
    def test_named_providers_then_only_the_floor(self):
        self.assertEqual(provider_order("gemini"), (("gemini",), ["gemini", "floor"]))

    def test_nothing_named_is_the_library_order(self):
        self.assertEqual(provider_order(""), ((), list(PAID_PROVIDERS)))


if __name__ == "__main__":
    unittest.main()
