from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .characters import Character, get_character_team
from .characters import Map

@register("astral_party_random", "aurora4123", "《吉星派对》随机地图角色抽取", "1.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    @filter.command("星趴角色")
    async def random_character(self, event: AstrMessageEvent):
        """随机一个角色"""
        #character = Character.get_random_character();
        yield event.plain_result(f"你抽取到的角色是：{Character.get_random_character}")

    @filter.command("星趴地图")
    async def random_map(self, event: AstrMessageEvent):
        yield event.plain_result(f"你抽取到的地图是：{Map.get_random_map}")
    @filter.command("星趴队伍")
    async def random_team(self, event: AstrMessageEvent):
        """随机一个队伍"""
        team =  get_character_team()
        message = f"你抽取到的队伍是：\n"
        for character in team:
            message += f"{character.value} \n"
        yield event.plain_result(message)
    @filter.command("星趴随机")
    async def random(self, event: AstrMessageEvent):
        """随机一个地图和队伍"""
        team = get_character_team()
        _map = Map.get_random_map()
        map_message = f"你抽取到的地图是：{_map.value}\n"
        team_message = f"队伍：\n"
        for character in team:
            team_message += f" {character.value} \n"
        yield event.plain_result(map_message + team_message)

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""

