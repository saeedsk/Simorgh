"""Cognee as a second sidecar (stage 15 item 5b): github.com/topoteretes/cognee.

Fed the month with `cognee.add` then `cognee.cognify`, one episode at a
time so the per-episode cost is measurable and the cap is checked between
episodes. Each question is one `cognee.search` in `GRAPH_COMPLETION` mode
with `only_context=True`: the graph context its completion would have been
given, not an answer, which is the same "what reached the block" check the
native systems get. The context is free text, split into lines; Cognee
marks nothing as superseded, so a temporal question sees every value it
kept as current.

Storage is Cognee's local-first set only: SQLite for relational data,
LanceDB for vectors, and its embedded graph store, all under a temporary
`data_root_directory` / `system_root_directory`. The graph store is
whatever the installed version defaults to (Ladybug, a Kuzu fork, in
1.6.x); the run reads it back and reports it, and refuses one that needs
a server.

Privacy: Cognee's datasets are the only partition it has, so a private
episode goes into dataset `person_<speaker>` and the rest into
`household`, and a question searches the household plus the asker's own.
The report says so.

Model calls: Cognee calls `litellm.acompletion` and `litellm.aembedding`
by attribute, so the meter wraps those two module functions for the run
and restores them after. `litellm.max_budget` is set to the cap as well,
as a second stop if a call path goes around the wrapper. Telemetry is off
through `TELEMETRY_DISABLED`, set before the import.

    pip install cognee        # into a separate environment, never the core
"""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from .corpus import Episode, Question
from .meter import metered
from .sidecar import Sidecar, groups_for

TELEMETRY_ENV = "TELEMETRY_DISABLED"

#: Graph stores that are a file in a directory, not a server.
LOCAL_GRAPH_STORES = frozenset({"ladybug", "kuzu", "networkx", "turso"})


class CogneeSide(Sidecar):
    name = "cognee"
    install = "pip install cognee"
    # cognify per episode: chunk graph extraction, summary, plus embeddings.
    calls_per_episode = 5

    def load(self):
        os.environ[TELEMETRY_ENV] = "1"
        try:
            import cognee
            import litellm
            from cognee import SearchType
        except ImportError as exc:
            return None, f"cognee is not installed ({exc})"
        return SimpleNamespace(cognee=cognee, litellm=litellm, SearchType=SearchType), ""

    async def open(self) -> None:
        lib = self._lib
        s = self.settings
        self._tmp = tempfile.TemporaryDirectory(prefix="simorgh-cognee-")
        data_root = os.path.join(self._tmp.name, "data")
        system_root = os.path.join(self._tmp.name, "system")
        # The environment for whatever Cognee reads lazily, the config
        # setters for what it has already read.
        os.environ.update({
            "DATA_ROOT_DIRECTORY": data_root, "SYSTEM_ROOT_DIRECTORY": system_root,
            "DB_PROVIDER": "sqlite", "VECTOR_DB_PROVIDER": "lancedb",
        })
        config = lib.cognee.config
        config.data_root_directory(data_root)
        config.system_root_directory(system_root)
        config.set_llm_config({"llm_provider": "custom", "llm_model": f"openai/{s.model}",
                               "llm_endpoint": s.base_url, "llm_api_key": s.api_key})
        config.set_embedding_config({"embedding_provider": "custom", "embedding_model": f"openai/{s.embed_model}",
                                     "embedding_endpoint": s.base_url, "embedding_api_key": s.api_key,
                                     "embedding_dimensions": s.embed_dimensions})
        store = graph_store()
        if store and store not in LOCAL_GRAPH_STORES:
            raise RuntimeError(f"cognee's graph store is {store!r}, which needs a server; refusing")
        self.notes["store"] = f"SQLite + LanceDB + {store or 'unknown'} graph store, temporary directory"
        self.notes["privacy"] = ("one dataset per person (private episodes in person_<speaker>, the rest in "
                                 "household); Cognee has no per-fact person scope")
        # The meter on the two functions every Cognee model call goes through.
        litellm = lib.litellm
        # Cognee sends `dimensions` with every embedding; LiteLLM refuses it
        # for an "openai/" model unless told to drop what a provider does not
        # take (the first paid run died on UnsupportedParamsError).
        self._saved_drop = getattr(litellm, "drop_params", False)
        litellm.drop_params = True
        self._saved = {name: getattr(litellm, name) for name in ("acompletion", "aembedding") if hasattr(litellm, name)}
        for name, fn in self._saved.items():
            setattr(litellm, name, metered(fn, self.meter))
        self._saved_budget = getattr(litellm, "max_budget", None)
        litellm.max_budget = self.meter.cap_usd
        self._datasets: set[str] = set()

    async def close(self) -> None:
        try:
            litellm = self._lib.litellm if self._lib is not None else None
            for name, fn in (getattr(self, "_saved", None) or {}).items():
                setattr(litellm, name, fn)
            if litellm is not None and hasattr(self, "_saved_budget"):
                litellm.max_budget = self._saved_budget
            if litellm is not None and hasattr(self, "_saved_drop"):
                litellm.drop_params = self._saved_drop
        finally:
            tmp = getattr(self, "_tmp", None)
            if tmp is not None:
                tmp.cleanup()

    async def ingest(self, episode: Episode) -> None:
        self.meter.check()
        cognee = self._lib.cognee
        await cognee.add(f"{episode.speaker.title()}: {episode.text}", dataset_name=episode.group)
        self._datasets.add(episode.group)
        await cognee.cognify(datasets=[episode.group])

    async def context(self, question: Question) -> list[str]:
        self.meter.check()
        datasets = [g for g in groups_for(question.asker) if g in self._datasets]
        if not datasets:
            return []
        result = await self._lib.cognee.search(
            query_text=question.text, query_type=self._lib.SearchType.GRAPH_COMPLETION,
            datasets=datasets, only_context=True, top_k=10)
        return text_lines(result)


def graph_store() -> str:
    """Which graph store this Cognee would use, or "" when it cannot say."""
    try:
        from cognee.infrastructure.databases.graph.config import get_graph_config
    except ImportError:
        return ""
    try:
        return str(get_graph_config().graph_database_provider or "").lower()
    except Exception:  # noqa: BLE001 -- a report line, not a reason to stop
        return ""


def text_lines(result) -> list[str]:
    """Whatever shape `search(only_context=True)` returns, as lines of text."""
    out: list[str] = []

    def walk(value) -> None:
        if value is None:
            return
        if isinstance(value, str):
            out.extend(line.strip() for line in value.splitlines() if line.strip())
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)
        else:
            walk(str(value))

    walk(result)
    return out


__all__ = ["CogneeSide", "LOCAL_GRAPH_STORES", "TELEMETRY_ENV", "graph_store", "text_lines"]
