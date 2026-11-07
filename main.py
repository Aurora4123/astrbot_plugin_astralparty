import asyncio
from contextlib import suppress
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from .catalog import CatalogError, CatalogStore, MODE_ALIASES, character_label, map_label
from .cards import AvatarCache, TEMPLATE_PATH, prepare_card
from .card_renderer import render_card
from .roles import CompositionError, parse_composition


def parse_draw_args(first="", second="", allow_mode=True):
    mode, composition = None, []
    for token in (first + " " + second).split():
        if token.lower() in MODE_ALIASES:
            if not allow_mode or mode is not None:
                raise CompositionError("地图模式只能指定一次；队伍命令不需要地图模式")
            mode = MODE_ALIASES[token.lower()]
        else:
            composition.append(token)
    composition = "".join(composition)
    parse_composition(composition)
    return mode or "pve", composition


@register("astral_party_random", "aurora4123", "《吉星派对》随机地图角色抽取", "1.3.0")
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.catalog = CatalogStore(
            StarTools.get_data_dir("astrbot_plugin_astralparty") / "catalog.json"
        )
        self._update_task = None
        self.avatars = AvatarCache(self.catalog.cache_path.parent / "avatars")
        self._card_template = TEMPLATE_PATH.read_text(encoding="utf-8")

    async def _reply_draw(self, event, text, characters=(), game_map=None, kind="random"):
        if self.config.get("image_output", True):
            local_image = None
            try:
                data = await prepare_card(characters, game_map, kind, self.avatars)
                try:
                    local_image = await asyncio.to_thread(
                        render_card, data, self.catalog.cache_path.parent / "renders",
                        self.config.get("font_path", ""),
                    )
                    image = local_image
                except Exception as exc:
                    logger.warning("星趴本地图片渲染失败，尝试 AstrBot 渲染服务: %s", exc)
                    image = await asyncio.wait_for(
                        self.html_render(
                            self._card_template, data,
                            options={"full_page": True, "type": "png",
                                     "viewport": {"width": 960, "height": 720}},
                        ), timeout=45,
                    )
                # Sending directly lets us fall back if an adapter rejects images.
                await event.send(event.image_result(image))
                return
            except Exception as exc:
                logger.warning("星趴结果图片生成或发送失败，回退文字: %s", exc)
            finally:
                if local_image:
                    with suppress(OSError):
                        Path(local_image).unlink()
        yield event.plain_result(text)

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
        if self.catalog.last_role_error:
            logger.warning("星趴定位同步失败，沿用已有分类: %s", self.catalog.last_role_error)
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
            character = self.catalog.random_character()
            text = f"你抽取到的角色是：{character_label(character)}"
            async for result in self._reply_draw(event, text, [character], kind="character"):
                yield result
        except CatalogError as exc:
            yield event.plain_result(str(exc))

    @filter.command("星趴地图")
    async def random_map(self, event: AstrMessageEvent, mode: str = ""):
        """随机地图，可选：合作 / 对战 / 限时 / 全部"""
        try:
            game_map = self.catalog.random_map(
                mode or "合作"
            )
            text = f"你抽取到的地图是：{map_label(game_map)}"
            async for result in self._reply_draw(event, text, game_map=game_map, kind="map"):
                yield result
        except CatalogError as exc:
            yield event.plain_result(str(exc))

    @filter.command("星趴队伍")
    async def random_team(self, event: AstrMessageEvent, composition: str = "", extra: str = ""):
        """随机四人队伍，可选：2辅2c / 1辅3c / 1辅1坦2c"""
        try:
            _, composition = parse_draw_args(composition, extra, allow_mode=False)
            team = self.catalog.team(composition=composition)
            names = "\n".join(character_label(c) for c in team)
            async for result in self._reply_draw(
                event, f"你抽取到的队伍是：\n{names}", team, kind="team"
            ):
                yield result
        except (CatalogError, CompositionError) as exc:
            yield event.plain_result(str(exc))

    @filter.command("星趴随机")
    async def random(self, event: AstrMessageEvent, mode: str = "", composition: str = ""):
        """随机地图和队伍，例如：2辅2c，或 合作 1辅3c"""
        try:
            mode, composition = parse_draw_args(mode, composition)
            game_map = self.catalog.random_map(mode)
            team = self.catalog.team(composition=composition)
            names = "\n".join(character_label(c) for c in team)
            text = f"你抽取到的地图是：{map_label(game_map)}\n队伍：\n{names}"
            async for result in self._reply_draw(event, text, team, game_map):
                yield result
        except (CatalogError, CompositionError) as exc:
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
            "/星趴角色：随机角色\n/星趴队伍 [组合]：四人队伍\n"
            "/星趴地图 [合作/对战/限时/全部]\n"
            "/星趴随机 [模式] [组合]\n"
            "组合：2辅2c、1辅3c、1辅1坦2c、4c（共4人）\n"
            "辅=辅助，c=输出，坦=生存，任=自由；攻/卡可分别指定攻击/卡牌输出\n"
            "示例：/星趴随机 2辅2c；/星趴随机 合作 1辅3c\n"
            "/星趴数据：查看数据状态\n/星趴更新：管理员同步图鉴\n"
            "不指定模式时只抽合作地图；限时地图仅在已确认的开放时间内参与抽取。"
        )

    async def terminate(self):
        if self._update_task:
            self._update_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._update_task


