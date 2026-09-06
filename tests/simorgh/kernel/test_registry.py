import unittest

from simorgh.kernel.registry import LAYERS, NEEDS_HMAC_SECRET, build_factories, known_layers


class TestLayers(unittest.TestCase):
    def test_layer_order_matches_the_architecture_doc(self):
        self.assertEqual(LAYERS, (
            ("bus", "ledger"),
            ("cognition", "memory", "worldmodel"),
            ("guardian", "execution", "verification", "planning"),
            ("learning", "reflection", "curiosity"),
            ("persona", "interface"),
            ("orchestration",),
        ))

    def test_no_subsystem_name_appears_in_more_than_one_layer(self):
        seen: set[str] = set()
        for layer in LAYERS:
            for name in layer:
                self.assertNotIn(name, seen, f"{name!r} appears in more than one layer")
                seen.add(name)

    def test_needs_hmac_secret_is_guardian_and_execution_only(self):
        self.assertEqual(NEEDS_HMAC_SECRET, frozenset({"guardian", "execution"}))
        for name in NEEDS_HMAC_SECRET:
            self.assertTrue(any(name in layer for layer in LAYERS))


class TestBuildFactories(unittest.TestCase):
    def test_factories_cover_every_subsystem_named_in_layers(self):
        # Was "Phase 0 factories are bus and ledger only" -- true when
        # this test was first written (Phase 0), stale the moment the
        # other twelve subsystems landed and were wired into the
        # registry (docs/EVOLUTION.md milestone 103). The invariant that
        # actually matters, and still holds: every name LAYERS declares
        # has a real factory, nothing more and nothing less.
        factories = build_factories(bus_client=object(), ledger_client=object())
        expected = {name for layer in LAYERS for name in layer}
        self.assertEqual(set(factories.keys()), expected)

    def test_factories_are_zero_arg_callables_returning_a_subsystem_each_call(self):
        factories = build_factories(bus_client=object(), ledger_client=object())
        bus_service_1 = factories["bus"]()
        bus_service_2 = factories["bus"]()
        self.assertEqual(bus_service_1.name, "bus")
        self.assertIsNot(bus_service_1, bus_service_2)  # a fresh instance per call, not a cached singleton

    def test_ledger_factory_returns_a_ledger_named_subsystem(self):
        factories = build_factories(bus_client=object(), ledger_client=object())
        self.assertEqual(factories["ledger"]().name, "ledger")


class TestKnownLayers(unittest.TestCase):
    def test_filters_out_names_with_no_factory_but_keeps_layer_slots(self):
        # A hand-built partial dict, not build_factories()'s own output --
        # that now covers every subsystem (milestone 103), so it can no
        # longer stand in for "only Phase 0 exists" the way it did when
        # this test was first written. known_layers()'s own filtering
        # behavior is what's under test here, independent of how complete
        # the registry happens to be at any given point in the build.
        only_bus_and_ledger = {"bus": lambda: object(), "ledger": lambda: object()}
        layers = known_layers(only_bus_and_ledger)
        self.assertEqual(len(layers), len(LAYERS))
        self.assertEqual(layers[0], ("bus", "ledger"))
        for layer in layers[1:]:
            self.assertEqual(layer, ())

    def test_empty_factories_yields_all_empty_layers(self):
        layers = known_layers({})
        self.assertEqual(layers, tuple(() for _ in LAYERS))

    def test_a_layer_partially_known_keeps_only_the_known_names_in_original_order(self):
        layers = known_layers({"guardian": lambda: object(), "planning": lambda: object()})
        self.assertEqual(layers[2], ("guardian", "planning"))


if __name__ == "__main__":
    unittest.main()
