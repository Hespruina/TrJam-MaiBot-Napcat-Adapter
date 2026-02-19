import asyncio
import sys
import json
import http
import websockets as Server
from src.logger import logger
from src.recv_handler.message_handler import message_handler
from src.recv_handler.meta_event_handler import meta_event_handler
from src.recv_handler.notice_handler import notice_handler
from src.recv_handler.message_sending import message_send_instance
from src.send_handler.nc_sending import nc_message_sender
from src.config import global_config
from src.mmc_com_layer import mmc_start_com, mmc_stop_com, router
from src.response_pool import put_response, check_timeout_response
from src.http_api_server import http_api_server
from src.prompt_injection_detector import get_detector

message_queue = asyncio.Queue()
websocket_server = None  # 保存WebSocket服务器实例以便关闭

# 消息处理状态跟踪
pending_messages = 0  # 等待处理的消息数量
processing_messages = 0  # 正在处理的消息数量

# 关闭标志
shutdown_requested = False  # 是否收到关闭请求（Ctrl+C）


async def message_recv(server_connection: Server.ServerConnection):
    global pending_messages, processing_messages
    try:
        await message_handler.set_server_connection(server_connection)
        asyncio.create_task(notice_handler.set_server_connection(server_connection))
        await nc_message_sender.set_server_connection(server_connection)
        
        # 设置prompt注入检测器的连接
        if global_config.prompt_injection.enable:
            detector = get_detector()
            detector.set_server_connection(server_connection)
        
        async for raw_message in server_connection:
            # 检查是否收到关闭请求
            if shutdown_requested:
                logger.info("余量处理模式：停止接收新消息")
                break
            
            logger.debug(f"{raw_message[:1500]}..." if (len(raw_message) > 1500) else raw_message)
            decoded_raw_message: dict = json.loads(raw_message)
            post_type = decoded_raw_message.get("post_type")
            if post_type in ["meta_event", "message", "notice"]:
                await message_queue.put(decoded_raw_message)
                pending_messages += 1
            elif post_type is None:
                await put_response(decoded_raw_message)
    except asyncio.CancelledError:
        logger.debug("message_recv 收到取消信号，正在关闭连接")
        await server_connection.close()
        raise


async def message_process():
    global pending_messages, processing_messages
    while True:
        # 检查是否收到关闭请求且没有待处理消息
        if shutdown_requested and pending_messages == 0 and processing_messages == 0:
            logger.info("余量处理模式：所有消息已处理完成")
            break
        
        # 使用 try_get 避免阻塞
        try:
            message = await asyncio.wait_for(message_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue
        
        post_type = message.get("post_type")
        if post_type == "message":
            processing_messages += 1
            await message_handler.handle_raw_message(message)
            processing_messages -= 1
        elif post_type == "meta_event":
            await meta_event_handler.handle_meta_event(message)
        elif post_type == "notice":
            await notice_handler.handle_notice(message)
        else:
            logger.warning(f"未知的post_type: {post_type}")
        message_queue.task_done()
        await asyncio.sleep(0.05)


async def main():
    # 启动配置文件监控并注册napcat_server配置变更回调
    from src.config import config_manager
    
    # 保存napcat_server任务的引用，用于重启
    napcat_task = None
    restart_event = asyncio.Event()
    
    async def on_napcat_config_change(old_value, new_value):
        """当napcat_server配置变更时，重启WebSocket服务器"""
        nonlocal napcat_task
        
        logger.warning(
            f"NapCat配置已变更:\n"
            f"  旧配置: {old_value.host}:{old_value.port}\n"
            f"  新配置: {new_value.host}:{new_value.port}"
        )
        
        # 关闭当前WebSocket服务器
        global websocket_server
        if websocket_server:
            try:
                logger.info("正在关闭旧的WebSocket服务器...")
                websocket_server.close()
                await websocket_server.wait_closed()
                logger.info("旧的WebSocket服务器已关闭")
            except Exception as e:
                logger.error(f"关闭旧WebSocket服务器失败: {e}")
        
        # 取消旧任务
        if napcat_task and not napcat_task.done():
            napcat_task.cancel()
            try:
                await napcat_task
            except asyncio.CancelledError:
                pass
        
        # 触发重启
        restart_event.set()
    
    config_manager.on_config_change("napcat_server", on_napcat_config_change)
    
    # 启动文件监控
    asyncio.create_task(config_manager.start_watch())
    
    # WebSocket服务器重启循环
    async def napcat_with_restart():
        nonlocal napcat_task
        while True:
            restart_event.clear()
            try:
                await napcat_server()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"NapCat服务器异常: {e}")
                break
            
            # 等待重启信号
            if not restart_event.is_set():
                break
            
            logger.info("正在重启WebSocket服务器...")
            await asyncio.sleep(1)  # 等待1秒后重启

    # 启动HTTP API服务器（如果启用）
    http_api_task = None
    if global_config.http_api.enable:
        http_api_task = asyncio.create_task(
            http_api_server.start(
                host=global_config.http_api.host,
                port=global_config.http_api.port
            )
        )
    
    tasks = [napcat_with_restart(), mmc_start_com(), message_process(), check_timeout_response()]
    if http_api_task:
        tasks.append(http_api_task)
    
    _ = await asyncio.gather(*tasks)

