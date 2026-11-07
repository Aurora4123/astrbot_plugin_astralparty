import asyncio
import base64
import importlib
import logging
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
cards = importlib.import_module(ROOT.name + ".cards")
catalog = importlib.import_module(ROOT.name + ".catalog")


@pytest.fixture
def store(tmp_path):
    return catalog.CatalogStore(tmp_path / "catalog.json")


def test_all_current_roles_have_distinct_real_avatars(store, tmp_path):
    cache = cards.AvatarCache(tmp_path / "avatars")
    uris = [cache._load(c) for c in store.characters()]
    assert len(uris) == 35
    assert len(set(uris)) == 35
    assert all(u.startswith("data:image/png;base64,") for u in uris)
    for uri in uris:
        assert base64.b64decode(uri.split(",")[1]).startswith(b"\x89PNG\r\n\x1a\n")


def test_card_includes_all_slots_and_escapes_external_text(store, tmp_path):
    team = store.characters()[-4:]
    team[0] = dict(team[0], name='<script>alert("x")</script>')
    data = asyncio.run(cards.prepare_card(
        team, store.maps("pvp")[-1], "random", cards.AvatarCache(tmp_path)
    ))
    html = Environment().from_string(cards.TEMPLATE_PATH.read_text(encoding="utf-8")).render(**data)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert html.count('class="slot"') == 4
    assert html.count('class="avatar"') == 4
    assert "四号位" in html
    assert "丛林冒险" in html
    assert "疯狂" not in html  # Do not invent unsupported difficulty settings.
    assert "不重复抽取" not in html
    assert ("队伍", "4 人") in data["metadata"]


def test_unknown_avatar_has_named_placeholder(tmp_path):
    c = {"id": "../escape", "name": "新角色", "title": "新称号"}
    data = asyncio.run(cards.prepare_card([c], None, "character", cards.AvatarCache(tmp_path)))
    assert data["slots"][0]["avatar"] == ""
    html = Environment().from_string(cards.TEMPLATE_PATH.read_text(encoding="utf-8")).render(**data)
    assert "placeholder" in html and "新角色" in html


def test_local_renderer_produces_png_for_long_names(store, tmp_path):
    from PIL import Image
    renderer = importlib.import_module(ROOT.name + ".card_renderer")
    try:
        chosen_font = renderer.find_font()
    except OSError:
        chosen_font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        if not Path(chosen_font).is_file():
            pytest.skip("No test font installed")
    team = store.characters()[-4:]
    team[0] = dict(team[0], name="测试长姓名" * 12)
    data = asyncio.run(cards.prepare_card(team, store.maps()[0], "random", cards.AvatarCache(tmp_path)))
    path = renderer.render_card(data, tmp_path, chosen_font)
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.width == 960
        assert 1300 <= image.height <= 1800


def test_plugin_local_render_sends_and_cleans_temporary_file(monkeypatch, tmp_path):
    plugin = load_plugin(monkeypatch, tmp_path)
    module = sys.modules[ROOT.name + ".main"]
    path = tmp_path / "card.png"
    path.write_bytes((cards.ASSET_ROOT / "122.png").read_bytes())
    monkeypatch.setattr(module, "render_card", lambda *args: str(path))
    plugin.html_render = AsyncMock()
    event = Event()
    assert asyncio.run(collect(plugin.random_character(event))) == []
    assert event.sent == [("image", str(path))]
    assert not path.exists()
    plugin.html_render.assert_not_called()


def test_download_cache_and_failed_resource_backoff(tmp_path):
    cache = cards.AvatarCache(tmp_path)
    sample = (cards.ASSET_ROOT / "122.png").read_bytes()
    c = {"id": "999", "name": "新角色",
         "avatar_url": "https://patchwiki.biligame.com/images/starengine/new.png"}
    with patch.object(cards, "download_avatar", return_value=sample) as fetch:
        assert cache._load(c) == cache._load(c)
        fetch.assert_called_once()
    c["avatar_url"] += "?v=2"
    with patch.object(cards, "download_avatar", side_effect=OSError("offline")) as fetch:
        assert cache._load(c) == ""
        assert cache._load(c) == ""
        fetch.assert_called_once()


@pytest.mark.parametrize("url", [
    "http://patchwiki.biligame.com/images/starengine/a.png",
    "https://evil.example/images/starengine/a.png",
    "https://patchwiki.biligame.com.evil.example/images/starengine/a.png",
    "file:///etc/passwd",
])
def test_rejects_untrusted_avatar_urls(url):
    assert not cards.trusted_avatar_url(url)


