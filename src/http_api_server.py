"""HTTP API 服务器 - 提供群聊列表管理接口"""
import asyncio
import json
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional

from src.logger import logger
from src.config import global_config


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """支持多线程的HTTP服务器"""
    allow_reuse_address = True
    daemon_threads = True


class APIHandler(BaseHTTPRequestHandler):
    """HTTP API请求处理器"""
    
    def log_message(self, format, *args):
        """重载日志方法，使用项目logger"""
        logger.debug(f"HTTP {self.command} {self.path}")
    
    def _send_json_response(self, status_code: int, data: dict):
        """发送JSON响应"""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    
    def _send_error(self, status_code: int, message: str):
        """发送错误响应"""
        self._send_json_response(status_code, {"success": False, "error": message})
    
    def do_OPTIONS(self):
        """处理CORS预检请求"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    
    def do_GET(self):
        """处理GET请求"""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query_params = parse_qs(parsed_url.query)
        
        # 只处理 /api 路径
        if path != "/api":
            self._send_error(404, "Not Found")
            return
        
        # 获取操作类型
        do = query_params.get("do", [None])[0]
        
        if do == "update_group_list":
            self._handle_update_group_list(query_params)
        elif do == "get_group_list":
            self._handle_get_group_list()
        else:
            self._send_error(400, f"Unknown action: {do}")
    
    def _handle_update_group_list(self, query_params: dict):
        """处理更新群聊列表请求
        
        请求示例: /api?do=update_group_list&id=123456&action=add
        请求示例: /api?do=update_group_list&id=123456&action=rm
        """
        try:
            # 获取群号
            group_id_str = query_params.get("id", [None])[0]
            if not group_id_str:
                self._send_error(400, "Missing required parameter: id")
                return
            
            try:
                group_id = int(group_id_str)
            except ValueError:
                self._send_error(400, f"Invalid group id: {group_id_str}")
                return
            
            # 获取操作类型
            action = query_params.get("action", [None])[0]
            if action not in ["add", "rm"]:
                self._send_error(400, "Missing or invalid parameter: action (must be 'add' or 'rm')")
                return
            
            # 获取当前群聊列表
            current_list = list(global_config.chat.group_list)
            
            if action == "add":
                if group_id in current_list:
                    self._send_json_response(200, {
                        "success": True,
                        "message": f"Group {group_id} already exists in list",
                        "data": {"group_list": current_list}
                    })
                    return
                
                current_list.append(group_id)
                logger.info(f"HTTP API: 添加群号 {group_id} 到群聊列表")
                
            elif action == "rm":
                if group_id not in current_list:
                    self._send_json_response(200, {
                        "success": True,
                        "message": f"Group {group_id} not found in list",
                        "data": {"group_list": current_list}
                    })
                    return
                
                current_list.remove(group_id)
                logger.info(f"HTTP API: 从群聊列表移除群号 {group_id}")
            
            # 更新配置
            global_config.chat.group_list = current_list
            
            # 保存到配置文件
            self._save_config()
            
            self._send_json_response(200, {
                "success": True,
                "message": f"Group {group_id} {action}ed successfully",
                "data": {"group_list": current_list}
            })
            
        except Exception as e:
            logger.error(f"HTTP API 处理更新群聊列表请求失败: {e}")
            self._send_error(500, f"Internal server error: {str(e)}")
    
    def _handle_get_group_list(self):
        """处理获取群聊列表请求
        
        请求示例: /api?do=get_group_list
        """
        try:
            current_list = list(global_config.chat.group_list)
            list_type = global_config.chat.group_list_type
            
            self._send_json_response(200, {
                "success": True,
                "data": {
                    "group_list_type": list_type,
                    "group_list": current_list,
                    "count": len(current_list)
                }
            })
        except Exception as e:
            logger.error(f"HTTP API 处理获取群聊列表请求失败: {e}")
            self._send_error(500, f"Internal server error: {str(e)}")
    
    def _save_config(self):
        """保存配置到文件"""
        try:
            import tomlkit
            import shutil
            from datetime import datetime
            
            config_path = "config.toml"
            
            # 读取当前配置文件
            with open(config_path, "r", encoding="utf-8") as f:
                config_doc = tomlkit.load(f)
            
            # 更新群聊列表
            if "chat" in config_doc and "group_list" in config_doc["chat"]:
                config_doc["chat"]["group_list"] = global_config.chat.group_list
            
            # 保存更新后的配置
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(tomlkit.dumps(config_doc))
            
            logger.debug("HTTP API: 配置文件已更新")
            
        except Exception as e:
            logger.error(f"HTTP API 保存配置失败: {e}")
            raise


class HttpApiServer:
    """HTTP API服务器管理类"""
    
    def __init__(self):
        self.server: Optional[ThreadedHTTPServer] = None
        self.server_thread: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self, host: str = "localhost", port: int = 3012):
        """启动HTTP API服务器
        
        Args:
            host: 监听地址
            port: 监听端口
        """
        if self._running:
            logger.warning("HTTP API服务器已在运行")
            return
        
        try:
            self.server = ThreadedHTTPServer((host, port), APIHandler)
            self._running = True
            
            # 在后台线程中运行服务器
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._serve_forever)
            
        except OSError as e:
            if e.errno == 10048 or "address already in use" in str(e).lower():
                logger.error(f"❌ HTTP API端口 {port} 已被占用")
            else:
                logger.error(f"❌ HTTP API服务器启动失败: {e}")
            self._running = False
            raise
        except Exception as e:
            logger.error(f"❌ HTTP API服务器启动失败: {e}")
            self._running = False
            raise
    
    def _serve_forever(self):
        """在后台线程中运行服务器"""
        logger.info(f"✅ HTTP API服务器已启动: http://{self.server.server_address[0]}:{self.server.server_address[1]}")
        self.server.serve_forever()
    
    def stop(self):
        """停止HTTP API服务器"""
        if not self._running:
            return
        
        logger.info("正在停止HTTP API服务器...")
        self._running = False
        
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        
        logger.info("HTTP API服务器已停止")


# 全局HTTP API服务器实例
http_api_server = HttpApiServer()
