"""Compatibility helpers for the original draw API, backed by bundled JSON."""
import random
from dataclasses import dataclass

from .catalog import BUNDLED_PATH, character_label, load_json, now_cst


@dataclass(frozen=True)
class DrawResult:
    value: str


class Character:
    @classmethod
    def get_random_character(cls):
        return get_character_team(1)[0]


class Map:
    @classmethod
    def get_random_map(cls):
        maps = [m for m in load_json(BUNDLED_PATH)["maps"] if m["mode"] == "pve"]
        return DrawResult(random.choice(maps)["name"])


def get_character_team(num=4):
    now = now_cst().strftime("%Y%m%d%H%M")
    pool = [c for c in load_json(BUNDLED_PATH)["characters"] if c["release_at"] <= now]
    return [DrawResult(character_label(c)) for c in random.sample(pool, num)]
