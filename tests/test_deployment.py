import unittest

from src.memory.long_term import InMemoryStore
from src.orchestrator.deployment import DeploymentManager, VersionStatus
from src.orchestrator.router import AgentRequest, AgentResponse, Router, SubAgent


class UppercaseAgent(SubAgent):
    name = "echo"

    def handle(self, request, bus):
        return AgentResponse(agent=self.name, output=request.text.upper())


class ExclaimAgent(SubAgent):
    name = "echo"

    def handle(self, request, bus):
        return AgentResponse(agent=self.name, output=request.text + "!")


class CrashingAgent(SubAgent):
    name = "echo"

    def handle(self, request, bus):
        raise RuntimeError("boom")


class TestDeploy(unittest.TestCase):
    def test_deploy_registers_agent_as_active_and_live_in_router(self):
        router = Router()
        manager = DeploymentManager(router)

        manager.deploy(UppercaseAgent())

        self.assertEqual(
            router.dispatch("echo", AgentRequest(text="hi")).output, "HI"
        )

    def test_cannot_deploy_twice_to_same_slot(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())

        with self.assertRaises(ValueError):
            manager.deploy(UppercaseAgent())


class TestStageCandidate(unittest.TestCase):
    def test_staging_a_candidate_does_not_change_live_dispatch(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())

        manager.stage_candidate(ExclaimAgent())

        self.assertEqual(
            router.dispatch("echo", AgentRequest(text="hi")).output, "HI"
        )

    def test_cannot_stage_without_an_active_version(self):
        router = Router()
        manager = DeploymentManager(router)

        with self.assertRaises(ValueError):
            manager.stage_candidate(ExclaimAgent())

    def test_cannot_stage_two_candidates_at_once(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())
        manager.stage_candidate(ExclaimAgent())

        with self.assertRaises(ValueError):
            manager.stage_candidate(ExclaimAgent())


class TestRunTrial(unittest.TestCase):
    def test_trial_compares_baseline_and_candidate_without_touching_live_bus(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())
        manager.stage_candidate(ExclaimAgent())

        report = manager.run_trial("echo", [AgentRequest(text="hi")])

        self.assertEqual(report.baseline_outcomes[0].output, "HI")
        self.assertEqual(report.candidate_outcomes[0].output, "hi!")
        # live dispatch is still untouched by the trial
        self.assertEqual(
            router.dispatch("echo", AgentRequest(text="x")).output, "X"
        )

    def test_trial_marks_crashing_candidate_as_failed_without_raising(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())
        manager.stage_candidate(CrashingAgent())

        report = manager.run_trial("echo", [AgentRequest(text="hi")])

        self.assertFalse(report.candidate_outcomes[0].succeeded)
        self.assertIsNotNone(report.candidate_outcomes[0].error)
        self.assertEqual(report.candidate_success_rate, 0.0)
        self.assertEqual(report.baseline_success_rate, 1.0)
        self.assertFalse(report.candidate_is_at_least_as_good())

    def test_trial_requires_a_staged_candidate(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())

        with self.assertRaises(ValueError):
            manager.run_trial("echo", [AgentRequest(text="hi")])


class TestPromote(unittest.TestCase):
    def test_promote_swaps_live_dispatch_to_candidate(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())
        manager.stage_candidate(ExclaimAgent())

        manager.promote("echo")

        self.assertEqual(
            router.dispatch("echo", AgentRequest(text="hi")).output, "hi!"
        )

    def test_promote_retires_previous_active_instead_of_deleting_it(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())
        manager.stage_candidate(ExclaimAgent())

        manager.promote("echo")

        status = manager.status("echo")
        self.assertEqual(status["active"].status, VersionStatus.ACTIVE)
        self.assertEqual(len(status["retired"]), 1)
        self.assertEqual(status["retired"][0].status, VersionStatus.RETIRED)

    def test_cannot_promote_without_a_staged_candidate(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())

        with self.assertRaises(ValueError):
            manager.promote("echo")


class TestRollback(unittest.TestCase):
    def test_rollback_discards_staged_candidate_without_promotion(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())
        manager.stage_candidate(ExclaimAgent())

        manager.rollback("echo")

        self.assertEqual(
            router.dispatch("echo", AgentRequest(text="hi")).output, "HI"
        )
        self.assertIsNone(manager.status("echo")["candidate"])

    def test_rollback_after_promotion_restores_previous_active(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())
        manager.stage_candidate(ExclaimAgent())
        manager.promote("echo")

        manager.rollback("echo")

        self.assertEqual(
            router.dispatch("echo", AgentRequest(text="hi")).output, "HI"
        )

    def test_rollback_with_nothing_to_roll_back_to_raises(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())

        with self.assertRaises(ValueError):
            manager.rollback("echo")


class TestPurgeRetired(unittest.TestCase):
    def test_purge_removes_retired_versions(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())
        manager.stage_candidate(ExclaimAgent())
        manager.promote("echo")

        purged = manager.purge_retired("echo")

        self.assertEqual(purged, 1)
        self.assertEqual(manager.status("echo")["retired"], [])

    def test_purge_never_touches_the_active_version(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())
        manager.stage_candidate(ExclaimAgent())
        manager.promote("echo")

        manager.purge_retired("echo")

        self.assertEqual(
            router.dispatch("echo", AgentRequest(text="hi")).output, "hi!"
        )

    def test_purge_can_keep_a_number_of_recent_retired_versions(self):
        router = Router()
        manager = DeploymentManager(router)
        manager.deploy(UppercaseAgent())
        manager.stage_candidate(ExclaimAgent())
        manager.promote("echo")

        purged = manager.purge_retired("echo", keep_last=1)

        self.assertEqual(purged, 0)
        self.assertEqual(len(manager.status("echo")["retired"]), 1)


class TestLineageLogging(unittest.TestCase):
    def test_full_ab_flow_is_logged_to_memory(self):
        router = Router()
        memory = InMemoryStore()
        manager = DeploymentManager(router, memory=memory)
        manager.deploy(UppercaseAgent())
        manager.stage_candidate(ExclaimAgent())
        manager.promote("echo")
        manager.purge_retired("echo")

        events = [r.metadata["event"] for r in memory.query(kind="lineage")]

        self.assertEqual(
            list(reversed(events)),
            ["deploy", "stage_candidate", "promote", "purge"],
        )


if __name__ == "__main__":
    unittest.main()