def check_napcat_server_token(conn, request):
    token = global_config.napcat_server.token
    if not token or token.strip() == "":
        return None
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {token}":
        return Server.Response(
            status=http.HTTPStatus.UNAUTHORIZED,
            headers=Server.Headers([("Content-Type", "text/plain")]),
            body=b"Unauthorized\n"
        )
    return None

async def napcat_server():
    global websocket_server
    logger.info("正在启动 MaiBot-Napcat-Adapter...")
    logger.debug(f"日志等级: {global_config.debug.level}")
    logger.debug("日志文件: logs/adapter_*.log")
    try:
        async with Server.serve(
            message_recv, 
            global_config.napcat_server.host, 
            global_config.napcat_server.port, 
            max_size=2**26, 
            process_request=check_napcat_server_token
        ) as server:
            websocket_server = server
            logger.success(
                f"✅ Adapter 启动成功! 监听: ws://{global_config.napcat_server.host}:{global_config.napcat_server.port}"
            )
            try:
                await server.serve_forever()
            except asyncio.CancelledError:
                logger.debug("napcat_server 收到取消信号")
                raise
    except OSError:
        # 端口绑定失败时抛出异常让外层处理
        raise


async def graceful_shutdown(silent: bool = False):
    """
    优雅关闭adapter
    Args:
        silent: 静默模式,控制台不输出日志,但仍记录到日志文件
    """
    global websocket_server, pending_messages, processing_messages, shutdown_requested
    try:
        if not silent:
            logger.info("正在关闭adapter...")
        else:
            logger.debug("正在清理资源...")
        
        # 设置关闭标志，进入余量处理模式
        shutdown_requested = True
        if not silent:
            logger.info("余量处理模式：停止接收新消息，专注处理剩余消息")
        
        # 等待所有消息处理完成
        wait_interval = 0.1  # 每0.1秒检查一次
        max_wait_time = 30  # 最多等待30秒
        waited_time = 0
        
        while True:
            if pending_messages == 0 and processing_messages == 0:
                logger.debug("所有消息已处理完成")
                break
            
            if waited_time >= max_wait_time:
                logger.warning(f"等待消息处理超时（{max_wait_time}秒），强制关闭")
                break
            
            await asyncio.sleep(wait_interval)
            waited_time += wait_interval
            
            if not silent and waited_time > 0 and waited_time % 5 < wait_interval:
                logger.info(f"余量处理中... 待处理: {pending_messages}, 正在处理: {processing_messages}")
        
        # 清理prompt注入检测器
        try:
            from src.prompt_injection_detector import cleanup_detector
            await cleanup_detector()
        except Exception as e:
            logger.debug(f"清理prompt注入检测器时出现错误: {e}")
        
        # 先关闭HTTP API服务器
        try:
            http_api_server.stop()
        except Exception as e:
            logger.debug(f"关闭HTTP API服务器时出现错误: {e}")
        
        # 先关闭WebSocket服务器
        if websocket_server:
            try:
                logger.debug("正在关闭WebSocket服务器")
                websocket_server.close()
                await websocket_server.wait_closed()
                logger.debug("WebSocket服务器已关闭")
            except Exception as e:
                logger.debug(f"关闭WebSocket服务器时出现错误: {e}")
        
        # 关闭MMC连接
        try:
            await asyncio.wait_for(mmc_stop_com(), timeout=3)
        except asyncio.TimeoutError:
            logger.debug("关闭MMC连接超时")
        except Exception as e:
            logger.debug(f"关闭MMC连接时出现错误: {e}")
        
        # 取消所有任务
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            logger.debug(f"正在取消 {len(tasks)} 个任务")
        for task in tasks:
            if not task.done():
                task.cancel()
        
        # 等待任务完成,记录异常到日志文件
        if tasks:
            try:
                results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=3)
                # 记录任务取消的详细信息到日志文件
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.debug(f"任务 {i+1} 清理时产生异常: {type(result).__name__}: {result}")
            except asyncio.TimeoutError:
                logger.debug("任务清理超时")
            except Exception as e:
                logger.debug(f"任务清理时出现错误: {e}")
        
        if not silent:
            logger.info("Adapter已成功关闭")
        else:
            logger.debug("资源清理完成")
    except Exception as e:
        logger.debug(f"graceful_shutdown异常: {e}", exc_info=True)


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.warning("收到中断信号，进入余量处理模式...")
        try:
            loop.run_until_complete(graceful_shutdown(silent=False))
        except Exception:
            pass
    except OSError as e:
        # 处理端口占用等网络错误
        if e.errno == 10048 or "address already in use" in str(e).lower():
            logger.error(f"❌ 端口 {global_config.napcat_server.port} 已被占用，请检查:")
            logger.error("   1. 是否有其他 MaiBot-Napcat-Adapter 实例正在运行")
            logger.error("   2. 修改 config.toml 中的 port 配置")
            logger.error(f"   3. 使用命令查看占用进程: netstat -ano | findstr {global_config.napcat_server.port}")
        else:
            logger.error(f"❌ 网络错误: {str(e)}")
        
        logger.debug("完整错误信息:", exc_info=True)
        
        # 端口占用时静默清理(控制台不输出,但记录到日志文件)
        try:
            loop.run_until_complete(graceful_shutdown(silent=True))
        except Exception as e:
            logger.debug(f"清理资源时出现错误: {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 主程序异常: {str(e)}")
        logger.debug("详细错误信息:", exc_info=True)
        try:
            loop.run_until_complete(graceful_shutdown(silent=True))
        except Exception as e:
            logger.debug(f"清理资源时出现错误: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # 清理事件循环
        try:
            # 取消所有剩余任务
            pending = asyncio.all_tasks(loop)
            if pending:
                logger.debug(f"finally块清理 {len(pending)} 个剩余任务")
                for task in pending:
                    task.cancel()
                # 给任务一点时间完成取消
                try:
                    results = loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    # 记录清理结果到日志文件
                    for i, result in enumerate(results):
                        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                            logger.debug(f"剩余任务 {i+1} 清理异常: {type(result).__name__}: {result}")
                except Exception as e:
                    logger.debug(f"清理剩余任务时出现错误: {e}")
        except Exception as e:
            logger.debug(f"finally块清理出现错误: {e}")
        finally:
            if loop and not loop.is_closed():
                logger.debug("关闭事件循环")
                loop.close()
        sys.exit(0)
