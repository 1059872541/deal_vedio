---
name: quarkpan-mcp-operate
description: 指导AI如何使用quark-nd-mcp MCP Server操作夸克网盘，包括文件浏览、上传下载、分享文件操作等
---

## 知识获取

你应该阅读 `@references/quark-nd-mcp-README.md` 中的内容，了解 quark-nd-mcp MCP Server 提供的全部工具及其参数。

## 功能概述

通过 MCP 工具可直接操作夸克网盘，无需额外 Python 库或脚本：

### 文件管理
- **list_files(path)** — 列出目录内容（`/` 表示根目录）
- **create_folder(path)** — 创建文件夹
- **rename(old_path, new_name)** — 重命名文件/文件夹
- **delete(paths)** — 删除文件/文件夹（支持批量）
- **move(source_paths, dest_path)** — 移动文件/文件夹
- **copy(source_paths, dest_path)** — 复制文件/文件夹
- **get_info(path)** — 获取文件/文件夹详细信息

### 文件传输
- **upload_file(dest_path, local_path)** — 上传本地文件到夸克网盘
- **download_file(source_path, local_path)** — 异步下载文件到本地
- **get_download_status(task_id)** — 查询下载进度
- **cancel_download(task_id)** — 取消下载任务
- **list_downloads()** — 列出所有下载任务

### 高级功能
- **regex_rename(path, pattern, replacement)** — 用正则批量重命名文件
- **search(path, keyword)** — 递归搜索文件/文件夹

### 分享文件操作
- **get_share_file_list(share_url)** — 获取分享链接根目录文件列表
- **get_share_detail(share_url, folder_id)** — 获取分享链接子目录文件列表
- **save_from_share(share_url, dest_path, [folder_id], [file_ids])** — 将分享文件保存到自己的网盘

## 操作核心原则

1. **用户需求优先**：始终以用户的需求为中心，确保提供的指导和建议能够满足用户的具体要求。
2. **先确认再执行**：在执行任何修改性操作（删除、移动、重命名）之前，先向用户展示将要操作的文件列表，确认无误后再执行。
3. **路径一致性**：夸克网盘使用 `/` 开头表示路径层次，根目录为 `/`。上传下载时注意本地路径与网盘路径的区别。
4. **异步下载流程**：`download_file` 是异步操作，返回 `task_id`，之后需要用 `get_download_status` 轮询进度。三步流程：调用下载 → 轮询进度 → 下载完成通知用户。
5. **分享文件操作**：分享链接可能需要密码（`?pwd=xxx`），保存前先使用 `get_share_file_list` 预览内容，确认后再保存。
6. **安全第一**：操作前确认文件路径和名称准确无误，避免误删或覆盖。

## 与现有 Python 版 quarkpan 的对比

| 维度 | quark-nd-mcp (本 skill) | quarkpan (Python 库) |
|------|------------------------|---------------------|
| 方式 | MCP 工具直接调用 | Python 脚本/代码 |
| 传输 | 支持上传和异步下载 | 仅文件列表浏览 |
| 分享 | 支持查看和保存分享 | 不支持 |
| 重命名 | 支持正则批量重命名 | 不支持 |

## 使用场景

当用户提到以下场景时使用此 skill：
- 操作夸克网盘（浏览、上传、下载、删除、移动）
- 查看网盘中的视频/文件列表
- 从夸克网盘下载文件到本地
- 上传本地文件到夸克网盘
- 处理夸克分享链接（查看内容、保存到自己的网盘）
- 批量重命名网盘中的文件
- 递归搜索网盘中的文件
