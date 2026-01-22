
<div align="center">

![:name](https://count.getloli.com/@astrbot_plugin_prompt_inject?name=astrbot_plugin_prompt_inject&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_prompt_inject

_✨ 提示词注入器 ✨_  

[![License](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0.html)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-4.0%2B-orange.svg)](https://github.com/Soulter/AstrBot)
[![GitHub](https://img.shields.io/badge/作者-Zhalslar-blue)](https://github.com/Zhalslar)

</div>

## 🤝 介绍

这是一个 **基于关键词 / 正则触发的提示词注入插件**。

当用户发送的消息 **命中你配置的正则规则** 时，插件会在一段时间内，把对应的提示词自动追加到 LLM 的 `system_prompt` 中，从而影响 AI 的回答风格、行为或规则。

**常见用途：**

- 临时切换 AI 的说话风格（严肃 / 可爱 / 专业）
- 在某个话题期间强制加入规则或背景设定
- 管理员触发特殊模式（教学 / 审核 / RP）
- 群聊中按关键词自动启用“上下文规则”

---

## 🧠 工作流程（简单版）

1. 用户发送一条消息  
2. 插件用正则匹配所有已启用的提示词模板  
3. 命中后：
   - 按优先级排序
   - 同优先级可自动去重
   - 检查管理员权限
4. 提示词被激活并缓存到 **当前会话**
5. 在有效期内，**每一次 LLM 请求都会自动注入提示词**
6. 到期 / 次数用完 / 手动清除后失效

---

## 📦 安装

在astrbot的插件市场搜索astrbot_plugin_prompt_inject，点击安装即可

---

## ⌨️ 命令表

| 命令 | 说明 |
|----|----|
| `提示词状态` | 查看当前会话中**正在生效**的提示词列表、剩余时间与注入次数 |
| `清除提示词` | 立即清除当前会话中**所有已激活**的提示词，停止后续注入 |

---

## 🧩 提示词模板（prompt_templates）

每一套提示词模板表示 **一条可被触发并注入的提示词规则**。  
当用户消息命中配置的正则后，该提示词会在一段时间内自动注入到 LLM 的 `system_prompt` 中。

### 模板字段说明

| 字段 | 类型 | 说明 |
|----|----|----|
| `name` | string | 提示词名称，**必须唯一** |
| `enable` | bool | 是否启用该提示词 |
| `content` | text | 触发后注入到 `system_prompt` 的提示词内容 |
| `priority` | int | 触发优先级，**数字越小越先处理** |
| `regexs` | list | 触发用的正则表达式列表， 正则不会写就让AI写，或者无脑直接写关键词即可模糊匹配 |
| `duration` | int | 注入时长（秒），`0` 表示一直生效 |
| `only_admin` | bool | 是否仅管理员可触发 |

---

## 👥 贡献指南

- 🌟 Star 这个项目！（点右上角的星星，感谢支持！）
- 🐛 提交 Issue 报告问题
- 💡 提出新功能建议
- 🔧 提交 Pull Request 改进代码

## 📌 注意事项

- 正则写错不会导致插件崩溃，但会被忽略并记录警告日志

- 优先级数字尽量不要重复（除非你明确需要覆盖）

- 提示词内容会 追加在 system_prompt 末尾

- 提示词是 会话级 的，不同群 / 私聊互不影响

- 想第一时间得到反馈的可以来作者的插件反馈群（QQ群）：460973561（不点star不给进）
