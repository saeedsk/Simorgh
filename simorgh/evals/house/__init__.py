"""The household simulator (stage 11).

Sim, booted where it can do no harm, driven by a scenario in which
several people talk to it and to each other, and watched closely
enough that what went wrong can be handed to somebody as a
reproduction rather than a description.

    async with Sandbox() as sandbox:
        director = Director(sandbox)
        await director.say("Ira", "Sim, what time is it")
        assert director.record.said

What is real: the Kernel, Guardian, the bus, the ledger, memory, the
speaker book. What is not: the model, the house, the microphone, the
speaker, and any way out of the sandbox.
"""

from .director import Director
from .record import Printed, Record, Said, Seen
from .sandbox import Sandbox

__all__ = ["Director", "Printed", "Record", "Said", "Sandbox", "Seen"]
