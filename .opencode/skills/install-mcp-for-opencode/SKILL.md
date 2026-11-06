---
name: install-mcp-for-opencode
description: 告诉AI如何协助用于为 OpenCode 安装和配置 MCP 服务器的自动化流程。
---

## 使用流程
### 第一步：获取 MCP 信息

**最佳实践：优先自动获取文档信息**

用户只需提供 **MCP 名称** 或 **文档链接**，AI 自动访问文档提取配置信息：

1. **MCP 服务器名称**（如：baidu-netdisk, github, sentry 等）
2. **MCP 文档链接**（可选但推荐，如：https://pan.baidu.com/union/doc/fm9shpba6）
3. **运行方式**（如果文档不明确时询问）：
   - `local` - 本地运行（stdio 模式）
   - `remote` - 远程服务器（SSE 模式）
4. **Access Token** 或 **API Key**（可选，根据 MCP 要求）

#### 自动文档分析

如果用户提供了文档链接，AI 应该：
1. **访问 MCP 文档**，提取以下信息：
   - 运行方式（local/remote）
   - 安装命令和参数
   - 所需环境变量
   - 认证方式
2. **访问 OpenCode MCP 配置文档**（https://opencode.ai/docs/zh-cn/mcp-servers/）
3. **自动组装**正确的配置格式

**示例：百度网盘 MCP**
```
用户：我想安装百度网盘 MCP，文档在这里 https://pan.baidu.com/union/doc/fm9shpba6

AI：[自动访问文档]
- 发现是 local 类型
- 需要 stdio 模式运行
- 需要 BAIDU_NETDISK_ACCESS_TOKEN 环境变量
- 使用 uv 运行 Python 脚本

AI：已分析文档！确认以下信息：
- 名称：baidu-netdisk
- 方式：local（stdio 模式）
- 命令：uv run netdisk.py
- 需要 Access Token

请提供 Access Token，我将自动完成安装。
```

### 第二步：分析 MCP 类型并配置

根据用户提供的文档，自动提取以下信息：

#### 对于 Local MCP（本地）：
```json
{
  "mcp": {
    "<mcp-name>": {
      "type": "local",
      "command": ["<command>", "<arg1>", "<arg2>", ...],
      "enabled": true,
      "environment": {
        "<ENV_VAR>": "<value>"
      }
    }
  }
}
```

#### 对于 Remote MCP（远程）：
```json
{
  "mcp": {
    "<mcp-name>": {
      "type": "remote",
      "url": "<mcp-server-url>",
      "enabled": true,
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

### 第三步：安装步骤（Local MCP）

如果是本地 MCP，需要：

1. **创建目录**
   - Windows: `D:\softwares\mcp\<mcp-name>\`
   - macOS/Linux: `~/mcp/<mcp-name>/`

2. **下载/准备 MCP 文件**
   - 根据文档下载 SDK 或源码
   - 解压到目标目录
   - 安装依赖（如 `uv sync` 或 `npm install`）

3. **配置 OpenCode**
   - 配置文件路径：`~/.config/opencode/opencode.jsonc`
   - 添加 MCP 配置（使用正确的 `command` 数组格式）
   - 设置 `environment` 环境变量

### 第四步：验证安装

1. 重启 VS Code
2. 检查 OpenCode MCP 面板 (`/mcps`)
3. 确认 MCP 显示为 "connected" 和 "Enabled"
4. 运行测试命令验证功能

## 配置示例

### 示例 1：百度网盘 MCP

**用户提供：**
- 名称：baidu-netdisk
- 文档：https://pan.baidu.com/union/doc/fm9shpba6
- 方式：local (stdio)
- Token：xxx.yyy.zzz

**自动执行：**
1. 创建目录 `D:\softwares\mcp\baidu-netdisk-mcp\`
2. 下载并解压 SDK
3. 安装依赖：`uv sync`
4. 配置 `opencode.jsonc`：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "baidu-netdisk": {
      "type": "local",
      "command": [
        "C:\\Users\\<username>\\.local\\bin\\uv.exe",
        "--directory",
        "D:\\softwares\\mcp\\baidu-netdisk-mcp",
        "run",
        "netdisk.py"
      ],
      "enabled": true,
      "environment": {
        "BAIDU_NETDISK_ACCESS_TOKEN": "xxx.yyy.zzz"
      }
    }
  }
}
```

### 示例 2：Sentry MCP（Remote）

**用户提供：**
- 名称：sentry
- 文档：https://docs.sentry.io/mcp
- 方式：remote

**自动执行：**
```json
{
  "mcp": {
    "sentry": {
      "type": "remote",
      "url": "https://mcp.sentry.dev/mcp",
      "enabled": true
    }
  }
}
```

然后运行：`opencode mcp auth sentry`

### 示例 3：无需认证的 MCP（如文件系统工具）

**用户提供：**
- 名称：filesystem
- 文档：本地文件操作工具
- 方式：local
- Token：无需

**自动执行：**
```json
{
  "mcp": {
    "filesystem": {
      "type": "local",
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"],
      "enabled": true
    }
  }
}
```

## 智能信息提取

当用户提供文档链接时，AI 自动提取以下关键信息：

