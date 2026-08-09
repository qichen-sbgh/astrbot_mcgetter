from typing import List, Optional, Dict, Any
from pathlib import Path
import astrbot.core.message.components as Comp
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.event import MessageChain
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
from .script.get_server_info import get_server_status
from .script.template_selector import get_img, format_template_help, resolve_template_name
from .script.mcbind_service import McBindService
from .script.mcq_service import McqService
from .script.permission import can_manage_group_feature, can_use_mcq, resolve_roles
from .script.mcmod.service import McmodService, parse_mcmod_subcommand
from .script.mcmod.push_logic import can_push_more, record_push, should_trigger_cold_room
from .script.json_operate import (
    read_json, add_data, del_data, update_data,
    get_all_servers, get_server_info, get_server_by_name,
    update_server_status, auto_cleanup_servers,
    set_server_name_color, set_player_name_color,
    clear_server_name_color, clear_player_name_color, list_colors,
    get_group_template, set_group_template,
    set_server_tags, clear_server_tags, list_server_tags, parse_tags_argument,
)
import asyncio
import re
import time
from datetime import datetime
from time import localtime, strftime

# 常量定义
# 单台服务器状态查询超时（秒）；超时按离线卡处理
QUERY_TIMEOUT_SEC = 8.0

HELP_INFO = """
/mchelp 
--查看帮助

/mc   
--查询保存的服务器

/mcadd 服务器名称 服务器地址 [force] [群聊个数] [群号列表]
--添加要查询的服务器
--force: 可选参数，设为True时跳过预查询检查强制添加
--群聊个数: 可选参数，指定从群号列表中取前几个群
--群号列表: 可选参数，群号之间使用英文逗号分隔，如 123,456,789
--默认会添加到当前群；若填写群号列表，会在此基础上额外添加到指定群

/mcget 服务器名称/ID
--获取指定服务器的地址信息

/mcdel 服务器名称/ID 
--删除服务器

/mcup 服务器名称/ID [新名称] [新地址]
--更新服务器信息

/mclist
--列出所有服务器及其ID

/mccleanup
--手动触发自动清理（删除长期未查询成功的服务器，天数见插件配置 auto_cleanup_days）

/mcbind 服务器ID
--为指定服务器绑定数据压缩包（zip）
--发送命令后请在300秒（5分钟）内上传 .zip 文件
--压缩包内至少包含 mods 或 kubejs 文件夹之一

/mcq 服务器ID [提示词]
--使用 Agent 分析该服务器已绑定的 mods/kubejs 内容
--支持调用网络搜索工具补充信息

/mcop @用户 或 /mcop 用户ID
--将用户加入 /mcq 权限白名单
--仅系统管理员、群主、群管理员或群等级达到阈值的用户可操作

/mctem [list|<主题名>]
--查看或切换本群图片渲染主题
--内置: neon classic dashboard inventory soft compact
--也可使用数据目录 template/ 下的自定义脚本名

/mccolor server 服务器名称/ID 颜色
--设置该服务器在卡片上的名称颜色

/mccolor player 玩家名 颜色
--设置玩家名称颜色（本群所有服务器卡片生效）

/mccolor list
--查看已设置的颜色

/mccolor clear server 服务器名称/ID
/mccolor clear player 玩家名
--清除已设置的颜色

--颜色格式: #RRGGBB / #RGB / R,G,B  例如 #00FFC8 或 255,85,255

/mctag <名称/ID> 标签1 标签2
--为服务器设置标签（显示在卡片 ID/地址下一行，最多8个）
--标签可用空格或逗号分隔，例如：/mctag 主服 生存 互通,公益

/mctag clear <名称/ID>
--清除该服务器标签

/mctag list
--查看本群所有服务器标签

/mcmod <问题>
--检索 MC百科 并用 Agent 整理回答（含参考链接）

/mcmod search|info|random|latest|updates
--搜索 / 详情 / 随便看看 / 最新收录 / 有新动态

/mcmod push on|off|status|now
--本群百科推送开关（群主/群管/系统管理员）；now 立即推送
"""

