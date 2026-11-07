import asyncio
import copy
import importlib
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
roles = importlib.import_module(ROOT.name + ".roles")
catalog = importlib.import_module(ROOT.name + ".catalog")


@pytest.mark.parametrize("text, expected", [
    ("2辅2c", ("support", "support", "damage", "damage")),
    ("２辅助２Ｃ", ("support", "support", "damage", "damage")),
    ("1辅 1坦 + 2输出", ("support", "tank", "damage", "damage")),
    ("4c", ("damage",) * 4),
    ("2卡2攻", ("card", "card", "attack", "attack")),
    ("1辅3任意", ("support", "any", "any", "any")),
    ("", ()),
])
def test_composition_syntax(text, expected):
    assert roles.parse_composition(text) == expected


@pytest.mark.parametrize("text", ["2辅1c", "5c", "2辅x2c", "2foo2c", "2辅-2c",
                                  "c2辅2", "0辅", "2辅2c垃圾", "4" * 81])
def test_invalid_syntax_is_not_silently_ignored(text):
    with pytest.raises(roles.CompositionError):
        roles.parse_composition(text)


def test_classification_keeps_ties_and_manual_overrides():
    hybrid = {"role_scores": [15, 60, 60, 15]}
    assert roles.roles_for(hybrid) == {"any", "card", "damage", "support"}
    assert roles.roles_for(dict(hybrid, roles=["support"])) == {"any", "support"}
    assert roles.roles_for(dict(hybrid, roles=[])) == {"any"}
    assert roles.roles_for({}) == {"any"}
    assert roles.roles_for({}, hybrid) == {"any", "card", "damage", "support"}
    assert roles.roles_for({}, {"roles": ["support"]}) == {"any", "support"}


def test_overlapping_pools_do_not_consume_a_required_output():
    pool = [{"id": "a", "roles": ["support", "damage"]},
            {"id": "b", "roles": ["support"]},
            {"id": "c", "roles": ["damage"]},
            {"id": "d", "roles": ["damage"]}]
    for seed in range(15):
        team = roles.draw_composition(pool, "1辅3c", rng=random.Random(seed))
        assert team[0]["id"] == "b"
        assert {c["id"] for c in team} == {"a", "b", "c", "d"}
    assert all("assigned_role" not in c for c in pool)


def test_impossible_shared_pool_returns_error_instead_of_duplicates():
    pool = [{"id": "a", "roles": ["support", "damage"]},
            {"id": "b", "roles": ["support", "damage"]},
            {"id": "c", "roles": ["tank"]},
            {"id": "d", "roles": ["tank"]}]
    with pytest.raises(roles.CompositionError, match="无法组成"):
        roles.draw_composition(pool, "2辅2c")


@pytest.mark.parametrize("composition", ["2辅2c", "1辅3c", "1辅1坦2c", "4c", "4辅", "4任", "2攻2卡"])
def test_current_roster_satisfies_requested_slots_without_mutation(tmp_path, composition):
    store = catalog.CatalogStore(tmp_path / "catalog.json")
    before = copy.deepcopy(store.data)
    team = store.team(composition=composition)
    assert len(team) == len({c["id"] for c in team}) == 4
    for c, expected in zip(team, roles.parse_composition(composition)):
        assert c["assigned_role"] == expected
        assert expected in roles.roles_for(c)
    assert store.data == before


def test_old_cache_without_classification_uses_new_bundled_defaults(tmp_path):
    cached = catalog.load_json(catalog.BUNDLED_PATH)
    cached["synced_at"] = "2099-01-01T00:00:00+08:00"
    for c in cached["characters"]:
        c.pop("role_scores")
    path = tmp_path / "catalog.json"
    catalog.atomic_save(path, cached)
    store = catalog.CatalogStore(path)
    assert len(store.team(composition="2辅2c")) == 4


def score_html(rows):
    head = "<tr>" + "".join(f"<th>{h}</th>" for h in roles.RoleScoreParser.HEADERS) + "</tr>"
    body = "".join(
        f'<tr><td><a><img alt="UT Item Hero {cid}.png"></a></td>'
        + "".join(f"<td>{n}</td>" for n in scores) + "</tr>"
        for cid, scores in rows.items()
    )
    return "<table>" + head + body + "</table>"


def test_role_score_parser_uses_exact_table_and_hero_ids():
    html = "<table><tr><th>其他</th></tr><tr><td>999</td></tr></table>"
    html += score_html({"102": [15, 15, 100, 15], "306": [100, 15, 15, 15]})
    assert roles.parse_role_scores(html) == {"102": [15, 15, 100, 15], "306": [100, 15, 15, 15]}
    with pytest.raises(roles.CompositionError):
        roles.parse_role_scores("<html>captcha</html>")


def test_role_sync_failure_keeps_classification_and_core_update_succeeds(tmp_path):
    from test_catalog import pages
    store = catalog.CatalogStore(tmp_path / "catalog.json")
    characters, maps = pages(store.data)
    def fetch(url):
        if url == catalog.ROLE_URL:
            raise TimeoutError("role source offline")
        return characters if url == catalog.CHARACTER_URL else maps
    assert "更新成功" in asyncio.run(store.refresh(fetch))
    assert store.last_role_error
    assert len(store.team(composition="2辅2c")) == 4


def test_role_sync_updates_scores_without_removing_manual_roles(tmp_path):
    from test_catalog import pages
    store = catalog.CatalogStore(tmp_path / "catalog.json")
    store.data["characters"][0]["roles"] = ["support"]
    characters, maps = pages(store.data)
    def fetch(url):
        if url == catalog.ROLE_URL:
            return score_html({"101": [100, 15, 15, 15]})
        return characters if url == catalog.CHARACTER_URL else maps
    assert "更新成功" in asyncio.run(store.refresh(fetch))
    assert not store.last_role_error
    c = store.data["characters"][0]
    assert c["role_scores"] == [100, 15, 15, 15]
    assert roles.roles_for(c) == {"any", "support"}
