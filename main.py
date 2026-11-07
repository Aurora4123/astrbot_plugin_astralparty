import asyncio
from contextlib import suppress

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from .catalog import CatalogError, CatalogStore, character_label, map_label


@register("astral_party_random", "aurora4123", "《吉星派对》随机地图角色抽取", "1.1.0")
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.catalog = CatalogStore(
            StarTools.get_data_dir("astrbot_plugin_astralparty") / "catalog.json"
        )
        self._update_task = None

    async def initialize(self):
        if self.config.get("auto_update", True):
            # Never delay plugin loading or draws while the wiki is unreachable.
            self._update_task = asyncio.create_task(self._auto_update())

    async def _refresh(self):
        result = await self.catalog.refresh()
        if self.catalog.last_error:
            logger.warning("星趴数据同步失败: %s", self.catalog.last_error)
        else:
            logger.info(result)
        return result

    async def _auto_update(self):
        while True:
            await self._refresh()
            try:
                hours = float(self.config.get("update_interval_hours", 24))
                if not 1 <= hours <= 720:
                    hours = 24
            except (TypeError, ValueError):
                hours = 24
            await asyncio.sleep(hours * 3600)

    @filter.command("星趴角色")
    async def random_character(self, event: AstrMessageEvent):
        """随机一个已上线角色"""
        try:
            yield event.plain_result(
                f"你抽取到的角色是：{character_label(self.catalog.random_character())}"
            )
        except CatalogError as exc:
            yield event.plain_result(str(exc))

    @filter.command("星趴地图")
    async def random_map(self, event: AstrMessageEvent, mode: str = ""):
        """随机地图，可选：合作 / 对战 / 限时 / 全部"""
        try:
            game_map = self.catalog.random_map(
                mode or self.config.get("default_map_mode", "合作")
            )
            yield event.plain_result(f"你抽取到的地图是：{map_label(game_map)}")
        except CatalogError as exc:
            yield event.plain_result(str(exc))

    @filter.command("星趴队伍")
    async def random_team(self, event: AstrMessageEvent):
        """随机一支不重复的四人队伍"""
        try:
            names = "\n".join(character_label(c) for c in self.catalog.team())
            yield event.plain_result(f"你抽取到的队伍是：\n{names}")
        except CatalogError as exc:
            yield event.plain_result(str(exc))

    @filter.command("星趴随机")
    async def random(self, event: AstrMessageEvent, mode: str = ""):
        """随机地图和四人队伍，可选：合作 / 对战 / 限时 / 全部"""
        try:
            game_map = self.catalog.random_map(
                mode or self.config.get("default_map_mode", "合作")
            )
            names = "\n".join(character_label(c) for c in self.catalog.team())
            yield event.plain_result(
                f"你抽取到的地图是：{map_label(game_map)}\n队伍：\n{names}"
            )
        except CatalogError as exc:
            yield event.plain_result(str(exc))

    @filter.command("星趴更新")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def update_catalog(self, event: AstrMessageEvent):
        """管理员：立即同步图鉴"""
        yield event.plain_result(await self._refresh())

    @filter.command("星趴数据")
    async def catalog_status(self, event: AstrMessageEvent):
        """查看数据时间、角色与地图数量"""
        yield event.plain_result(self.catalog.status())

    @filter.command("星趴帮助")
    async def help(self, event: AstrMessageEvent):
        """查看插件用法"""
        yield event.plain_result(
            "/星趴角色：随机角色\n/星趴队伍：四人队伍（不重复）\n"
            "/星趴地图 [合作/对战/限时/全部]\n"
            "/星趴随机 [合作/对战/限时/全部]\n"
            "/星趴数据：查看数据状态\n/星趴更新：管理员同步图鉴\n"
            "限时地图为历史存档，不代表当前开放。"
        )

    async def terminate(self):
        if self._update_task:
            self._update_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._update_task


