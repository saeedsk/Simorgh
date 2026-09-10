"""Is each domain switched on, and does it actually work?

`capabilities` answers that for Node and Docker. It could not answer it
for the six domains, because a domain is not a binary on `PATH` -- it is
a configuration plus an account plus, sometimes, a file that has to
have been built. So each one gets a `Connector`: construction never
raises, `probe()` is the health check, and the answer says exactly what
to set when the answer is no.

That reuses the machinery rather than adding another. `capabilities`
already lists every connector, `domains` groups the same probes by
domain, and a domain added later needs nothing new.

Two states are deliberately distinguished, because a person needs them
to be:

- **not configured** -- nothing has been set up, and the probe says the
  exact line to add. This is not a fault, and it must not read as one.
- **configured but not working** -- something has been set up and it is
  not answering. That IS a fault, and it is what a person wants to see.
"""

from __future__ import annotations

from pathlib import Path

from simorgh.contracts.connector import ConnectorStatus


class _DomainConnector:
    """Common shape: a name, what it needs, and a probe that never
    raises."""

    domain = ""
    packages: tuple[str, ...] = ()

    def __init__(self, config) -> None:
        self._config = config
        self.name = self.domain
        self.needs: tuple[str, ...] = ()

    async def close(self) -> None:
        return None

    def _repo_root(self) -> Path:
        return Path(getattr(self._config, "repo_root", "."))


class KnowledgeConnector(_DomainConnector):
    """The document index. "Configured" means a source has been added;
    "working" means something has actually been indexed, because a
    source that has never been scanned answers every question with
    nothing and looks exactly like an empty corpus."""

    domain = "knowledge"

    async def probe(self) -> ConnectorStatus:
        raw = str(getattr(self._config, "knowledge_index_path",
                          "workspace/knowledge/index.db"))
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self._repo_root() / path
        if not path.exists():
            return ConnectorStatus(
                False,
                "no documents indexed yet -- add a folder with "
                '`tool kb_sources add {"path": "~/Documents"}` then `tool kb_sources scan`',
                ("a document source",))
        try:
            from .knowledge.index import Index

            with Index(path) as index:
                stats = index.stats()
        except Exception as exc:  # noqa: BLE001 -- a probe never raises
            return ConnectorStatus(False, f"the index at {path} could not be opened ({exc!r})")
        if not stats["sources"]:
            return ConnectorStatus(False, "no document sources are configured -- "
                                          "`tool kb_sources add ...`", ("a document source",))
        if not stats["chunks"]:
            return ConnectorStatus(False, f"{stats['sources']} source(s) configured but nothing "
                                          f"indexed yet -- run `tool kb_sources scan`")
        return ConnectorStatus(True, f"{stats['documents']} document(s), {stats['chunks']} "
                                     f"passage(s) from {stats['sources']} source(s)")


class HomeConnector(_DomainConnector):
    """Home Assistant. The client's own probe already says the right
    thing, so this only supplies it with credentials."""

    domain = "home"

    def __init__(self, config, *, secrets=None, env=None) -> None:
        super().__init__(config)
        self.needs = ("HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN")
        self._secrets, self._env = secrets, env

    def _client(self):
        from .home.tools import _HomeTool

        return _HomeTool(self._config, secrets=self._secrets, env=self._env)._client()

    async def probe(self) -> ConnectorStatus:
        try:
            return await self._client().probe()
        except Exception as exc:  # noqa: BLE001
            return ConnectorStatus(False, f"home assistant: {exc!r}")


class EnergyConnector(_DomainConnector):
    """Meters plus a tariff. Either one missing means nothing can be
    priced, and which one is missing is the whole of what a person
    needs to know."""

    domain = "energy"

    async def probe(self) -> ConnectorStatus:
        meters = {k: v for k, v in (getattr(self._config, "energy_meters", {}) or {}).items() if v}
        from .energy.tools import _EnergyTool

        tariff = _EnergyTool(self._config)._tariff()
        missing = []
        if not meters:
            missing.append("[execution.energy_meters]")
        if tariff.name == "unset":
            missing.append("a tariff")
        if missing:
            return ConnectorStatus(
                False,
                "not set up: " + " and ".join(missing) + " -- `tool energy_tariff show` has an "
                "example, and `tool home_find energy` finds your meters",
                tuple(missing))
        gaps = tariff.gaps()
        if gaps:
            return ConnectorStatus(False, f"{len(meters)} meter(s) and the {tariff.name!r} "
                                          f"tariff, but no rate covers hour(s) {gaps}")
        return ConnectorStatus(True, f"{len(meters)} meter(s), tariff {tariff.name!r} "
                                     f"in {tariff.currency}")


class MediaConnector(_DomainConnector):
    """Media players come from Home Assistant, so this is really "does
    HA have any", which is a different answer from "is HA reachable"."""

    domain = "media"

    def __init__(self, config, *, secrets=None, env=None) -> None:
        super().__init__(config)
        self._secrets, self._env = secrets, env

    async def probe(self) -> ConnectorStatus:
        from .home.tools import _HomeTool

        client = _HomeTool(self._config, secrets=self._secrets, env=self._env)._client()
        if not client.configured:
            return ConnectorStatus(False, "media runs through Home Assistant, which is not "
                                          "configured -- see the `home` row",
                                   client.missing())
        try:
            entities = await client.states()
        except Exception as exc:  # noqa: BLE001
            return ConnectorStatus(False, f"home assistant is not answering ({exc})")
        players = [e for e in entities if e.entity_id.startswith("media_player.")]
        if not players:
            return ConnectorStatus(False, "Home Assistant has no media_player entities")
        return ConnectorStatus(True, f"{len(players)} player(s)")


class SecurityConnector(_DomainConnector):
    """Needs nothing at all, which is worth saying rather than leaving
    a person to wonder what to configure."""

    domain = "security"

    async def probe(self) -> ConnectorStatus:
        raw = str(getattr(self._config, "security_findings_path",
                          "workspace/security/findings.db"))
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self._repo_root() / path
        if not path.exists():
            return ConnectorStatus(True, "ready, nothing checked yet -- run `tool sec_self`")
        try:
            from .security.findings import FindingStore

            with FindingStore(path) as store:
                counts = store.counts()
                open_now = len(store.open_findings())
        except Exception as exc:  # noqa: BLE001
            return ConnectorStatus(False, f"the findings store could not be opened ({exc!r})")
        recorded = sum(n for status, n in counts.items() if status != "by_severity")
        if not recorded:
            return ConnectorStatus(True, "ready, nothing checked yet -- run `tool sec_self`")
        return ConnectorStatus(True, f"{open_now} open finding(s) of {recorded} recorded")


def domain_connectors(config, *, secrets=None, env=None) -> list:
    """One connector per domain that is not already covered.

    `pim` is absent on purpose: its accounts each register their own
    connector (`imap:fastmail`, `caldav:home`), which is the more useful
    grain -- one mailbox failing while another works is exactly the
    thing a single `pim` row would hide.
    """
    return [
        KnowledgeConnector(config),
        HomeConnector(config, secrets=secrets, env=env),
        EnergyConnector(config),
        MediaConnector(config, secrets=secrets, env=env),
        SecurityConnector(config),
    ]


__all__ = ["EnergyConnector", "HomeConnector", "KnowledgeConnector", "MediaConnector",
           "SecurityConnector", "domain_connectors"]