### 从 MCP 文档提取
| 信息项 | 示例 | 用途 |
|--------|------|------|
| **运行方式** | local / remote | 决定配置结构 |
| **安装命令** | `uv run netdisk.py` | 构建 command 数组 |
| **依赖工具** | uv / npm / bun / python | 检查环境要求 |
| **环境变量** | `BAIDU_NETDISK_ACCESS_TOKEN` | 配置 environment |
| **下载链接** | SDK 下载地址 | 获取必要文件 |
| **认证方式** | Token / OAuth / None | 决定是否需要认证 |

### 从 OpenCode 文档提取
| 信息项 | 示例 | 用途 |
|--------|------|------|
| **配置格式** | `mcp: { "name": {...} }` | 确保格式正确 |
| **命令格式** | 必须是数组 | 避免配置错误 |
| **环境变量名** | `environment` 而非 `env` | 使用正确字段名 |
| **认证命令** | `opencode mcp auth <name>` | OAuth 流程 |

### 信息整合流程

```
用户输入：名称 + 文档链接
    ↓
访问 MCP 文档 → 提取：运行方式、命令、环境变量
    ↓
访问 OpenCode 文档 → 确认：配置格式、字段名
    ↓
整合信息 → 生成正确的 opencode.jsonc 配置
    ↓
执行安装 → 下载、配置、验证
```

## 认证方式说明

### 不需要 Access Token 的情况
- **公开 MCP**：如文档查询、代码搜索等公共服务
- **OAuth 认证**：如 Sentry，使用 `opencode mcp auth <name>` 进行浏览器授权
- **本地工具**：仅操作本地文件系统，不需要远程认证

### 需要 Access Token 的情况
- **API 认证**：如百度网盘、GitHub 等需要 Personal Access Token
- **环境变量**：如 `BAIDU_NETDISK_ACCESS_TOKEN`、`GITHUB_TOKEN`
- **Header 认证**：远程 MCP 在 `headers` 中传递 Token

## 注意事项

1. **命令格式**：OpenCode 要求 `command` 必须是数组格式
2. **环境变量**：使用 `environment` 而不是 `env`
3. **路径格式**：Windows 路径需要双反斜杠 `\\`
4. **依赖安装**：本地 MCP 需要提前安装好依赖（uv/npm/bun 等）
5. **Token 安全**：Access Token 不要硬编码，建议从环境变量读取

## 故障排除

### 错误："Configuration is invalid"
- 检查 JSON 格式是否正确
- 确认 `type` 字段是 "local" 或 "remote"
- 确认 `command` 是数组格式

### 错误："MCP not found"
- 重启 VS Code
- 检查 `/mcps` 命令是否能看到 MCP
- 确认配置文件路径正确

### 错误："Command not found"
- 检查命令路径是否正确
- 确认依赖已安装（如 uv、python、node 等）
- 使用绝对路径

## 交互流程

### 场景 1：用户提供文档链接（推荐 ✅）

```
用户：我想安装百度网盘 MCP，文档在这里 https://pan.baidu.com/union/doc/fm9shpba6

AI：[自动访问文档分析]
- 从文档提取：local 类型、stdio 模式、uv 运行
- 需要环境变量：BAIDU_NETDISK_ACCESS_TOKEN

AI：已自动分析文档！确认信息如下：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 MCP 名称：baidu-netdisk
🔧 运行方式：local（stdio 模式）
💻 运行命令：uv run netdisk.py
🔐 认证方式：Access Token
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请提供 Access Token，我将自动完成安装。

用户：[提供 Token]

AI：[自动执行安装]
✅ 创建目录
✅ 下载 SDK
✅ 安装依赖
✅ 配置 opencode.jsonc
✅ 验证安装

AI：🎉 安装完成！请重启 VS Code 后输入 /mcps 查看。
```

### 场景 2：用户未提供文档链接

```
用户：我想安装一个 GitHub MCP

AI：好的！你有 GitHub MCP 的文档链接吗？

选项：
A. 提供文档链接 → 自动分析安装
B. 没有文档 → 手动询问配置信息

用户选择 A：文档链接 https://github.com/mcp/docs

AI：[自动访问文档并安装...]
```

## 最佳实践

### ✅ 推荐做法

1. **始终提供文档链接**
   - 让 AI 自动提取配置信息
   - 减少手动输入错误
   - 大大提高成功率

2. **文档链接格式**
   - 官方文档首页
   - MCP Server 配置说明页
   - README.md 文件链接

3. **多文档联合分析**
   - MCP 文档：了解服务器配置
   - OpenCode 文档：了解平台格式要求
   - 两者结合 = 正确配置

### ❌ 避免做法

1. **不提供文档**
   - 需要手动询问所有信息
   - 容易遗漏关键配置
   - 安装失败率高

2. **提供错误信息**
   - 命令格式错误
   - 环境变量名错误
   - 路径格式错误

### 💡 成功案例

**百度网盘 MCP 安装成功要素：**
1. ✅ 用户提供了文档链接
2. ✅ AI 访问文档提取了 local/stdio/uv 信息
3. ✅ AI 访问 OpenCode 文档确认了 command 数组格式
4. ✅ 自动配置了正确的 environment 字段名
5. ✅ 5 分钟完成安装

**关键因素：文档链接 → 自动分析 → 正确配置**
