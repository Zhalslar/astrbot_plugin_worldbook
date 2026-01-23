# core/prompt.py
from __future__ import annotations

import re
import time

from astrbot.api import logger

from .config import ConfigNode, PluginConfig


class PromptItem(ConfigNode):
    __template_key: str
    name: str
    enable: bool
    priority: int
    regexs: list[str]
    content: str
    duration: int
    times: int

    def __init__(self, data: dict):
        super().__init__(data)
        self._activated_at: float | None = None
        self._inject_count: int = 0
        self._compiled_regexs: list[re.Pattern] = []

        self.regexs = [r for r in self.regexs if r.strip()] or [self.name]

        for pattern in self.regexs:
            try:
                self._compiled_regexs.append(re.compile(pattern))
            except re.error as e:
                logger.warning(f"[prompt:{self.name}] 正则编译失败: {pattern} ({e})")

    @property
    def activated(self) -> bool:
        return self._activated_at is not None

    @property
    def expired(self) -> bool:
        # 未激活：不算过期
        if self._activated_at is None:
            return False

        # duration == 0：永久生效
        if self.duration == 0:
            return False

        return time.time() >= self._activated_at + self.duration

    @property
    def remaining(self) -> int:
        if self.duration == 0:
            return 0

        if self._activated_at is None:
            return self.duration

        return max(
            0,
            int(self.duration - (time.time() - self._activated_at)),
        )

    @property
    def available(self) -> bool:
        """
        当前 prompt 是否仍可注入
        """
        # 已过期（时间）
        if self.expired:
            return False

        # 次数限制：times == 0 表示不限制
        if self.times > 0 and self._inject_count >= self.times:
            return False

        return True

    def display(self) -> str:
        """以可读文本形式展示该提示词"""
        status = "启用" if self.enable else "禁用"
        regex_text = "、".join(self.regexs)
        times_text = "不限次数" if self.times == 0 else f"{self.times} 次"
        duration_text = "永久" if self.duration == 0 else f"{self.duration} 秒"
        lines = [
            f"# 【{self.name}】",
            f"{status}; 优先级{self.priority}; 触发正则: {regex_text}; 注入时长: {duration_text}; 注入次数: {times_text}",
            f"{self.content}",
        ]
        return "\n".join(lines)


class PromptManager:
    """Prompt 管理器"""

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.prompts: list[PromptItem] = []

        self._register_prompt()
        self._refresh_enabled_cache()

        # 初始化后立即持久化一次（修正 enable / regex 等）
        self.cfg.save_config()

    def _register_prompt(self) -> None:
        """注册配置中的所有 prompt"""
        for item in self.cfg.prompt_templates:
            prompt = PromptItem(item)
            self.prompts.append(prompt)
            logger.debug(f"已注册 Prompt: {prompt.name}, 参数: {prompt.raw_data()}")

    def _refresh_enabled_cache(self) -> None:
        """刷新启用 prompt 缓存（内部使用）"""
        self._enabled_prompts_cache: list[PromptItem] = [
            p for p in self.prompts if p.enable
        ]

    def _next_priority(self, avoid_admin: bool = True) -> int:
        """获取下一个可用的 priority（可避开 admin priority）"""

        if not self.prompts:
            priority = 0
        else:
            priority = max(p.priority for p in self.prompts) + 1

        if not avoid_admin:
            return priority

        # 避开 admin priority 区间
        while self.cfg.is_admin_priority(priority):
            priority += 1

        return priority

    # ================= 查询接口 =================

    def get_prompt(self, name: str) -> PromptItem | None:
        """按 name 获取单个 prompt"""
        for prompt in self.prompts:
            if prompt.name == name:
                return prompt
        return None

    def list_prompts(self) -> list[PromptItem]:
        """获取全部 prompt（包含启用和禁用）"""
        return list(self.prompts)

    def list_enabled_prompts(self) -> list[PromptItem]:
        """获取当前已启用的 prompt"""
        return list(self._enabled_prompts_cache)

    def list_disabled_prompts(self) -> list[PromptItem]:
        """获取当前已禁用的 prompt"""
        return [p for p in self.prompts if not p.enable]

    def list_prompts_sorted(self) -> list[PromptItem]:
        """获取按 priority 排序的全部 prompt"""
        return sorted(self.prompts, key=lambda p: p.priority)

    # ================= 启停控制接口 =================

    def enable_prompts(self, names: list[str]) -> tuple[list[str], list[str]]:
        """按 name 批量开启 prompt"""
        success: list[str] = []
        failed: list[str] = []

        for name in names:
            prompt = self.get_prompt(name)
            if not prompt:
                failed.append(name)
                continue

            if not prompt.enable:
                prompt.enable = True
            success.append(name)

        self._refresh_enabled_cache()
        self.cfg.save_config()
        return success, failed

    def disable_prompts(self, names: list[str]) -> tuple[list[str], list[str]]:
        """按 name 批量关闭 prompt"""
        success: list[str] = []
        failed: list[str] = []

        for name in names:
            prompt = self.get_prompt(name)
            if not prompt:
                failed.append(name)
                continue

            if prompt.enable:
                prompt.enable = False
            success.append(name)

        self._refresh_enabled_cache()
        self.cfg.save_config()
        return success, failed

    # ================= CRUD 接口 =================

    def add_prompt(self, name: str, content: str) -> PromptItem:
        """新增一个 prompt（data 为配置 dict，自动处理 priority）"""
        data = {
            "__template_key": "default",
            "name": name,
            "enable": True,
            "priority": self._next_priority(),
            "regexs": [],
            "content": content,
            "duration": self.cfg.default_duration,
            "times": self.cfg.default_times,
        }

        prompt = PromptItem(data)
        self.prompts.append(prompt)
        self.cfg.prompt_templates.append(data)

        self._refresh_enabled_cache()
        self.cfg.save_config()

        logger.info(f"新增 Prompt: {prompt.name} (priority={prompt.priority})")
        return prompt

    def remove_prompts(self, names: list[str]) -> tuple[list[str], list[str]]:
        """按 name 批量删除 prompt"""
        success: list[str] = []
        failed: list[str] = []

        remaining_prompts: list[PromptItem] = []
        remaining_configs: list[dict] = []

        for prompt, cfg in zip(self.prompts, self.cfg.prompt_templates):
            if prompt.name in names:
                success.append(prompt.name)
            else:
                remaining_prompts.append(prompt)
                remaining_configs.append(cfg)

        for name in names:
            if name not in success:
                failed.append(name)

        self.prompts = remaining_prompts
        self.cfg.prompt_templates = remaining_configs

        self._refresh_enabled_cache()
        self.cfg.save_config()
        return success, failed

    # ================= 运行时匹配接口 =================

    @property
    def enabled_prompts(self) -> list[PromptItem]:
        """获取启用 prompt（原始顺序）"""
        return self._enabled_prompts_cache

    def enabled_sorted_prompts(self) -> list[PromptItem]:
        """获取按 priority 排序后的启用 prompt"""
        return sorted(
            self._enabled_prompts_cache,
            key=lambda p: p.priority,
        )

    def match_prompts(self, text: str) -> list[PromptItem]:
        """
        根据文本匹配 prompt（不处理 priority 冲突策略）
        """
        matched: list[PromptItem] = []

        for prompt in self.enabled_sorted_prompts():
            for regex in prompt._compiled_regexs:
                if regex.search(text):
                    matched.append(prompt)
                    break

        return matched
