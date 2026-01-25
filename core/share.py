from __future__ import annotations

import shutil
import uuid

import aiohttp

import astrbot.core.message.components as Comp
from astrbot.api import logger
from astrbot.core.platform import AstrMessageEvent

from ..core.lorebook import Lorebook
from .config import PluginConfig


class LorebookShare:
    """
    世界书文件分享层（单 YAML 文件版）

    设计约定：
    - 流通格式：单个 .yaml / .yml
    - 对齐酒馆世界书（Lorebook / World Info）
    """

    def __init__(self, lorebook: Lorebook, config: PluginConfig):
        self.lorebook = lorebook
        self.cfg = config

    async def download_file(self, url: str) -> bytes | None:
        """下载文件"""
        url = url.replace("https://", "http://")
        try:
            async with aiohttp.ClientSession() as client:
                response = await client.get(url)
                img_bytes = await response.read()
                return img_bytes
        except Exception as e:
            logger.error(f"图片下载失败: {e}")

    # ================= 导出 =================

    async def upload_lorebook(
        self,
        event: AstrMessageEvent,
        name: str | None = None,
    ):
        """
        导出并上传世界书（单 YAML 文件）
        """
        if event.get_platform_name() != "aiocqhttp":
            yield event.plain_result("本插件未适配此平台的文件上传功能")
            return

        name = name or f"{event.get_sender_name()}_lorebook"
        filename = f"{name}.{self.cfg.export_format}"

        workdir = self.cfg.export_dir / uuid.uuid4().hex
        workdir.mkdir(parents=True, exist_ok=True)

        lorefile = workdir / filename

        try:
            # 导出为单文件
            self.lorebook.export_lorefile(str(lorefile))

            client = event.bot  # type: ignore
            group_id = event.get_group_id()

            if group_id:
                await client.upload_group_file(
                    group_id=int(group_id),
                    file=str(lorefile),
                    name=filename,
                )
            else:
                await client.upload_private_file(
                    user_id=int(event.get_sender_id()),
                    file=str(lorefile),
                    name=filename,
                )

        except Exception as e:
            logger.error(f"[lorebook-share] 导出失败: {e}")
            yield event.plain_result("世界书导出失败")

        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            event.stop_event()

    # ================= 导入 =================

    async def download_lorebook(
        self,
        event: AstrMessageEvent,
        *,
        override: bool = False,
    ):
        """
        下载并导入世界书（单 YAML 文件）
        """
        if event.get_platform_name() != "aiocqhttp":
            yield event.plain_result("本插件未适配此平台的文件接收功能")
            return

        chain = event.message_obj.message
        reply_chain = (
            chain[0].chain if chain and isinstance(chain[0], Comp.Reply) else None
        )
        file_comp = (
            reply_chain[0]
            if reply_chain and isinstance(reply_chain[0], Comp.File)
            else None
        )

        if not file_comp or not file_comp.url:
            yield event.plain_result("请引用一个世界书 .yaml 文件")
            return

        if not str(file_comp.name).lower().endswith((".json", ".yaml", ".yml")):
            yield event.plain_result("仅支持 .json / .yaml / .yml 世界书文件")
            return

        data = await self.download_file(file_comp.url)
        if not data:
            yield event.plain_result("文件下载失败")
            return

        workdir = self.cfg.import_dir / uuid.uuid4().hex
        workdir.mkdir(parents=True, exist_ok=True)
        name = file_comp.name or file_comp.url.split("/")[-1]
        lorefile = workdir / name

        try:
            lorefile.write_bytes(data)

            # 直接按世界书文件导入
            self.lorebook.load_entry_from_lorefile(
                str(lorefile),
                override=override,
            )

            yield event.plain_result("该世界书导入完成")
            event.stop_event()

        except Exception as e:
            logger.error(f"[lorebook-share] 导入失败: {e}")
            yield event.plain_result(f"导入失败: {e}")

        finally:
            shutil.rmtree(workdir, ignore_errors=True)