def load_plugin(monkeypatch, tmp_path):
    api = types.ModuleType("astrbot.api")
    api.AstrBotConfig = dict
    api.logger = logging.getLogger("test")
    events = types.ModuleType("astrbot.api.event")
    def decorator(*args, **kwargs):
        return lambda fn: fn
    events.filter = types.SimpleNamespace(
        command=decorator, permission_type=decorator,
        PermissionType=types.SimpleNamespace(ADMIN="admin"),
    )
    events.AstrMessageEvent = object
    stars = types.ModuleType("astrbot.api.star")
    class Star:
        def __init__(self, context):
            pass
    stars.Star = Star
    stars.Context = object
    stars.register = decorator
    stars.StarTools = types.SimpleNamespace(get_data_dir=lambda name: tmp_path)
    for name, mod in (("astrbot", types.ModuleType("astrbot")), ("astrbot.api", api),
                      ("astrbot.api.event", events), ("astrbot.api.star", stars)):
        monkeypatch.setitem(sys.modules, name, mod)
    name = ROOT.name + ".main"
    monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module(name)
    # Exercise HTML service fallback independently of the host's font set.
    monkeypatch.setattr(module, "render_card", lambda *a, **kw: (_ for _ in ()).throw(OSError("no local font")))
    return module.MyPlugin(None, {"auto_update": False})


class Event:
    def __init__(self, fail_send=False):
        self.sent = []
        self.fail_send = fail_send
    def plain_result(self, text):
        return ("text", text)
    def image_result(self, path):
        return ("image", path)
    async def send(self, message):
        if self.fail_send:
            raise RuntimeError("adapter rejected image")
        self.sent.append(message)


async def collect(generator):
    return [item async for item in generator]


def test_plugin_sends_card_with_same_draw(monkeypatch, tmp_path):
    plugin = load_plugin(monkeypatch, tmp_path)
    plugin.html_render = AsyncMock(return_value="https://renderer.example/card.png")
    event = Event()
    result = asyncio.run(collect(plugin.random(event, "对战")))
    assert result == []
    assert event.sent == [("image", "https://renderer.example/card.png")]
    data = plugin.html_render.call_args.args[1]
    assert len({s["name"] for s in data["slots"]}) == 4
    assert data["metadata"][1] == ("玩法", "标准对战")


@pytest.mark.parametrize("command,args", [
    ("random", ("2辅2c",)),
    ("random", ("合作", "2辅2c")),
    ("random", ("2辅2c", "合作")),
    ("random_team", ("2辅2c",)),
    ("random_team", ("2辅", "2c")),
])
def test_composition_command_outputs_assigned_roles(monkeypatch, tmp_path, command, args):
    plugin = load_plugin(monkeypatch, tmp_path)
    plugin.html_render = AsyncMock(return_value="https://renderer.example/card.png")
    event = Event()
    assert asyncio.run(collect(getattr(plugin, command)(event, *args))) == []
    data = plugin.html_render.call_args.args[1]
    assert [s["role"] for s in data["slots"]] == ["辅助", "辅助", "输出", "输出"]
    assert ("阵容", "2辅2C") in data["metadata"]
    assert len({s["name"] for s in data["slots"]}) == 4
    if command == "random":
        assert data["metadata"][1] == ("玩法", "合作挑战")


def test_composition_validation_and_text_fallback(monkeypatch, tmp_path):
    plugin = load_plugin(monkeypatch, tmp_path)
    plugin.config["image_output"] = False
    invalid = asyncio.run(collect(plugin.random(Event(), "2辅1c")))
    assert "合计必须为4" in invalid[0][1]
    result = asyncio.run(collect(plugin.random_team(Event(), "2辅2c")))
    assert result[0][1].count("（辅助）") == 2
    assert result[0][1].count("（输出）") == 2


@pytest.mark.parametrize("old_default", ["全部", "对战"])
@pytest.mark.parametrize("command", ["random", "random_map"])
def test_no_argument_commands_ignore_old_pvp_default(monkeypatch, tmp_path, old_default, command):
    plugin = load_plugin(monkeypatch, tmp_path)
    plugin.config["default_map_mode"] = old_default
    plugin.html_render = AsyncMock(return_value="https://renderer.example/card.png")
    event = Event()
    asyncio.run(collect(getattr(plugin, command)(event)))
    data = plugin.html_render.call_args.args[1]
    assert data["metadata"][1] == ("玩法", "合作挑战")


@pytest.mark.parametrize("failure", ["render", "send", "disabled"])
def test_plugin_falls_back_to_original_draw(monkeypatch, tmp_path, failure):
    plugin = load_plugin(monkeypatch, tmp_path)
    event = Event(fail_send=failure == "send")
    plugin.html_render = AsyncMock(return_value="https://renderer.example/card.png")
    if failure == "render":
        plugin.html_render.side_effect = RuntimeError("offline")
    if failure == "disabled":
        plugin.config["image_output"] = False
    c = plugin.catalog.characters()[-1]
    plugin.catalog.random_character = lambda: c
    result = asyncio.run(collect(plugin.random_character(event)))
    assert len(result) == 1 and result[0][0] == "text"
    assert "橘雪莉" in result[0][1]
    if failure == "disabled":
        plugin.html_render.assert_not_called()
