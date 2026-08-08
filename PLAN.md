# 实施方案：并发 / MOTD / 多主题 / Polish

> 每完成一项功能独立 `git commit`。本文件仅作过程清单，可随实现更新勾选状态。

## 范围

| ID | 项 | 提交粒度 | 状态 |
|----|----|----------|------|
| F1 | `/mc` 并发查询 + 单服超时 | 1 commit | done |
| F3 | 卡片展示 MOTD | 1 commit | done |
| F6 | 内置多主题 + 按群存储 + `/mctem list` | 1 commit（含 p-mctem） | done |
| P1 | README 与代码对齐 | 1 commit | done |
| P2 | 清理天数可配置 | 1 commit | done |
| P3 | 图标本地缓存 | 1 commit | done |
| P4 | 版本号统一 | 1 commit | done |

---

## F1 · 并发查询

### 目标
多服 `/mc` 时并行查状态，总耗时接近最慢那一台，而不是求和。

### 方案
1. `main.mcgetter`：对 `servers` 列表用 `asyncio.gather` 并行调用现有 `get_img`（内部已查服+渲染）。
2. **顺序**：用 `servers.items()` 顺序建 task，`gather` 后按同一顺序组 `message_chain`。
3. **超时**：在 `get_server_status` 调用处（`MyPlugin.get_img`）包 `asyncio.wait_for(..., timeout=QUERY_TIMEOUT)`，默认 **8s**；超时按离线卡处理。
4. 单服异常：catch 后补离线卡，不拖垮整轮。
5. 不改 CLI 语义；无需新命令。

### 涉及文件
- `main.py`（`mcgetter` 循环 → gather）
- 可选常量：`QUERY_TIMEOUT_SEC = 8`

### 验收
- 多服时日志/体感明显快于串行
- 某服超时/失败仍出离线卡，其他服正常

---

## F3 · MOTD

### 目标
在线卡展示服务器 MOTD（去格式码、截断）。

### 方案
1. `get_server_info.get_server_status`：从 `status.description` 取纯文本
   - 兼容 str / dict / 带 `to_plain` 的对象
   - 去除 `§.` / `\x1b` 类颜色码，压空白
2. 返回字段增加 `motd: str`
3. 渲染链路透传：`MyPlugin.get_img` → `template_selector.get_img` → `generate_server_info_image`（及后续主题）
4. 霓虹默认卡：meta 行下方或 stat 区上方一行 MOTD（小字、截断 1 行）
5. 离线卡不显示 MOTD（或显示 `—`）

### 涉及文件
- `script/get_server_info.py`
- `main.py`
- `script/template_selector.py`
- `script/get_img.py`

### 验收
- 有 MOTD 的服卡片可见描述；过长被截断；无 MOTD 不留丑空白

---

## F6 · 内置多主题 + 按群 + list

### 目标
内置多套主题可切换；模板配置按**群**隔离；`/mctem` 可列出。

### 方案

#### 内置主题名（稳定 ID）
| ID | 说明 | 来源 |
|----|------|------|
| `neon` / `default` | 霓虹玻璃（当前默认） | Design F |
| `classic` | 经典精修 | Design A |
| `dashboard` | 现代仪表盘 | Design B |
| `inventory` | MC 背包风 | Design C |
| `soft` | 浅色柔和 | Design D |
| `compact` | 紧凑信息流 | Design E |

用户数据目录下 `template/*.py` 自定义模板名仍可用（优先级：同名时**自定义覆盖内置**，或文档约定自定义勿与内置撞名——采用：**先查自定义文件，没有再查内置**）。

#### 按群存储
- 在群 JSON 增加字段：`"template": "neon"`
- 读写：`json_operate.get_template` / `set_template`
- 废弃全局 `template.txt` 作为权威来源；若群 JSON 无字段，回退读全局 `template.txt` 一次并 migrate 写入群 JSON（兼容旧安装）

#### 命令
```
/mctem              → 当前主题 + 可用列表（内置 + 自定义）
/mctem list         → 同上
/mctem <name>       → 切换当前群主题
```

#### 渲染调度
- `get_img(..., template: Optional[str] = None)`：由 `main` 传入本群 template
- 内置主题统一签名（含 motd / offline / colors）
- 自定义 `draw_image` 仍兼容旧签名（无 motd 时不传或 **kwargs）

### 涉及文件
- `script/themes/`（新建：registry + 各主题或从 prototype 移植精简版）
- `script/template_selector.py`
- `script/json_operate.py`
- `main.py`（`mctem`、`get_img` 传 template）
- `HELP_INFO`

### 验收
- 群 A 设 classic、群 B 设 neon 互不影响
- `/mctem` 无参可读列表
- 错误名有友好提示

---

## P1 · README 对齐

- 去掉「失败汇总转发」描述，改为离线失败卡
- 命令表补 `/mccolor`、`/mctem` 行为
- TODO 勾选已完成项（自定义主题增强等）
- 修正过时 GitHub Issues 链接若可

### 提交
`docs: align README with offline cards and mccolor`

---

## P2 · 清理天数可配置

- `_conf_schema.json` 增加 `auto_cleanup_days`（int，默认 10，最小 1）
- `auto_cleanup_servers(json_path, days=None)` 接受天数
- `main` 从 `plugin_config` 读取并传入
- 帮助文案中的「10 天」改为动态或「可配置」

### 提交
`feat: make auto-cleanup days configurable`

---

## P3 · 图标本地缓存

- 模块级 LRU / dict：`key = sha1(icon_base64)[:16]` → `PIL.Image` 拷贝
- 上限例如 64 条；默认图标不占缓存或单独路径
- 仅内存缓存，重启清空即可

### 提交
`perf: cache decoded server icons in memory`

---

## P4 · 版本统一

- `metadata.yaml`、`@register(..., "x.y.z")`、必要时 README 版本说明一致
- 本批功能完成后版本 **1.7.0**（并发 + MOTD + 多主题 + polish）

### 提交
`chore: bump version to 1.7.0`

---

## 实现顺序

1. F1 并发 → commit  
2. F3 MOTD → commit  
3. F6 主题（含 mctem list / 按群）→ commit  
4. P1 README → commit  
5. P2 清理配置 → commit  
6. P3 图标缓存 → commit  
7. P4 版本号 → commit  

---

## 风险与边界

- 自定义旧模板无 offline/motd：不强制改 API，缺参时走兼容调用
- 并发后瞬时连接变多：超时 8s + 单服失败隔离足够；暂不加全局 semaphore（可后续）
- 主题移植工作量大：内置主题保证 neon 完整；其余从 prototype 移植核心视觉，支持 online/offline + MOTD 一行
