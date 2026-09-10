"""Domain 1: the creator's own documents, searchable, without any of it
leaving the machine (`docs/plans/domains/01-knowledge.md`).

`read_file` could already open a PDF; what it could not do was *find*
one. Every question re-read whatever it was pointed at, so "what did my
insurance policy say about flood cover" was only answerable by someone
who already knew which file to open -- which is the whole difficulty.

Why this lives under `simorgh/execution/` rather than in a
`simorgh/knowledge/` subsystem of its own: a subsystem may not import
another subsystem's internals
(`tests/simorgh/test_module_boundaries.py`, from
`docs/blueprint/02-system-architecture.md` section 4). The tools are in
Execution, so an engine anywhere else would be unreachable from them.
A future `knowledge` subsystem doing background scanning would talk to
its tools over the bus like everything else; the index and the
retrieval are library code either way, and library code belongs next to
its only caller.

Everything here is derived and reproducible. Delete
`workspace/knowledge/index.db` and rescan: that is the whole recovery
story, and it is why nothing in the index is precious.
"""

from .api import Chunk, Citation, Document, Hit, SourceSpec

__all__ = ["Chunk", "Citation", "Document", "Hit", "SourceSpec"]
