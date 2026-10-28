"""Stage 17: the `SETTINGS` presets turn a shipped-off feature on over `sim`."""
from simorgh.evals import ablation
from simorgh.orchestration.config import Config as OrchestrationConfig


def test_settings_presets_parse_and_stay_out_of_the_plan_table():
    assert ablation.parse_presets("sim,mask2,routed") == ["sim", "mask2", "routed"]
    assert not set(ablation.SETTINGS) & set(ablation.PRESETS)


def test_mask2_and_routed_set_their_keys_and_ablate_nothing():
    model = ablation.parse_models("together:zai-org/GLM-5.3-Flash")[0]
    mask = ablation.preset_config("mask2", model)["orchestration"]
    routed = ablation.preset_config("routed", model)["orchestration"]
    assert mask == {"ablate": [], "mask_after_steps": 2}
    assert routed == {"ablate": [], "tool_routing": "on"}
    assert ablation.preset_config("sim", model)["orchestration"] == {"ablate": []}


def test_the_settings_are_keys_orchestration_reads():
    for preset in ablation.SETTINGS.values():
        cfg = OrchestrationConfig.from_mapping(preset["orchestration"])
        for key, value in preset["orchestration"].items():
            assert getattr(cfg, key) == value


def test_settings_presets_are_never_called_inert():
    assert ablation.inert_presets(["mask2", "routed"], ablation.scenarios_for("toolchain")) == []
