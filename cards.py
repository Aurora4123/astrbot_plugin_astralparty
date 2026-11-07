"""Prepare safe, self-contained HTML cards for AstrBot's image renderer."""
import asyncio
import base64
import hashlib
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .catalog import now_cst
from .roles import ROLE_LABELS, composition_label

ASSET_ROOT = Path(__file__).with_name("data") / "avatars"
TEMPLATE_PATH = Path(__file__).with_name("templates") / "result.html"
MODE_NAMES = {"pve": "合作挑战", "pvp": "标准对战", "limited": "限时玩法"}
POSITIONS = ("一号位", "二号位", "三号位", "四号位")
MAX_IMAGE_BYTES = 1024 * 1024


def trusted_avatar_url(url):
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.hostname == "patchwiki.biligame.com"
            and parsed.port in (None, 443) and not parsed.username
            and not parsed.password and parsed.path.startswith("/images/starengine/"))


def image_mime(body):
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("Unsupported avatar format")


def to_data_uri(body):
    return f"data:{image_mime(body)};base64," + base64.b64encode(body).decode("ascii")


def download_avatar(url):
    if not trusted_avatar_url(url):
        raise ValueError("Untrusted avatar host")
    request = Request(url, headers={"User-Agent": "AstralPartyCatalog/1.2"})
    with urlopen(request, timeout=6) as response:
        if not trusted_avatar_url(response.geturl()):
            raise ValueError("Untrusted avatar redirect")
        body = response.read(MAX_IMAGE_BYTES + 1)
    if len(body) > MAX_IMAGE_BYTES:
        raise ValueError("Avatar too large")
    image_mime(body)
    return body


class AvatarCache:
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self._semaphore = asyncio.Semaphore(4)
        self._failed = {}

    def _bundled(self, character):
        cid = character["id"]
        if cid.isascii() and cid.isdigit():
            return ASSET_ROOT / f"{cid}.png"
        return None

    def _load(self, character):
        bundled = self._bundled(character)
        if bundled and bundled.is_file():
            return to_data_uri(bundled.read_bytes())
        url = character.get("avatar_url", "")
        if not trusted_avatar_url(url):
            return ""
        path = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".img")
        if path.is_file():
            try:
                if path.stat().st_size <= MAX_IMAGE_BYTES:
                    return to_data_uri(path.read_bytes())
            except (OSError, ValueError):
                pass
        # Failed resources are retried after ten minutes, not on every draw.
        import time
        if time.monotonic() - self._failed.get(url, float("-inf")) < 600:
            return ""
        try:
            body = download_avatar(url)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(body)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return to_data_uri(body)
        except (OSError, ValueError):
            self._failed[url] = time.monotonic()
            return ""

    async def get(self, character):
        async with self._semaphore:
            try:
                return await asyncio.to_thread(self._load, character)
            except (OSError, ValueError):
                return ""


async def prepare_card(characters, game_map, kind, avatars):
    portraits = await asyncio.gather(*(avatars.get(c) for c in characters))
    slots = []
    for index, (character, portrait) in enumerate(zip(characters, portraits)):
        slots.append({"position": POSITIONS[index] if len(characters) > 1 else "本次角色",
                      "name": character["name"], "title": character["title"],
                      "role": ROLE_LABELS.get(character.get("assigned_role"), ""),
                      "avatar": portrait, "initial": character["name"][:1]})
    titles = {"random": "星趴随机开局", "team": "星趴随机队伍",
              "character": "星趴角色抽取", "map": "星趴地图抽取"}
    metadata = []
    if game_map:
        metadata.extend([("地图", game_map["name"]),
                         ("玩法", MODE_NAMES.get(game_map.get("play_mode"), MODE_NAMES[game_map["mode"]]))])
    if slots:
        metadata.append(("队伍" if len(slots) > 1 else "角色",
                         f"{len(slots)} 人" if len(slots) > 1 else "随机抽取 1 名角色"))
    if characters and all(c.get("assigned_role") for c in characters):
        metadata.append(("阵容", composition_label([c["assigned_role"] for c in characters])))
    return {"heading": titles[kind], "metadata": metadata, "slots": slots,
            "limited": bool(game_map and game_map["mode"] == "limited"),
            "generated_at": now_cst().strftime("%Y-%m-%d %H:%M:%S")}
