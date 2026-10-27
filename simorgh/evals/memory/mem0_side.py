"""Mem0 as a third sidecar (stage 15 item 5c): github.com/mem0ai/mem0.

The `mem0ai` open-source package in local mode. Fed the month with
`Memory.add(messages, user_id=...)`, one episode at a time, with `infer`
on, so Mem0 extracts its own facts and makes its own ADD / UPDATE /
DELETE decision against what it already holds. Each question is
`Memory.search(question, user_id=...)`, and every returned memory's text
is one block line. Mem0 rewrites a memory in place when it updates one,
so it keeps no past value: a `temporal_before` question can only miss.

Storage: Qdrant in local mode (`qdrant-client`'s embedded store, a
directory, no server; Mem0's default vector store, and one of its own
dependencies, so nothing more to install) and the SQLite history, both in
a temporary directory. No graph store: Mem0 Graph needs Neo4j, which this
stage refuses. `MEM0_DIR` -- where Mem0 keeps its config file and user id
-- also points into a temporary directory before the import, so a run
never writes `~/.mem0`.

Privacy: `user_id` is Mem0's per-person scope, and maps cleanly. A
private episode is added under `person_<speaker>`, the rest under
`household`, and a question searches the household plus the asker's own
(two searches, merged by score). The report says so.

Model calls: Mem0 builds its own `openai.OpenAI` clients, one in its LLM
(`memory.llm.client`) and one in its embedder
(`memory.embedding_model.client`). Both are swapped for metered ones
right after `Memory.from_config`, before any call; a Memory without
either seam is refused rather than run unmetered. Telemetry is off
through `MEM0_TELEMETRY=False`, set before the import.

    pip install mem0ai        # into a separate environment, never the core
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from types import SimpleNamespace

from .corpus import Episode, Question
from .meter import MeteredClient
from .sidecar import Sidecar, groups_for

TELEMETRY_ENV = "MEM0_TELEMETRY"
#: Where Mem0 writes its config file and anonymous user id (`~/.mem0` otherwise).
HOME_ENV = "MEM0_DIR"
#: Mem0's OpenAI LLM sends everything to OpenRouter when this is set.
OPENROUTER_ENV = "OPENROUTER_API_KEY"
COLLECTION = "simorgh_memory_eval"
#: Memories per search, per user_id.
LIMIT = 10


class Mem0Side(Sidecar):
    name = "mem0"
    install = "pip install mem0ai"
    # add() with infer: one extraction call, one update-decision call, and
    # an embedding per extracted fact (about two).
    calls_per_episode = 4
    # One embedding per search, and a question searches two user_ids.
    calls_per_question = 2

    def load(self):
        os.environ[TELEMETRY_ENV] = "False"
        if not os.environ.get(HOME_ENV):
            # Mem0 creates this directory and writes into it at import.
            home = tempfile.mkdtemp(prefix="simorgh-mem0-home-")
            atexit.register(shutil.rmtree, home, True)
            os.environ[HOME_ENV] = home
        try:
            from mem0 import Memory
        except ImportError as exc:
            return None, f"mem0ai is not installed ({exc})"
        return SimpleNamespace(Memory=Memory), ""

    async def open(self) -> None:
        s = self.settings
        self._tmp = tempfile.TemporaryDirectory(prefix="simorgh-mem0-")
        self._openrouter = os.environ.pop(OPENROUTER_ENV, None)
        config = {
            "llm": {"provider": "openai",
                    "config": {"model": s.model, "api_key": s.api_key, "openai_base_url": s.base_url}},
            "embedder": {"provider": "openai",
                         "config": {"model": s.embed_model, "api_key": s.embed_api_key,
                                    "openai_base_url": s.embed_base_url, "embedding_dims": s.embed_dimensions}},
            "vector_store": {"provider": "qdrant",
                             "config": {"collection_name": COLLECTION, "embedding_model_dims": s.embed_dimensions,
                                        "path": os.path.join(self._tmp.name, "qdrant"), "on_disk": True}},
            "history_db_path": os.path.join(self._tmp.name, "history.db"),
            "version": "v1.1",
        }
        memory = self._lib.Memory.from_config(config)
        # The meter on both clients Mem0 built, before anything calls them.
        for owner in ("llm", "embedding_model"):
            part = getattr(memory, owner, None)
            if getattr(part, "client", None) is None:
                raise RuntimeError(f"mem0's Memory has no {owner}.client to meter; refusing to run unmetered")
            part.client = MeteredClient(part.client, self.meter)
        if getattr(memory, "graph", None) is not None or getattr(memory, "enable_graph", False):
            raise RuntimeError("mem0 has a graph store configured, which needs Neo4j; refusing")
        self.memory = memory
        self.notes["store"] = "Qdrant local mode + SQLite history, temporary directory; no graph store"
        self.notes["privacy"] = ("user_id per person (private episodes under person_<speaker>, the rest under "
                                 "household), Mem0's own per-person scope")

    async def close(self) -> None:
        try:
            if getattr(self, "_openrouter", None) is not None:
                os.environ[OPENROUTER_ENV] = self._openrouter
            memory = getattr(self, "memory", None)
            client = getattr(getattr(memory, "vector_store", None), "client", None)
            if client is not None and hasattr(client, "close"):
                client.close()         # Qdrant local holds a lock on its directory
        finally:
            tmp = getattr(self, "_tmp", None)
            if tmp is not None:
                tmp.cleanup()

    async def ingest(self, episode: Episode) -> None:
        self.meter.check()
        self.memory.add([{"role": "user", "content": f"{episode.speaker.title()}: {episode.text}"}],
                        user_id=episode.group)

    async def context(self, question: Question) -> list[str]:
        self.meter.check()
        found = []
        for user_id in groups_for(question.asker):
            found.extend(results(self.memory.search(question.text, user_id=user_id, limit=LIMIT)))
        found.sort(key=lambda m: -float(m.get("score") or 0.0))
        return memory_lines(found)


def results(reply) -> list[dict]:
    """`search`'s memories: `{"results": [...]}` (v1.1), or the bare list (v1.0)."""
    if isinstance(reply, dict):
        reply = reply.get("results") or []
    return [m for m in reply or () if isinstance(m, dict)]


def memory_lines(memories) -> list[str]:
    """Each memory's text, once, as a block line."""
    lines: list[str] = []
    for m in memories:
        text = str(m.get("memory") or "").strip()
        if text and text not in lines:
            lines.append(text)
    return lines


__all__ = ["COLLECTION", "HOME_ENV", "LIMIT", "Mem0Side", "TELEMETRY_ENV", "memory_lines", "results"]
