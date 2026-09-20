"""Stage 8 item 3's acceptance: a fixture of 30 failures yields the two
planted clusters and no others.

The rule this pins is that finding a pattern costs nothing and asks
nobody. Counting is deterministic, free, and happens over facts already
in the ledger; the model is asked exactly one thing, and only after the
counting -- to phrase what the counting already found.

The fixture is built the way the live data looks: two real patterns,
one big enough to see and one only just, buried in noise that must NOT
come back as a lesson -- failures with no recorded cause, a failure
mode every task type has equally, and a pair that is simply too small.
"""

import unittest

from simorgh.growth.diagnose import Failure, cluster, phrasing_prompt


def _fixture() -> list[Failure]:
    failures: list[Failure] = []
    n = 0

    def add(**kw) -> None:
        nonlocal n
        n += 1
        failures.append(Failure(task_id=f"t{n}", **kw))

    # Planted cluster one: six patch tasks that all failed the same
    # check. This is the one anybody would notice.
    for _ in range(6):
        add(task_type="patch", failed_check="full_suite_ran",
            reason="committed a change that narrowed run_tests to one passing file")
    # Planted cluster two: four research tasks Guardian refused the same
    # tool for. Smaller, and still a real pattern.
    for _ in range(4):
        add(task_type="research", denied_tool="run_shell",
            reason="tried to curl the page instead of using web_fetch")
    # Noise 1: failures with no recorded cause. "These failed, cause
    # unknown" is not a lesson, however many there are.
    for _ in range(8):
        add(task_type="patch", reason="the model stopped without saying why")
    # Noise 2: a failure mode every type has equally -- a timeout. Above
    # `min_members` in each type, and about nothing in particular.
    for kind in ("patch", "research", "plan", "chat"):
        for _ in range(3):
            add(task_type=kind, failed_check="answered_in_time", reason="timed out")
    return failures


class TheFixture(unittest.TestCase):
    def test_it_is_thirty_failures(self):
        self.assertEqual(len(_fixture()), 30)


class TheClustering(unittest.TestCase):
    def setUp(self):
        self.clusters = cluster(_fixture())

    def test_exactly_the_two_planted_clusters_come_back(self):
        self.assertEqual(len(self.clusters), 2, [c.describe() for c in self.clusters])

    def test_the_bigger_one_is_first(self):
        first, second = self.clusters
        self.assertEqual((first.task_type, first.key[1], len(first.members)), ("patch", "full_suite_ran", 6))
        self.assertEqual((second.task_type, second.key[2], len(second.members)), ("research", "run_shell", 4))

    def test_a_cause_nobody_recorded_is_not_a_pattern(self):
        self.assertNotIn("", [c.key[1] or c.key[2] or c.key[3] for c in self.clusters])

    def test_a_failure_mode_every_type_shares_is_not_about_this_type(self):
        self.assertNotIn("answered_in_time", [c.key[1] for c in self.clusters],
                         "a timeout everybody gets equally is not a lesson about patching")

    def test_the_counting_is_deterministic(self):
        again = cluster(_fixture())
        self.assertEqual([c.key for c in self.clusters], [c.key for c in again])

    def test_the_model_is_only_asked_to_phrase_what_counting_found(self):
        prompt = phrasing_prompt(self.clusters[0])
        self.assertIn("full_suite_ran", prompt)
        self.assertIn("one sentence", prompt)
        self.assertIn("nothing you cannot see below", prompt)

    def test_a_smaller_run_of_the_same_failure_is_below_the_bar(self):
        """Two of a kind is a coincidence; three is the bar."""
        two = [f for f in _fixture() if f.failed_check == "full_suite_ran"][:2]
        self.assertEqual(cluster(two), [])


class TheThreeSourcesFoldIntoOneList(unittest.TestCase):
    """Stage 8 item 3: the failure clusters, the denial miner and the
    pattern miner all make the same claim -- this keeps happening, and
    it is specific enough to say something about -- so one place
    decides what is worth phrasing."""

    def setUp(self):
        from simorgh.growth.diagnose import candidates
        from simorgh.growth.monitors.patterns import Pattern

        self.found = candidates(
            _fixture(),
            denials={("run_shell", "outside the session's scope"): 7,
                     ("notify", "tier 3 needs a person"): 2},
            patterns=[Pattern(kind="failure_rate", task_type="plan", rate=0.8,
                              proposal="plan tasks are failing four times in five")],
        )

    def test_every_source_is_represented(self):
        self.assertEqual({c.source for c in self.found}, {"failures", "denials", "patterns"})

    def test_the_strongest_claim_is_first(self):
        self.assertEqual((self.found[0].source, self.found[0].count), ("denials", 7))

    def test_a_denial_below_the_repeat_bar_is_not_a_candidate(self):
        self.assertNotIn("notify", [c.subject for c in self.found])

    def test_one_prompt_shape_whatever_found_it(self):
        from simorgh.growth.diagnose import candidate_prompt

        for candidate in self.found:
            prompt = candidate_prompt(candidate)
            self.assertIn("one sentence", prompt)
            self.assertIn("nothing you cannot see below", prompt)
            self.assertIn(candidate.what, prompt)

    def test_nothing_anywhere_yields_nothing(self):
        from simorgh.growth.diagnose import candidates

        self.assertEqual(candidates([], denials={}, patterns=[]), [])


if __name__ == "__main__":
    unittest.main()