@register("astrbot_mcgetter", "QiChen", "查询mc服务器信息和玩家列表,渲染为图片；集成MC百科", "1.8.0")
class MyPlugin(Star):
    """Minecraft服务器信息查询插件"""
    
    def __init__(self, context: Context, config: Optional[Dict[str, Any]] = None):
        """
        初始化插件

        Args:
            context: 插件上下文
        """
        super().__init__(context)
        self.plugin_config = config or {}
        self.mcbind_service = McBindService()
        self.mcq_service = McqService()
        self.mcmod_service = McmodService(get_config=self._get_plugin_config_value)
        # 并发 /mc 时串行写群 JSON，避免 last_success 等状态互相覆盖
        self._status_update_lock = asyncio.Lock()
        self._mcmod_scheduler_task: Optional[asyncio.Task] = None
        self._mcmod_last_evening_date: str = ""
        self._mcmod_last_hourly_slot: str = ""
        try:
            self._mcmod_scheduler_task = asyncio.create_task(self._mcmod_scheduler_loop())
        except Exception as e:
            logger.warning("mcmod scheduler start failed: %s", e)

    async def terminate(self):
        task = getattr(self, "_mcmod_scheduler_task", None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

    @filter.command("mchelp")
    async def get_help(self, event: AstrMessageEvent) -> MessageEventResult:
        """
        显示帮助信息

        Args:
            event: 消息事件

        Returns:
            包含帮助信息的消息结果
        """
        yield event.plain_result(HELP_INFO)

    @filter.command("mctem")
    async def change_mctem(
        self,
        event: AstrMessageEvent,
        name: str = "",
    ) -> MessageEventResult:
        """
        查看或切换本群卡片主题。

        /mctem
        /mctem list
        /mctem <主题名>
        """
        try:
            group_id = event.get_group_id()
            json_path = str(await self.get_json_path(group_id))
            current = await get_group_template(json_path)
            action = (name or "").strip()

            if not action or action.lower() in ("list", "ls", "help", "?"):
                yield event.plain_result(format_template_help(current))
                return

            ok, resolved, err = resolve_template_name(action)
            if not ok:
                yield event.plain_result(err)
                return

            success, msg = await set_group_template(json_path, resolved)
            if success:
                yield event.plain_result(msg + "\n使用 /mctem list 可查看全部主题。")
            else:
                yield event.plain_result(msg)
        except Exception as e:
            yield event.plain_result("切换模板时发生错误:" + str(e))

    @filter.command("mccolor")
    async def mccolor(
        self,
        event: AstrMessageEvent,
        action: str = "list",
        arg1: str = "",
        arg2: str = "",
        arg3: str = "",
    ) -> MessageEventResult:
        """
        设置渲染颜色。

        /mccolor server <名称/ID> <颜色>
        /mccolor player <玩家名> <颜色>
        /mccolor list
        /mccolor clear server <名称/ID>
        /mccolor clear player <玩家名>
        """
        try:
            group_id = event.get_group_id()
            json_path = str(await self.get_json_path(group_id))
            action = (action or "list").strip().lower()

            if action in ("list", "ls", "show", ""):
                yield event.plain_result(await list_colors(json_path))
                return

            if action == "server":
                if not arg1 or not arg2:
                    yield event.plain_result("用法：/mccolor server 服务器名称/ID 颜色\n例如：/mccolor server 主服 #00FFC8")
                    return
                ok, msg = await set_server_name_color(json_path, arg1, arg2)
                yield event.plain_result(msg)
                return

            if action == "player":
                if not arg1 or not arg2:
                    yield event.plain_result("用法：/mccolor player 玩家名 颜色\n例如：/mccolor player Steve #FF55FF")
                    return
                ok, msg = await set_player_name_color(json_path, arg1, arg2)
                yield event.plain_result(msg)
                return

            if action == "clear":
                target = (arg1 or "").strip().lower()
                name = arg2
                if target == "server":
                    if not name:
                        yield event.plain_result("用法：/mccolor clear server 服务器名称/ID")
                        return
                    ok, msg = await clear_server_name_color(json_path, name)
                    yield event.plain_result(msg)
                    return
                if target == "player":
                    if not name:
                        yield event.plain_result("用法：/mccolor clear player 玩家名")
                        return
                    ok, msg = await clear_player_name_color(json_path, name)
                    yield event.plain_result(msg)
                    return
                yield event.plain_result("用法：/mccolor clear server|player 名称")
                return

            # 兼容：/mccolor del server|player ...
            if action in ("del", "delete", "remove", "rm"):
                target = (arg1 or "").strip().lower()
                name = arg2
                if target == "server" and name:
                    ok, msg = await clear_server_name_color(json_path, name)
                    yield event.plain_result(msg)
                    return
                if target == "player" and name:
                    ok, msg = await clear_player_name_color(json_path, name)
                    yield event.plain_result(msg)
                    return
                yield event.plain_result("用法：/mccolor clear server|player 名称")
                return

            yield event.plain_result(
                "未知子命令。可用：\n"
                "/mccolor server 服务器 颜色\n"
                "/mccolor player 玩家名 颜色\n"
                "/mccolor list\n"
                "/mccolor clear server|player 名称"
            )
        except Exception as e:
            yield event.plain_result("设置颜色时发生错误:" + str(e))

    @filter.command("mctag")
    async def mctag(
        self,
        event: AstrMessageEvent,
        arg1: str = "",
        arg2: str = "",
        arg3: str = "",
        arg4: str = "",
        arg5: str = "",
        arg6: str = "",
        arg7: str = "",
        arg8: str = "",
        arg9: str = "",
    ) -> MessageEventResult:
        """
        服务器标签管理。

        /mctag <名称/ID> 标签1 标签2 ...
        /mctag clear <名称/ID>
        /mctag list
        """
        try:
            group_id = event.get_group_id()
            json_path = str(await self.get_json_path(group_id))
            a1 = (arg1 or "").strip()
            if not a1 or a1.lower() in ("list", "ls", "show"):
                yield event.plain_result(await list_server_tags(json_path))
                return

            if a1.lower() in ("clear", "del", "delete", "rm", "remove"):
                target = (arg2 or "").strip()
                if not target:
                    yield event.plain_result("用法：/mctag clear 服务器名称/ID")
                    return
                ok, msg = await clear_server_tags(json_path, target)
                yield event.plain_result(msg)
                return

            # 其余参数拼成标签文本
            rest_parts = [arg2, arg3, arg4, arg5, arg6, arg7, arg8, arg9]
            rest = " ".join(p for p in rest_parts if p)
            tags = parse_tags_argument(rest)
            if not tags:
                yield event.plain_result(
                    "用法：/mctag <名称/ID> 标签1 标签2\n"
                    "例如：/mctag 主服 生存 互通\n"
                    "清除：/mctag clear 主服\n"
                    "列表：/mctag list"
                )
                return
            ok, msg = await set_server_tags(json_path, a1, tags)
            yield event.plain_result(msg)
        except Exception as e:
            yield event.plain_result("设置标签时发生错误:" + str(e))

    @filter.command("mc")
    async def mcgetter(self, event: AstrMessageEvent) -> Optional[MessageEventResult]:
        """
        查询所有保存的服务器信息

        Args:
            event: 消息事件

        Returns:
            包含服务器信息图片的消息结果，如果出错则返回None
        """
        try:
            group_id = event.get_group_id()
            
            json_path = await self.get_json_path(group_id)

            json_data = await read_json(json_path)

            if not json_data or not json_data.get("servers"):
                yield event.plain_result("请先使用 /mcadd 添加服务器")
                return
            
            # 执行自动清理（天数来自插件配置）
            cleanup_days = self._get_cleanup_days()
            deleted_servers = await auto_cleanup_servers(json_path, days=cleanup_days)
            if deleted_servers:
                cleanup_message = (
                    f"自动清理完成，以下服务器因{cleanup_days}天未查询成功已被删除:\n"
                )
                for server in deleted_servers:
                    last_success_date = datetime.fromtimestamp(server['last_success_time']).strftime('%Y-%m-%d %H:%M:%S')
                    cleanup_message += f"• {server['name']} (ID: {server['id']}) - 地址: {server['host']} - 最后成功: {last_success_date}\n"
                yield event.plain_result(cleanup_message.strip())
                
                # 重新读取数据（清理后）
                json_data = await read_json(json_path)
                if not json_data.get("servers"):
                    yield event.plain_result("所有服务器已被清理，请重新添加服务器")
                    return
            
            servers = json_data.get("servers", {})
            colors = json_data.get("colors") if isinstance(json_data.get("colors"), dict) else {}
            template = str(json_data.get("template") or "neon")
            server_items = list(servers.items())

            async def _query_one(server_id: Any, server_info: Dict[str, Any]) -> Optional[str]:
                """单服查询；失败时尽量返回离线卡 base64。"""
                try:
                    return await self.get_img(
                        server_info["name"],
                        server_info["host"],
                        server_id,
                        str(json_path),
                        last_success_time=server_info.get("last_success_time"),
                        colors=colors,
                        template=template,
                        tags=server_info.get("tags") if isinstance(server_info.get("tags"), list) else [],
                    )
                except Exception:
                    try:
                        return await self._offline_card_base64(
                            server_id=server_id,
                            server_info=server_info,
                            colors=colors,
                            template=template,
                        )
                    except Exception:
                        return None

            # 并行查询所有服务器，保持与 server_items 相同的输出顺序
            results = await asyncio.gather(
                *[_query_one(sid, info) for sid, info in server_items],
                return_exceptions=False,
            )

            message_chain: List[Comp.Image] = []
            for img_b64 in results:
                if isinstance(img_b64, str) and img_b64:
                    message_chain.append(Comp.Image.fromBase64(img_b64))

            if message_chain:
                yield event.chain_result(message_chain)
            else:
                yield event.plain_result("没有可用的服务器信息，请检查服务器是否在线")
                
        except Exception as e:
            yield event.plain_result("查询服务器信息时发生错误:"+str(e))

    @filter.command("mcadd")
    async def mcadd(
        self,
        event: AstrMessageEvent,
        name: str,
        host: str,
        force: str = "false",
        group_count: int = 0,
        group_ids: str = ""
    ) -> MessageEventResult:
        """
        添加新的服务器

        Args:
            event: 消息事件
            name: 服务器名称
            host: 服务器地址
            force: 可选，True/False，是否跳过预查询
            group_count: 可选，指定从群号列表中取前几个群
            group_ids: 可选，群号列表，逗号分隔

        Returns:
            操作结果消息
        """

        try:
            # 解析 force，兼容 true/false/1/0/yes/no
            force_str = str(force).strip().lower()
            true_tokens = {"true", "1", "yes", "y", "on"}
            false_tokens = {"false", "0", "no", "n", "off", ""}

            force_enabled = False
            legacy_group_id = ""
            if force_str in true_tokens:
                force_enabled = True
            elif force_str in false_tokens:
                force_enabled = False
            elif re.fullmatch(r"\d+", force_str):
                # 兼容旧输入：/mcadd name host <群号>
                legacy_group_id = force_str
            else:
                yield event.plain_result("force 参数无效，请使用 True/False")
                return

            if group_count < 0:
                yield event.plain_result("群聊个数不能小于0")
                return

            parsed_group_ids: List[str] = []
            if group_ids:
                normalized_group_ids = str(group_ids).replace("，", ",")
                parsed_group_ids = [gid.strip() for gid in normalized_group_ids.split(",") if gid.strip()]
                invalid_group_ids = [gid for gid in parsed_group_ids if not re.fullmatch(r"\d+", gid)]
                if invalid_group_ids:
                    yield event.plain_result(f"以下群号不合法: {'、'.join(invalid_group_ids)}")
                    return

            target_group_ids: List[str] = []

            if legacy_group_id and not parsed_group_ids and group_count == 0:
                target_group_ids.append(legacy_group_id)

            if parsed_group_ids:
                if group_count > 0:
                    if len(parsed_group_ids) < group_count:
                        yield event.plain_result("群号列表数量少于指定的群聊个数")
                        return
                    target_group_ids.extend(parsed_group_ids[:group_count])
                else:
                    target_group_ids.extend(parsed_group_ids)

            # 检查host合法性
            if not re.match(r'^[a-zA-Z0-9.:-]+$', host):
                yield event.plain_result("服务器地址格式不正确，只能包含字母、数字和符号.:-")
                return
            elif await get_server_status(host) is None and not force_enabled:
                yield event.plain_result("预查询失败，请检查服务器是否在线或地址是否正确，或在完整的/mcadd命令后加上True 强制添加")
                return

            # 始终默认包含当前群
            current_group_id = event.get_group_id()
            if current_group_id:
                target_group_ids.insert(0, current_group_id)

            if not target_group_ids:
                yield event.plain_result("当前会话没有群号，请填写群号列表参数")
                return

            # 去重并保留顺序
            target_group_ids = list(dict.fromkeys(target_group_ids))

            result_lines: List[str] = []

            for group_id in target_group_ids:
                json_path = await self.get_json_path(group_id)

                # 检查当前群是否已存在相同地址
                try:
                    json_data = await read_json(json_path)
                    servers = json_data.get("servers", {})
                    duplicated_server = None
                    for server_id, server_info in servers.items():
                        if server_info.get('host') == host:
                            duplicated_server = (server_id, server_info)
                            break

                    if duplicated_server:
                        dup_id, dup_info = duplicated_server
                        result_lines.append(
                            f"群 {group_id}: 已存在相同地址服务器 {dup_info.get('name', '未知')} (ID: {dup_id})"
                        )
                        continue
                except Exception as e:
                    result_lines.append(f"群 {group_id}: 检查地址失败 - {str(e)}")
                    continue

                # 执行添加并获取新增ID
                if await add_data(json_path, name, host):
                    try:
                        json_data = await read_json(json_path)
                        servers = json_data.get("servers", {})
                        created_id = None
                        for server_id, server_info in servers.items():
                            if server_info.get('name') == name and server_info.get('host') == host:
                                created_id = server_id
                                break

                        if created_id:
                            result_lines.append(f"群 {group_id}: 添加成功 {name} (ID: {created_id})")
                        else:
                            result_lines.append(f"群 {group_id}: 添加成功 {name}")
                    except Exception as e:
                        result_lines.append(f"群 {group_id}: 添加成功，但读取新ID失败 - {str(e)}")
                else:
                    result_lines.append(f"群 {group_id}: 无法添加 {name}，请检查是否已存在")

            if result_lines:
                yield event.plain_result("\n".join(result_lines))
            else:
                yield event.plain_result("未执行任何添加操作")
                
        except Exception as e:
            yield event.plain_result("添加服务器时发生错误:"+str(e))

    @filter.command("mcdel")
    async def mcdel(self, event: AstrMessageEvent, identifier: str) -> MessageEventResult:
        """
        删除指定的服务器（支持通过名称或ID删除）

        Args:
            event: 消息事件
            identifier: 要删除的服务器名称或ID

        Returns:
            操作结果消息
        """
        try:
            group_id = event.get_group_id()
            json_path = await self.get_json_path(group_id)
            
            if await del_data(json_path, identifier):
                yield event.plain_result(f"成功删除服务器 {identifier}")
            else:
                yield event.plain_result(f"无法删除 {identifier}，请检查是否存在")
                
        except Exception as e:
            yield event.plain_result("删除服务器时发生错误:"+str(e))

    @filter.command("mcbind")
    async def mcbind(self, event: AstrMessageEvent, server_id: str) -> MessageEventResult:
        """
        为指定服务器绑定数据文件（上传zip后解压mods/kubejs）
        """
        message = await self.mcbind_service.begin_bind(event, server_id, self.get_json_path)
        if message:
            yield event.plain_result(message)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def handle_mcbind_file(self, event: AstrMessageEvent) -> MessageEventResult:
        """
        处理 /mcbind 后的文件上传消息
        """
        message = await self.mcbind_service.handle_file_message(event, self.get_json_path)
        if message:
            yield event.plain_result(message)

    @filter.command("mcget")
    async def mcget(self, event: AstrMessageEvent, identifier: str) -> MessageEventResult:
        """
        获取指定服务器的信息（支持通过名称或ID查找）
        """
        try:
            group_id = event.get_group_id()
            json_path = await self.get_json_path(group_id)
            
            server_info = await get_server_info(json_path, identifier)
            if not server_info:
                yield event.plain_result(f"没有找到服务器 {identifier}")
                return
                
            yield event.plain_result(f"{server_info['name']} (ID: {server_info['id']}) 的地址是:")
            yield event.plain_result(f"{server_info['host']}")
            
        except Exception as e:
            yield event.plain_result("获取服务器信息时发生错误:"+str(e))

    @filter.command("mcq")
    async def mcq(self, event: AstrMessageEvent) -> MessageEventResult:
        """对指定服务器已绑定内容进行 Agent 分析。"""
        try:
            if not await self._can_use_mcq(event):
                yield event.plain_result(
                    "你没有权限使用 /mcq。默认仅系统管理员、群主/群管理员、群等级达到阈值用户可用；"
                    "管理员可用 /mcop @用户 或 /mcop 用户ID 添加白名单。"
                )
                return

            result = await self.mcq_service.ask(event, self.context, self.get_json_path)
            yield event.plain_result(result)
        except Exception as e:
            yield event.plain_result("执行 mcq 分析时发生错误:" + str(e))

    @filter.command("mcmod")
    async def mcmod_cmd(self, event: AstrMessageEvent) -> MessageEventResult:
        """MC百科问答 / 子命令 / 推送控制。"""
        try:
            if not bool(self._get_plugin_config_value("mcmod_enabled", True)):
                yield event.plain_result("MC百科功能已在配置中关闭。")
                return

            sub, rest = parse_mcmod_subcommand(event.message_str)
            svc = self.mcmod_service

            if sub in {"help", "?"}:
                yield event.plain_result(svc.help_text())
                return

            if sub == "push":
                async for msg in self._mcmod_push_cmd(event, rest):
                    yield msg
                return

            if sub == "search":
                if not rest:
                    yield event.plain_result("用法：/mcmod search <关键词>")
                    return
                yield event.plain_result(await svc.cmd_search(rest))
                return

            if sub == "info":
                yield event.plain_result(await svc.cmd_info(rest))
                return

            if sub == "random":
                yield event.plain_result(
                    await svc.cmd_random(self.context, event.unified_msg_origin)
                )
                return

            if sub == "latest":
                n = 5
                if rest.strip().isdigit():
                    n = int(rest.strip())
                yield event.plain_result(await svc.cmd_latest(n))
                return

            if sub == "updates":
                n = 5
                if rest.strip().isdigit():
                    n = int(rest.strip())
                yield event.plain_result(await svc.cmd_updates(n))
                return

            # 默认：tool_loop 问答
            yield event.plain_result(await svc.ask_agent(event, self.context))
        except Exception as e:
            logger.exception("mcmod command failed")
            yield event.plain_result("执行 /mcmod 时发生错误:" + str(e))

    async def _mcmod_push_cmd(self, event: AstrMessageEvent, rest: str):
        parts = (rest or "").split()
        action = (parts[0].lower() if parts else "status")
        key = event.unified_msg_origin
        store = self.mcmod_service.push_store

        if action in {"on", "off", "now"}:
            if not await can_manage_group_feature(event):
                yield event.plain_result("仅系统管理员、群主或群管理员可操作推送开关。")
                return

        if action == "on":
            store.enable(key, umo=event.unified_msg_origin, group_id=event.get_group_id() or "")
            yield event.plain_result("已开启本群 MC百科推送（每晚19点 + 冷场概率推送）。")
            return
        if action == "off":
            store.disable(key)
            yield event.plain_result("已关闭本群 MC百科推送。")
            return
        if action == "now":
            st = store.get(key)
            if not st.enabled:
                store.enable(key, umo=event.unified_msg_origin, group_id=event.get_group_id() or "")
            text = await self.mcmod_service.build_push_payload(
                self.context,
                event.unified_msg_origin,
                n=int(self._get_plugin_config_value("mcmod_push_items", 3) or 3),
            )
            if not text:
                yield event.plain_result("推送内容生成失败，请稍后再试。")
                return
            st = store.get(key)
            record_push(st, "manual", time.time())
            store.update(key, st)
            yield event.plain_result(text)
            return

        st = store.get(key)
        st.ensure_today()
        yield event.plain_result(
            f"推送状态: {'开启' if st.enabled else '关闭'}\n"
            f"今日已推送: {st.today_push_count}\n"
            f"上次推送: {st.last_push_kind or '-'} @ {st.last_push_at or 0}"
        )

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_mcmod_hooks(self, event: AstrMessageEvent) -> MessageEventResult:
        """记录活跃度 + mcmod 链接自动导读。"""
        try:
            # 活跃度：仅已开启推送的群记录人类发言时间
            sender = event.get_sender_id()
            self_id = event.get_self_id()
            if sender and sender != self_id:
                umo = event.unified_msg_origin
                store = self.mcmod_service.push_store
                if store.has(umo) and store.get(umo).enabled:
                    store.touch_human(umo)

            text = (event.message_str or "").strip()
            if text.startswith("/"):
                return

            preview = await self.mcmod_service.handle_link_preview(event, self.context)
            if preview:
                yield event.plain_result(preview)
        except Exception as e:
            logger.warning("mcmod group hook failed: %s", e)

    @filter.command("mcop")
    async def mcop(self, event: AstrMessageEvent, user_id: str = "") -> MessageEventResult:
        """添加 /mcq 白名单用户。"""
        try:
            if not await self._can_manage_mcq_whitelist(event):
                yield event.plain_result("你没有权限执行 /mcop")
                return

            target_user_id = self._extract_target_user_id(event, user_id)
            if not target_user_id:
                yield event.plain_result("用法：/mcop @用户 或 /mcop 用户ID")
                return

            whitelist = self._get_mcq_whitelist()
            if target_user_id in whitelist:
                yield event.plain_result(f"用户 {target_user_id} 已在 /mcq 白名单中")
                return

            whitelist.append(target_user_id)
            self._set_plugin_config_value("mcq_whitelist_user_ids", whitelist)
            self._save_plugin_config()

            yield event.plain_result(f"已将用户 {target_user_id} 加入 /mcq 白名单")
        except Exception as e:
            yield event.plain_result("执行 mcop 时发生错误:" + str(e))

    @filter.command("mcup")
    async def mcup(self, event: AstrMessageEvent, identifier: str, new_name: Optional[str] = None, new_host: Optional[str] = None) -> MessageEventResult:
        """
        更新服务器信息（支持通过名称或ID更新）

        Args:
            event: 消息事件
            identifier: 要更新的服务器名称或ID
            new_name: 新的服务器名称（可选）
            new_host: 新的服务器地址（可选）

        Returns:
            操作结果消息
        """

        try:
            if not new_name and not new_host:
                yield event.plain_result("请提供要更新的信息（新名称或新地址）")
                return
                
            # 如果提供了新地址，检查格式
            if new_host and not re.match(r'^[a-zA-Z0-9.:-]+$', new_host):
                yield event.plain_result("服务器地址格式不正确，只能包含字母、数字和符号.:-")
                return
                
            group_id = event.get_group_id()
            json_path = await self.get_json_path(group_id)
            
            if await update_data(json_path, identifier, new_name, new_host):
                # 获取更新后的服务器信息
                updated_info = await get_server_info(json_path, identifier)
                if updated_info:
                    yield event.plain_result(f"成功更新服务器信息: {updated_info['name']} (ID: {updated_info['id']})")
                else:
                    yield event.plain_result(f"成功更新服务器 {identifier}")
            else:
                yield event.plain_result(f"无法更新 {identifier}，请检查是否存在或名称是否冲突")
                
        except Exception as e:
            yield event.plain_result("更新服务器信息时发生错误:"+str(e))

    @filter.command("mclist")
    async def mclist(self, event: AstrMessageEvent) -> MessageEventResult:
        """
        列出所有服务器及其ID
        """
        try:
            group_id = event.get_group_id()
            json_path = await self.get_json_path(group_id)
            
            servers = await get_all_servers(json_path)
            if not servers:
                yield event.plain_result("没有保存的服务器")
                return

            nodes: List[Comp.Node] = [
                Comp.Node(
                    uin="0",
                    name="MCGetter",
                    content=[
                        Comp.Plain(f"当前保存的服务器共 {len(servers)} 个，列表如下：")
                    ]
                )
            ]

            for server_id, server_info in servers.items():
                nodes.append(
                    Comp.Node(
                        uin="0",
                        name="MCGetter",
                        content=[
                            Comp.Plain(
                                f"ID: {server_id}\n"
                                f"名称: {server_info.get('name', '未知服务器')}\n"
                                f"地址: {server_info.get('host', '未知地址')}"
                            )
                        ]
                    )
                )

            yield event.chain_result([Comp.Nodes(nodes=nodes)])
            
        except Exception as e:
            yield event.plain_result("获取服务器列表时发生错误:"+str(e))

    @filter.command("mccleanup")
    async def mccleanup(self, event: AstrMessageEvent) -> MessageEventResult:
        """
        手动触发自动清理（删除长期未查询成功的服务器）
        """
        try:
            group_id = event.get_group_id()
            json_path = await self.get_json_path(group_id)
            cleanup_days = self._get_cleanup_days()
            if cleanup_days <= 0:
                yield event.plain_result("自动清理已关闭（插件配置 auto_cleanup_days <= 0）")
                return

            deleted_servers = await auto_cleanup_servers(json_path, days=cleanup_days)
            if deleted_servers:
                cleanup_message = (
                    f"自动清理完成，以下服务器因{cleanup_days}天未查询成功已被删除:\n"
                )
                for server in deleted_servers:
                    last_success_date = datetime.fromtimestamp(server['last_success_time']).strftime('%Y-%m-%d %H:%M:%S')
                    cleanup_message += f"• {server['name']} (ID: {server['id']}) - 地址: {server['host']} - 最后成功: {last_success_date}\n"
                yield event.plain_result(cleanup_message.strip())
            else:
                yield event.plain_result("没有需要清理的服务器")
                
        except Exception as e:
            yield event.plain_result("自动清理时发生错误:"+str(e))

    def _get_cleanup_days(self) -> int:
        """Read auto_cleanup_days from plugin config; default 10."""
        raw = self._get_plugin_config_value("auto_cleanup_days", 10)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 10

    def _format_last_success(self, last_success_time: Any) -> Optional[str]:
        """Format last successful query timestamp for offline cards."""
        if isinstance(last_success_time, (int, float)) and last_success_time > 0:
            return strftime('%Y-%m-%d %H:%M:%S', localtime(last_success_time))
        return None

    async def _offline_card_base64(
        self,
        server_id: Any,
        server_info: Dict[str, Any],
        colors: Optional[Dict[str, Any]] = None,
        template: Optional[str] = None,
    ) -> str:
        """渲染单张离线卡，供并发查询失败回退使用。"""
        colors = colors if isinstance(colors, dict) else {}
        sid = str(server_id)
        server_name_color = (colors.get("server_names") or {}).get(sid)
        tags = server_info.get("tags") if isinstance(server_info.get("tags"), list) else []
        return await get_img(
            players_list=[],
            latency=-1,
            server_name=server_info.get("name", "未知服务器"),
            plays_max=0,
            plays_online=0,
            server_version="—",
            icon_base64=None,
            server_id=sid,
            host=server_info.get("host", ""),
            online_state="offline",
            last_success_text=self._format_last_success(
                server_info.get("last_success_time")
            ),
            server_name_color=server_name_color,
            player_colors=colors.get("players") or {},
            template=template,
            tags=tags,
        )

    async def _update_status_safe(
        self, json_path: Optional[str], server_id: Optional[Any], success: bool
    ) -> None:
        """在锁内更新服务器查询状态，避免并发 /mc 写坏群配置。"""
        if not json_path or server_id is None:
            return
        async with self._status_update_lock:
            await update_server_status(json_path, server_id, success)

    async def get_img(
        self,
        server_name: str,
        host: str,
        server_id: Optional[str] = None,
        json_path: Optional[str] = None,
        last_success_time: Any = None,
        colors: Optional[Dict[str, Any]] = None,
        template: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        获取服务器信息图片（失败时返回离线卡）

        Args:
            server_name: 服务器名称
            host: 服务器地址
            server_id: 服务器ID（可选）
            json_path: JSON文件路径（用于更新状态）
            last_success_time: 上次成功查询时间戳（离线卡展示用）
            colors: 群维度颜色配置 {server_names, players}
            template: 群维度卡片主题
            tags: 服务器标签列表

        Returns:
            图片的base64编码字符串；查询失败时返回离线卡，渲染彻底失败才返回None
        """
        colors = colors if isinstance(colors, dict) else {}
        sid = str(server_id) if server_id is not None else None
        server_name_color = (colors.get("server_names") or {}).get(sid) if sid else None
        player_colors = colors.get("players") or {}
        tag_list = tags if isinstance(tags, list) else []

        async def _offline() -> Optional[str]:
            try:
                return await get_img(
                    players_list=[],
                    latency=-1,
                    server_name=server_name,
                    plays_max=0,
                    plays_online=0,
                    server_version="—",
                    icon_base64=None,
                    server_id=sid,
                    host=host,
                    online_state="offline",
                    last_success_text=self._format_last_success(last_success_time),
                    server_name_color=server_name_color,
                    player_colors=player_colors,
                    template=template,
                    tags=tag_list,
                )
            except Exception:
                return None

        try:
            try:
                info = await asyncio.wait_for(
                    get_server_status(host),
                    timeout=QUERY_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "查询服务器超时(%.1fs): %s (%s)", QUERY_TIMEOUT_SEC, server_name, host
                )
                info = None

            if not info:
                await self._update_status_safe(json_path, server_id, False)
                return await _offline()

            await self._update_status_safe(json_path, server_id, True)

            return await get_img(
                players_list=info['players_list'],
                latency=info['latency'],
                server_name=server_name,
                plays_max=info['plays_max'],
                plays_online=info['plays_online'],
                server_version=info['server_version'],
                icon_base64=info['icon_base64'],
                server_id=sid,
                host=host,
                online_state="online",
                server_name_color=server_name_color,
                player_colors=player_colors,
                motd=info.get("motd") or "",
                template=template,
                tags=tag_list,
            )

        except Exception:
            await self._update_status_safe(json_path, server_id, False)
            return await _offline()

    async def get_json_path(self, group_id: str) -> Path:
        """
        获取群组的JSON配置文件路径

        Args:
            group_id: 群组ID

        Returns:
            JSON文件的Path对象
        """
        data_path = StarTools.get_data_dir("astrbot_mcgetter")
        json_path = data_path / f'{group_id}.json'
        json_path.parent.mkdir(parents=True, exist_ok=True)
        return json_path

    def _get_plugin_config_value(self, key: str, default: Any) -> Any:
        try:
            if hasattr(self.plugin_config, "get"):
                value = self.plugin_config.get(key, default)
                return default if value is None else value
        except Exception:
            pass
        return default

    def _set_plugin_config_value(self, key: str, value: Any) -> None:
        try:
            if isinstance(self.plugin_config, dict) or hasattr(self.plugin_config, "__setitem__"):
                self.plugin_config[key] = value
        except Exception as e:
            logger.warning("设置插件配置失败 key=%s: %s", key, e)

    def _save_plugin_config(self) -> None:
        save_fn = getattr(self.plugin_config, "save_config", None)
        if callable(save_fn):
            save_fn()

    def _get_mcq_whitelist(self) -> List[str]:
        raw = self._get_plugin_config_value("mcq_whitelist_user_ids", [])
        if not isinstance(raw, list):
            return []
        ret: List[str] = []
        for item in raw:
            s = str(item).strip()
            if s:
                ret.append(s)
        return list(dict.fromkeys(ret))

    def _extract_target_user_id(self, event: AstrMessageEvent, user_id_text: str) -> str:
        for comp in event.get_messages():
            if isinstance(comp, Comp.At):
                qq = str(getattr(comp, "qq", "") or "").strip()
                if qq and qq != "all":
                    return qq

        text = str(user_id_text or "").strip()
        if re.fullmatch(r"\d+", text):
            return text
        return ""

    def _extract_sender_level(self, event: AstrMessageEvent) -> int:
        sender = getattr(event.message_obj, "sender", None)
        level_candidates = []
        if sender is not None:
            level_candidates.append(getattr(sender, "level", None))
            level_candidates.append(getattr(sender, "group_level", None))

        raw_message = getattr(event.message_obj, "raw_message", None)
        if isinstance(raw_message, dict):
            sender_obj = raw_message.get("sender")
            if isinstance(sender_obj, dict):
                level_candidates.append(sender_obj.get("level"))

        for raw_level in level_candidates:
            if raw_level is None:
                continue
            if isinstance(raw_level, (int, float)):
                return int(raw_level)
            s = str(raw_level)
            m = re.search(r"\d+", s)
            if m:
                try:
                    return int(m.group(0))
                except Exception:
                    continue
        return 0

    async def _can_manage_mcq_whitelist(self, event: AstrMessageEvent) -> bool:
        allow_astrbot_admin = bool(self._get_plugin_config_value("mcq_allow_astrbot_admin", True))
        roles = await resolve_roles(event)
        if allow_astrbot_admin and roles["astrbot_admin"]:
            return True
        if roles["group_owner"] or roles["group_admin"]:
            return True
        return False

    async def _can_use_mcq(self, event: AstrMessageEvent) -> bool:
        return await can_use_mcq(
            event,
            permission_enabled=bool(self._get_plugin_config_value("mcq_permission_enabled", True)),
            whitelist=self._get_mcq_whitelist(),
            allow_astrbot_admin=bool(self._get_plugin_config_value("mcq_allow_astrbot_admin", True)),
            allow_group_owner=bool(self._get_plugin_config_value("mcq_allow_group_owner", True)),
            allow_group_admin=bool(self._get_plugin_config_value("mcq_allow_group_admin", True)),
            min_group_level=int(self._get_plugin_config_value("mcq_min_group_level", 90) or 0),
        )

    async def _mcmod_scheduler_loop(self) -> None:
        """每分钟检查：19:00 晚报 + 整点冷场推送。"""
        while True:
            try:
                await asyncio.sleep(30)
                await self._mcmod_scheduler_tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("mcmod scheduler tick error: %s", e)

    async def _mcmod_scheduler_tick(self) -> None:
        if not bool(self._get_plugin_config_value("mcmod_enabled", True)):
            return
        now = datetime.now()
        evening_hour = int(self._get_plugin_config_value("mcmod_evening_push_hour", 19) or 19)
        today = now.date().isoformat()
        hour_slot = now.strftime("%Y-%m-%d-%H")

        # 晚报：当日 hour==evening 且未发
        if now.hour == evening_hour and now.minute < 5 and self._mcmod_last_evening_date != today:
            self._mcmod_last_evening_date = today
            await self._mcmod_broadcast_push(kind="evening")

        # 冷场：每小时整点后 5 分钟内最多触发一次检查
        if (
            bool(self._get_plugin_config_value("mcmod_hourly_push", True))
            and now.minute < 5
            and self._mcmod_last_hourly_slot != hour_slot
        ):
            self._mcmod_last_hourly_slot = hour_slot
            await self._mcmod_cold_room_push()

    async def _mcmod_broadcast_push(self, kind: str = "evening") -> None:
        store = self.mcmod_service.push_store
        n = int(self._get_plugin_config_value("mcmod_push_items", 3) or 3)
        daily_cap = int(self._get_plugin_config_value("mcmod_push_per_day_cap", 4) or 4)
        for key, st in list(store.all_enabled().items()):
            try:
                st.ensure_today()
                if not can_push_more(st, daily_cap=daily_cap):
                    continue
                text = await self.mcmod_service.build_push_payload(self.context, st.umo, n=n)
                if not text:
                    continue
                await self.context.send_message(st.umo, MessageChain([Comp.Plain(text)]))
                record_push(st, kind, time.time())
                store.update(key, st)
            except Exception as e:
                logger.warning("mcmod evening push failed %s: %s", key, e)

    async def _mcmod_cold_room_push(self) -> None:
        store = self.mcmod_service.push_store
        n = int(self._get_plugin_config_value("mcmod_push_items", 3) or 3)
        daily_cap = int(self._get_plugin_config_value("mcmod_push_per_day_cap", 4) or 4)
        idle_skip = float(self._get_plugin_config_value("mcmod_idle_skip_minutes", 10) or 10)
        now_ts = time.time()
        for key, st in list(store.all_enabled().items()):
            try:
                st.ensure_today()
                if not can_push_more(st, daily_cap=daily_cap):
                    continue
                last = st.last_human_msg_at or st.enabled_at or now_ts
                idle_min = max(0.0, (now_ts - last) / 60.0)
                if not should_trigger_cold_room(
                    idle_min,
                    st.today_push_count,
                    idle_skip_minutes=idle_skip,
                    daily_cap=daily_cap,
                ):
                    continue
                text = await self.mcmod_service.build_push_payload(self.context, st.umo, n=n)
                if not text:
                    continue
                await self.context.send_message(st.umo, MessageChain([Comp.Plain(text)]))
                record_push(st, "cold", now_ts)
                store.update(key, st)
            except Exception as e:
                logger.warning("mcmod cold push failed %s: %s", key, e)
