import asyncio
import copy
from contextlib import nullcontext
import sys
import threading
from datetime import datetime
from html import escape
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import (BUNDLED_PATH, CST, CatalogError, CatalogStore, atomic_save,
                     load_json, parse_wiki, validate)


@pytest.fixture
def store(tmp_path):
    return CatalogStore(tmp_path / "catalog.json")


def pages(data):
    # Minimal form of the card attributes/table markup observed on BWIKI.
    cards = "".join(
        '<div class="divsort" data-param1="{id}" data-param2="{name}" '
        'data-param3="{title}" data-param12="{release_at}"></div>'.format(
            **{k: escape(v, quote=True) for k, v in c.items()}
        ) for c in data["characters"]
    )
    rows = []
    for label, mode in (("合作挑战模式", "pve"), ("标准对战模式", "pvp"), ("限时玩法", "limited")):
        links = "".join(
            f'<a href="/starengine/test" title="{m["name"]}"><img></a>'
            f'<a href="/starengine/test" title="{m["name"]}">{m["name"]}</a>'
            for m in data["maps"] if m["mode"] == mode
        )
        rows.append(f"<tr><th>{label}</th><td>{links}</td></tr>")
    return cards, "<table>" + "".join(rows) + "</table>"


def fetcher_for(data):
    cards, maps = pages(data)
    return lambda url: cards if "%E8%A7%92" in url else maps


def test_snapshot_and_current_content(store):
    assert len(store.characters()) == 35
    assert [len(store.maps(m)) for m in ("pve", "pvp", "limited")] == [8, 5, 6]
    assert {"远野汉娜", "橘雪莉", "赛克斯"} <= {c["name"] for c in store.characters()}
    assert "森秋幻境" in {m["name"] for m in store.maps()}
    assert all(m["mode"] == "pve" for m in store.maps())


def test_team_draw_without_replacement(store):
    # Force random.sample to select the tail: new characters must be reachable.
    with patch("catalog.random.sample", side_effect=lambda pool, n: pool[-n:]):
        assert {c["id"] for c in store.team()} == {"303", "304", "305", "306"}
    team = store.team()
    assert len({c["id"] for c in team}) == 4
    with patch("catalog.random.choice", side_effect=lambda pool: pool[-1]):
        assert store.random_map()["name"] == "森秋幻境"


def test_future_release_at_china_time(store):
    future = dict(store.data["characters"][0], id="130", name="测试预告", release_at="209911121400")
    store.data["characters"].append(future)
    assert future not in store.characters(datetime(2099, 11, 12, 13, 59, tzinfo=CST))
    assert future in store.characters(datetime(2099, 11, 12, 14, 0, tzinfo=CST))


def test_real_markup_shape_round_trip(store):
    data = parse_wiki(*pages(store.data))
    assert data["characters"] == store.data["characters"]
    assert len(data["maps"]) == 19  # image and text anchors are deduplicated
    assert len({m["id"] for m in data["maps"]}) == 19


def test_refresh_persists_new_data_and_draws_it(store):
    candidate = copy.deepcopy(store.data)
    candidate["characters"].append(dict(candidate["characters"][0], id="999", name="新角色"))
    with patch("catalog.now_cst", return_value=datetime(2099, 1, 1, tzinfo=CST)):
        result = asyncio.run(store.refresh(fetcher_for(candidate)))
    assert "更新成功" in result
    assert load_json(store.cache_path)["characters"][-1]["name"] == "新角色"
    assert store.characters()[-1]["name"] == "新角色"
    restarted = CatalogStore(store.cache_path)
    assert restarted.characters()[-1]["name"] == "新角色"


@pytest.mark.parametrize("failure", ["network", "captcha", "missing_character", "missing_maps", "write"])
def test_failure_keeps_memory_and_disk(store, failure):
    atomic_save(store.cache_path, store.data)
    before = store.cache_path.read_bytes()
    candidate = copy.deepcopy(store.data)
    if failure == "missing_character":
        candidate["characters"].pop()
    elif failure == "missing_maps":
        candidate["maps"].pop(0)
    fetch = fetcher_for(candidate)
    if failure == "network":
        def fetch(url):
            raise TimeoutError("offline")
    elif failure == "captcha":
        fetch = lambda url: "<html>captcha</html>"
    with patch("catalog.atomic_save", side_effect=OSError("disk full")) if failure == "write" else nullcontext():
        result = asyncio.run(store.refresh(fetch))
    assert "更新失败" in result
    assert store.cache_path.read_bytes() == before
    assert len(store.characters()) == 35
    assert len(store.maps()) == 8
    assert store.last_error


def test_invalid_and_old_caches_fall_back(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text("{broken", encoding="utf-8")
    assert len(CatalogStore(path).characters()) == 35
    data = load_json(BUNDLED_PATH)
    data["synced_at"] = "2000-01-01T00:00:00+08:00"
    data["characters"].pop()
    atomic_save(path, data)
    assert len(CatalogStore(path).characters()) == 35


def test_rejects_duplicate_ids_and_invalid_release(store):
    candidate = copy.deepcopy(store.data)
    candidate["characters"].append(candidate["characters"][0])
    with pytest.raises(CatalogError):
        validate(candidate)
    candidate = copy.deepcopy(store.data)
    candidate["characters"][0]["release_at"] = "invalid"
    with pytest.raises(CatalogError):
        validate(candidate)


def test_invalid_mode_is_a_useful_error(store):
    with pytest.raises(CatalogError, match="模式请选择"):
        store.random_map("wrong")


def test_simultaneous_refresh_reuses_attempt(store):
    entered, release = threading.Event(), threading.Event()
    base_fetch = fetcher_for(store.data)
    def blocked_fetch(url):
        entered.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test synchronization")
        return base_fetch(url)
    async def run():
        first = asyncio.create_task(store.refresh(blocked_fetch))
        await asyncio.to_thread(entered.wait, 5)
        second = await store.refresh(blocked_fetch)
        release.set()
        assert "正在进行" in second
        assert "更新成功" in await first
    asyncio.run(run())
