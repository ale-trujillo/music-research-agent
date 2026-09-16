"""A request with no visitor id has no list -- it does not get everyone's.

The first design kept one favorites list for the whole deployment, which on a
public URL meant every visitor read, and could delete from, the owner's
shortlist. Per-visitor keys fixed that, but the fallback survived the fix: a
request arriving without an `x-visitor` header still landed in a bucket named
`favorites:shared`, readable and writable by anyone who omitted the header.

That is not a hypothetical. A tab left open from before the deploy saved four
artists through the old JavaScript, they went to the shared bucket, and one of
them was from the private acceptance set -- served publicly by an endpoint that
needed no header at all to read it. The bug reads as favorites "disappearing",
because the save and the next page load used different keys.

So the absence of an id is now an answer, not a default: reads return nothing
and writes are refused.
"""

import pytest

from music_research_agent.store import (
    EmptyStore,
    JsonFileStore,
    RedisStore,
    clean_scope,
    open_store,
    scoped_storage,
)

REDIS_ENV = {"KV_REST_API_URL": "https://fake.upstash.io", "KV_REST_API_TOKEN": "fake"}


@pytest.fixture
def deployed(monkeypatch):
    """A deployment that keeps one list per visitor."""
    for name, value in REDIS_ENV.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def local(monkeypatch):
    """One person, one machine, one file."""
    for name in (*REDIS_ENV, "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("missing", [None, "", "   ", "!!!", "///", ".."])
def test_an_unusable_id_opens_no_list(deployed, missing):
    """Including ids that sanitise away to nothing -- those are absent too."""
    store = open_store(missing)
    assert isinstance(store, EmptyStore)
    assert store.load() == []


def test_an_unusable_id_cannot_write():
    with pytest.raises(RuntimeError):
        EmptyStore().save_all([])


def test_redis_refuses_a_scopeless_key():
    """The backstop: no code path may construct a store without an id."""
    with pytest.raises(ValueError):
        RedisStore("https://fake.upstash.io", "fake", "")


def test_two_visitors_never_share_a_key(deployed):
    one = open_store("2f1c9e4a-0b3d-4c7e-9a11-5d6f8e2b1c04")
    two = open_store("8a3b1d6c-7e2f-4a09-b512-1c4d9f0e3a76")
    assert one.KEY != two.KEY
    assert one.KEY.startswith("favorites:")


def test_an_id_is_sanitised_before_it_reaches_a_key(deployed):
    """A key becomes a URL path segment in the REST API, so an id that tries to
    climb out of it -- to reach FLUSHALL, or another visitor's list -- keeps
    only the harmless characters."""
    store = open_store("abc/../../flush")
    assert store.KEY == "favorites:abcflush"
    assert not {"/", ".", ":"} & set(store.KEY.removeprefix("favorites:"))


def test_a_long_id_is_capped():
    assert len(clean_scope("a" * 500)) == 64


def test_local_use_still_keeps_one_file(local):
    """The CLI has one person and no id to offer; it must not be refused."""
    assert scoped_storage() is False
    assert isinstance(open_store(), JsonFileStore)


def test_the_shared_bucket_name_is_gone():
    """Named explicitly: this string reappearing is the regression."""
    from pathlib import Path

    import music_research_agent.store as store_module

    source = Path(store_module.__file__).read_text()
    assert "favorites:shared" not in source


def test_discovery_has_a_seed_for_a_visitor_with_no_favorites():
    """Per-visitor lists made the seedless first visit the normal one."""
    from music_research_agent.api import DEMO_SEEDS

    assert DEMO_SEEDS, "an empty default puts the error back on the discover tab"


class TestOverHttp:
    """The rejection has to happen at the edge, before anything is written."""

    @pytest.fixture
    def client(self, deployed):
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from music_research_agent.api import app

        return TestClient(app)

    def test_reading_without_an_id_is_empty_not_shared(self, client):
        response = client.get("/api/favorites")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.parametrize("headers", [{}, {"x-visitor": ""}, {"x-visitor": "!!!"}])
    def test_saving_without_an_id_is_refused(self, client, headers):
        response = client.post("/api/favorites", json={"query": "anyone"}, headers=headers)
        assert response.status_code == 400, "a silent success hides the artists"
        assert "x-visitor" in response.json()["detail"]

    def test_forgetting_without_an_id_is_refused(self, client):
        """404 here would have leaked whether a name sat in the shared bucket."""
        response = client.delete("/api/favorites/Someone")
        assert response.status_code == 400
