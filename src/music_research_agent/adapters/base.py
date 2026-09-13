"""Source adapters. One per public API, each able to fail alone.

Emerging artists are thin on data by definition, so a source returning nothing
is the normal case, not an error. Adapters never raise into the pipeline: a
failure is recorded on the bundle and the run continues.
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import httpx

from ..evidence import Evidence, EvidenceBundle
from ..schema import Citation, Identity

DEFAULT_TIMEOUT = 15.0


class SourceAdapter(ABC):
    name: str = "unnamed"
    requires_env: tuple[str, ...] = ()
    timeout: float = DEFAULT_TIMEOUT

    def is_configured(self) -> bool:
        return all(os.getenv(var) for var in self.requires_env)

    def missing_env(self) -> list[str]:
        return [var for var in self.requires_env if not os.getenv(var)]

    def cite(self, url: str | None = None, note: str | None = None) -> Citation:
        return Citation(
            source=self.name,
            url=url,
            retrieved_at=datetime.now(UTC),
            note=note,
        )

    @abstractmethod
    async def fetch(
        self, identity: Identity, client: httpx.AsyncClient
    ) -> list[Evidence]:
        """Return evidence for this artist. Empty list means 'no data', which
        is a legitimate and informative answer."""


class CorroboratingAdapter(SourceAdapter):
    """A source that cannot be trusted on a name match alone.

    Some sources identify an artist only by a display name, with no stable ID
    to join on. Probing the golden set, a short artist name matched a channel
    with 235,000 subscribers belonging to an unrelated producer in another
    country, while the real artist had about 24. Reporting that would have been
    wrong by four orders of magnitude, with a citation attached.

    These adapters run in a second wave and must corroborate a candidate
    against evidence already in the bundle before claiming anything.
    """

    @abstractmethod
    async def fetch_corroborated(
        self, identity: Identity, client: httpx.AsyncClient, bundle: "EvidenceBundle"
    ) -> list[Evidence]:
        ...

    async def fetch(self, identity: Identity, client: httpx.AsyncClient) -> list[Evidence]:
        raise NotImplementedError("use fetch_corroborated")


async def run_adapters(
    adapters: list[SourceAdapter],
    identity: Identity,
    bundle: EvidenceBundle,
    client: httpx.AsyncClient,
) -> EvidenceBundle:
    """Fan out in parallel. One adapter blowing up never sinks the run."""

    async def guarded(adapter: SourceAdapter) -> tuple[SourceAdapter, object]:
        if not adapter.is_configured():
            missing = ", ".join(adapter.missing_env())
            return adapter, RuntimeError(f"missing credentials: {missing}")
        try:
            async with asyncio.timeout(adapter.timeout):
                return adapter, await adapter.fetch(identity, client)
        except TimeoutError:
            return adapter, RuntimeError(f"timed out after {adapter.timeout}s")
        except Exception as exc:  # noqa: BLE001 - deliberate: isolate every failure
            return adapter, exc

    for adapter, result in await asyncio.gather(*(guarded(a) for a in adapters)):
        if isinstance(result, Exception):
            bundle.fail(adapter.name, str(result))
        elif result:
            bundle.add(*result)
        else:
            bundle.fail(adapter.name, "no data for this artist")
    return bundle


async def run_corroborating(
    adapters: list["CorroboratingAdapter"],
    identity: Identity,
    bundle: EvidenceBundle,
    client: httpx.AsyncClient,
) -> EvidenceBundle:
    """Second wave: sources that need the first wave's evidence to verify identity."""
    for adapter in adapters:
        if not adapter.is_configured():
            bundle.fail(adapter.name, f"missing credentials: {', '.join(adapter.missing_env())}")
            continue
        try:
            async with asyncio.timeout(adapter.timeout):
                found = await adapter.fetch_corroborated(identity, client, bundle)
            bundle.add(*found) if found else bundle.fail(
                adapter.name, "no candidate could be corroborated against known releases"
            )
        except TimeoutError:
            bundle.fail(adapter.name, f"timed out after {adapter.timeout}s")
        except Exception as exc:  # noqa: BLE001
            bundle.fail(adapter.name, str(exc))
    return bundle
