"""Graphiti as a sidecar (stage 15 item 5): github.com/getzep/graphiti.

Fed the month episode by episode with `Graphiti.add_episode`, into
FalkorDBLite -- the embedded FalkorDB, `redislite.async_falkordb_client`,
no server -- in a temporary directory. Each question is one
`Graphiti.search(question, group_ids=...)`, and the returned edges are the
block: one edge's `fact` a line, and an edge Graphiti has invalidated
(`invalid_at` or `expired_at` set) as a `PAST` line, which is the closest
thing it has to the native `was`.

Privacy: Graphiti has no per-person scope. Its `group_id` partition is
the closest, so a private episode goes into `person_<speaker>` and the
rest into `household`, and a question searches the household plus the
asker's own group. The report says so (`notes["privacy"]`).

Its model calls go through `OpenAIGenericClient`, `OpenAIEmbedder` and
`OpenAIRerankerClient`, each handed the same metered `AsyncOpenAI` pointed
at Together. The plain `search` uses reciprocal-rank fusion, so the
reranker is constructed (Graphiti would otherwise build one that wants an
OpenAI key) but not called.

    pip install 'graphiti-core[falkordblite]'     # Python 3.12+; a separate environment, never the core
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

from .corpus import Episode, Question
from .meter import MeteredClient
from .score import PAST
from .sidecar import Sidecar, groups_for

TELEMETRY_ENV = "GRAPHITI_TELEMETRY_ENABLED"


class GraphitiSide(Sidecar):
    name = "graphiti"
    install = "pip install 'graphiti-core[falkordblite]'"
    # The plan's "5-10 model calls per episode": extraction, node and edge
    # resolution, invalidation, plus the embeddings.
    calls_per_episode = 8

    def load(self):
        # Before the import: graphiti reads it at call time, but a module
        # that phones home at import would already have done so.
        os.environ[TELEMETRY_ENV] = "false"
        try:
            from graphiti_core import Graphiti
            from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
            from graphiti_core.driver.falkordb_driver import FalkorDriver
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
            from graphiti_core.nodes import EpisodeType
            from openai import AsyncOpenAI
            from redislite.async_falkordb_client import AsyncFalkorDB
        except ImportError as exc:
            return None, f"graphiti-core with falkordblite is not installed ({exc})"
        return SimpleNamespace(
            Graphiti=Graphiti, OpenAIRerankerClient=OpenAIRerankerClient, FalkorDriver=FalkorDriver,
            OpenAIEmbedder=OpenAIEmbedder, OpenAIEmbedderConfig=OpenAIEmbedderConfig, LLMConfig=LLMConfig,
            OpenAIGenericClient=OpenAIGenericClient, EpisodeType=EpisodeType, AsyncOpenAI=AsyncOpenAI,
            AsyncFalkorDB=AsyncFalkorDB), ""

    async def open(self) -> None:
        lib = self._lib
        s = self.settings
        self._tmp = tempfile.TemporaryDirectory(prefix="simorgh-graphiti-")
        self._falkor = lib.AsyncFalkorDB(dbfilename=os.path.join(self._tmp.name, "graph.db"))
        driver = lib.FalkorDriver(falkor_db=self._falkor)
        client = MeteredClient(lib.AsyncOpenAI(api_key=s.api_key, base_url=s.base_url), self.meter)
        llm_config = lib.LLMConfig(api_key=s.api_key, model=s.model, small_model=s.model, base_url=s.base_url)
        self.graphiti = lib.Graphiti(
            graph_driver=driver,
            llm_client=lib.OpenAIGenericClient(config=llm_config, client=client),
            embedder=lib.OpenAIEmbedder(
                config=lib.OpenAIEmbedderConfig(api_key=s.embed_api_key, base_url=s.embed_base_url,
                                                embedding_model=s.embed_model,
                                                embedding_dim=s.embed_dimensions),
                client=MeteredClient(lib.AsyncOpenAI(api_key=s.embed_api_key, base_url=s.embed_base_url),
                                     self.meter)),
            cross_encoder=lib.OpenAIRerankerClient(config=llm_config, client=client),
        )
        await self.graphiti.build_indices_and_constraints()
        self.notes["store"] = "FalkorDBLite (embedded), temporary directory"
        self.notes["privacy"] = ("group_id per person (private episodes in person_<speaker>, the rest in "
                                 "household); Graphiti has no per-fact person scope")

    async def close(self) -> None:
        try:
            graphiti = getattr(self, "graphiti", None)
            if graphiti is not None:
                await graphiti.close()
        finally:
            tmp = getattr(self, "_tmp", None)
            if tmp is not None:
                tmp.cleanup()

    async def ingest(self, episode: Episode) -> None:
        self.meter.check()
        await self.graphiti.add_episode(
            name=f"episode-{episode.index}",
            episode_body=f"{episode.speaker.title()}: {episode.text}",
            source_description="a household member talking to Sim",
            reference_time=datetime.fromtimestamp(episode.ts, timezone.utc),
            source=self._lib.EpisodeType.message,
            group_id=episode.group,
        )

    async def context(self, question: Question) -> list[str]:
        self.meter.check()
        edges = await self.graphiti.search(question.text, group_ids=groups_for(question.asker), num_results=10)
        return edge_lines(edges)


def edge_lines(edges) -> list[str]:
    """Graphiti's edges as block lines; an invalidated edge is a `PAST` line."""
    lines = []
    for edge in edges or ():
        fact = str(getattr(edge, "fact", "") or "").strip()
        if not fact:
            continue
        ended = getattr(edge, "invalid_at", None) or getattr(edge, "expired_at", None)
        lines.append(f"{PAST}{fact}" if ended else fact)
    return lines


__all__ = ["GraphitiSide", "TELEMETRY_ENV", "edge_lines"]
