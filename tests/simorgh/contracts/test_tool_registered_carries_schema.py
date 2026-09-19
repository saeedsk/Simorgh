"""Stage 2 item 1: every tool a booted system registers says its arguments."""

import asyncio
import tempfile
import unittest

from simorgh.contracts import topics
from simorgh.contracts.validation import validate
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel


class EveryRegisteredToolCarriesItsSchema(unittest.IsolatedAsyncioTestCase):
    async def test_each_schema_is_an_object_schema_the_validator_can_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = Kernel(LoadedConfig({"runtime": {"data_dir": tmp}}, None), secrets=EnvSecretStore({}))
            await kernel.boot()
            try:
                await asyncio.sleep(0.2)
                execution = kernel._supervisor.services["execution"].service  # noqa: SLF001
                from simorgh.execution.service import input_schema_of

                problems = []
                for name, tool in execution._registry.items():  # noqa: SLF001
                    schema = input_schema_of(tool)
                    props = schema.get("properties", {})
                    if not isinstance(props, dict):
                        problems.append(f"{name}: properties is not a mapping")
                        continue
                    missing = [r for r in schema.get("required", []) if r not in props]
                    if missing:
                        problems.append(f"{name}: required {missing} not in properties")
                    try:
                        validate({}, schema)
                    except Exception as exc:  # noqa: BLE001
                        problems.append(f"{name}: validator raised {exc!r}")
                self.assertGreater(len(execution._registry), 50)  # noqa: SLF001
                self.assertEqual(problems, [])
                # And it crossed the wire: WorldModel holds what read_file declared.
                worldmodel = kernel._supervisor.services["worldmodel"].service  # noqa: SLF001
                held = worldmodel._tools._tools["read_file"]["input_schema"]  # noqa: SLF001
                self.assertEqual(held, input_schema_of(execution._registry["read_file"]))  # noqa: SLF001
                self.assertIn("path", held["properties"])
            finally:
                await kernel.shutdown()


if __name__ == "__main__":
    unittest.main()
