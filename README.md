# TrJam-MaiBot-Napcat-Adapter

MaiBot 与 Napcat 的适配器。本项目基于 [MaiBot-Napcat-Adapter](https://github.com/Mai-with-u/MaiBot-Napcat-Adapter ) 修改而来，在官方原版基础上添加了与 **ZHRrobot-TrJam** 联动的功能及部分实验性特性。

遵循 **GPL-3.0** 协议开源。

## 项目说明

本适配器用于连接 Napcat 客户端与 MaiBot 服务，独立运行.

### 主要变更

本适配器在官方原版基础上进行了以下重要修改：

#### 1. HTTP API 接口

新增了 HTTP API 服务器，提供群聊列表管理功能，支持动态添加/移除群聊，无需重启服务。

**功能特性：**
- 支持通过 HTTP GET 请求管理群聊列表
- 自动将修改同步到配置文件 `config.toml`
- 提供 CORS 支持，方便前端调用
- 支持获取当前群聊列表和列表类型

**API 接口：**

- **获取群聊列表**
  ```
  GET /api?do=get_group_list
  ```
  返回：当前群聊列表、列表类型（whitelist/blacklist）、群聊数量

- **添加群聊**
  ```
  GET /api?do=update_group_list&id={群号}&action=add
  ```
  功能：将指定群号添加到群聊列表

- **移除群聊**
  ```
  GET /api?do=update_group_list&id={群号}&action=rm
  ```
  功能：从群聊列表中移除指定群号

**配置说明：**
```toml
[http_api]
enable = true           # 是否启用HTTP API
host = "localhost"      # HTTP API监听地址
port = 30014            # HTTP API端口
```

**实现文件：** [src/http_api_server.py](src/http_api_server.py)

#### 2. Prompt 注入检测

集成了基于 AI 的 Prompt 注入检测功能，使用 OpenAI 兼容 API 对用户消息进行安全检测，防止恶意提示词注入攻击。

**功能特性：**
- 使用 LLM 模型进行智能检测，支持多种模型
- 四级敏感度配置（HIGH/MEDIUM/LOW/NONE）
- 自动拦截高风险消息，防止恶意指令注入
- 向用户发送警告消息
- 向指定群组推送检测报告（不含具体消息内容）
- 多模型重试机制，提高检测可靠性
- 使用随机 safecode 和 XML 标签破坏技术防止注入

**检测流程：**
1. 提取纯文本消息内容
2. 调用 AI 模型进行风险分析
3. 根据敏感度配置判断是否拦截
4. 记录日志并发送警告/报告

**配置说明：**
```toml
[prompt_injection]
enable = true                    # 是否启用prompt注入检测
base_url = "https://api.openai.com/v1"  # OpenAI API基础URL
api_key = "sk-xxx"               # OpenAI API密钥
models = ["gpt-3.5-turbo", "gpt-4"]  # 用于检测的模型列表，将随机选择一个使用
report_groups = [123456]        # 检测报告推送的群组列表
sensitivity = 2                  # 敏感度等级（1-4）
```

**敏感度等级说明：**
- `1`: 只拦截 HIGH 风险
- `2`: 拦截 HIGH 和 MEDIUM 风险
- `3`: 拦截 HIGH、MEDIUM 和 LOW 风险
- `4`: 拦截所有风险（仅用于测试）

**实现文件：**
- 核心检测逻辑：[src/prompt_injection_detector.py](src/prompt_injection_detector.py)
- 消息发送集成：[src/recv_handler/message_sending.py](src/recv_handler/message_sending.py)
- 安全规则配置：[safe_rules.md](safe_rules.md)

#### 3. 优雅关闭机制

实现了完善的优雅关闭机制，确保程序退出时处理完所有转发到 MaiBot 的任务，避免消息丢失或处理中断。

**功能特性：**
- Ctrl+C 触发余量处理模式
- 停止接收新消息，专注处理剩余消息
- 实时显示待处理和正在处理的消息数量
- 最多等待 30 秒完成剩余任务
- 按顺序清理资源：HTTP API → WebSocket → MMC → 异步任务
- 详细的关闭日志记录

**关闭流程：**
1. 设置关闭标志，停止接收新消息
2. 等待消息队列中的所有消息处理完成
3. 清理 Prompt 注入检测器（关闭 HTTP 会话）
4. 停止 HTTP API 服务器
5. 关闭 WebSocket 服务器
6. 关闭 MMC 连接
7. 取消所有异步任务
8. 关闭事件循环

**实现文件：** [main.py](main.py) 中的 `graceful_shutdown()` 函数

---

## 使用说明

基础配置与运行方式请参考 [MaiBot 官方文档](https://docs.mai-mai.org/manual/adapters/napcat.html )。

> **注意**：由于本项目增加了特定联动功能，部分配置文件可能需要额外字段，具体请参考本仓库下的配置文件或源码注释。

### 新增配置项说明

在 `config.toml` 中新增了以下配置节：

```toml
[http_api]          # HTTP API 设置
[prompt_injection]   # Prompt注入检测设置
```

请根据实际需求配置这些参数。


## 特别鸣谢

本项目基于以下开源项目开发，特此感谢：

- 原项目：[MaiBot-Napcat-Adapter](https://github.com/Mai-with-u/MaiBot-Napcat-Adapter )

## 许可证

本项目继承原项目协议，采用 **GNU General Public License v3.0** (GPL-3.0) 开源。
你可以自由使用、修改和分发，但衍生作品必须同样保持开源并使用相同协议。
