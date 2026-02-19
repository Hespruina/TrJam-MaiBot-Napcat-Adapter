from dataclasses import dataclass, field
from typing import Literal

from src.config.config_base import ConfigBase

"""
须知：
1. 本文件中记录了所有的配置项
2. 所有新增的class都需要继承自ConfigBase
3. 所有新增的class都应在config.py中的Config类中添加字段
4. 对于新增的字段，若为可选项，则应在其后添加field()并设置default_factory或default
"""

ADAPTER_PLATFORM = "qq"


@dataclass
class NicknameConfig(ConfigBase):
    nickname: str
    """机器人昵称"""


@dataclass
class NapcatServerConfig(ConfigBase):
    host: str = "localhost"
    """Napcat服务端的主机地址"""

    port: int = 8095
    """Napcat服务端的端口号"""

    token: str = ""
    """Napcat服务端的访问令牌，若无则留空"""

    heartbeat_interval: int = 30
    """Napcat心跳间隔时间，单位为秒"""


@dataclass
class MaiBotServerConfig(ConfigBase):
    platform_name: str = field(default=ADAPTER_PLATFORM, init=False)
    """平台名称，“qq”"""

    host: str = "localhost"
    """MaiMCore的主机地址"""

    port: int = 8000
    """MaiMCore的端口号"""

    enable_api_server: bool = False
    """是否启用API-Server模式连接"""

    base_url: str = ""
    """API-Server连接地址 (ws://ipp:port/path)"""

    api_key: str = ""
    """API Key (仅在enable_api_server为True时使用)"""


@dataclass
class ChatConfig(ConfigBase):
    group_list_type: Literal["whitelist", "blacklist"] = "whitelist"
    """群聊列表类型 白名单/黑名单"""

    group_list: list[int] = field(default_factory=[])
    """群聊列表"""

    private_list_type: Literal["whitelist", "blacklist"] = "whitelist"
    """私聊列表类型 白名单/黑名单"""

    private_list: list[int] = field(default_factory=[])
    """私聊列表"""

    ban_user_id: list[int] = field(default_factory=[])
    """被封禁的用户ID列表，封禁后将无法与其进行交互"""

    ban_qq_bot: bool = False
    """是否屏蔽QQ官方机器人，若为True，则所有QQ官方机器人将无法与MaiMCore进行交互"""

    enable_poke: bool = True
    """是否启用戳一戳功能"""


@dataclass
class VoiceConfig(ConfigBase):
    use_tts: bool = False
    """是否启用TTS功能"""


@dataclass
class ForwardConfig(ConfigBase):
    """转发消息相关配置"""
    
    image_threshold: int = 3
    """图片数量阈值：转发消息中图片数量超过此值时，使用占位符代替base64发送，避免麦麦VLM处理卡死"""


@dataclass
class DebugConfig(ConfigBase):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    """日志级别，默认为INFO"""


@dataclass
class HttpApiConfig(ConfigBase):
    enable: bool = True
    """是否启用HTTP API"""

    host: str = "localhost"
    """HTTP API监听地址"""

    port: int = 3014
    """HTTP API端口"""


@dataclass
class PromptInjectionConfig(ConfigBase):
    """Prompt注入检测配置"""

    enable: bool = False
    """是否启用prompt注入检测"""

    base_url: str = "https://api.openai.com/v1"
    """OpenAI API基础URL"""

    api_key: str = ""
    """OpenAI API密钥"""

    models: list[str] = field(default_factory=lambda: ["gpt-3.5-turbo"])
    """用于检测的模型列表，将随机选择一个使用"""

    report_groups: list[int] = field(default_factory=list)
    """检测报告推送的群组列表（不包含具体消息内容）"""

    sensitivity: int = 2
    """敏感度等级（1-4）
    1: 只拦截 HIGH 风险
    2: 拦截 HIGH 和 MEDIUM 风险
    3: 拦截 HIGH、MEDIUM 和 LOW 风险
    4: 拦截所有风险（包括 NONE，仅用于测试）
    """
