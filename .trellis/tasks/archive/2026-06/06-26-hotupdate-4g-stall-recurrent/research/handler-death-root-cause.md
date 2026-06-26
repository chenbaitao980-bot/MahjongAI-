# Hotupdate Handler 死锁真因分析

## 时间线

| 时间 | 事件 |
|---|---|
| 16:00 | 进程 15569 启动（systemd） |
| 18:48 | DNS responder 收到大量 amazon.com 查询（非劫持域名，转发上游） |
| 19:17 | scanner reject (3.129.187.38 → /) |
| **19:20:07** | 正常服务客户端 39.184.31.145 热更请求 |
| **19:20:17** | 正常服务客户端 223.104.166.111 热更请求 |
| **19:20:17~21:16** | **完全静默**：无 HTTP 请求日志、无 ERROR、无异常 |
| 21:11 | watchdog 首次探测到 1/2 endpoint down，counter 卡 1 |
| 21:16 | 用户/systemd 手动重启，新进程 27817 启动 |

## 现场状态（15569 死时）

| 指标 | 值 | 正常值 | 说明 |
|---|---|---|---|
| 线程数 | 3 | 10~50+ | 主线程 + DNS 线程 + serve_forever 线程 |
| fd 数 | 少 | 几十 | handler thread 全灭 |
| CPU | 0.0% | 低但非零 | 无活跃计算 |
| 上下文切换 | 7 次 | 1000+ | 无网络活动 |
| TCP:443 | 2× CLOSE-WAIT + 2× ESTAB(1 无 owner) | LISTEN + 活跃连接 | socket 半死 |
| 日志 ERROR | 0 | — | 无异常抛出 |
| core dump | 无 | — | 不是 segfault |

## 根因推断

### 代码结构问题

```python
# setup_mitm.py:1149
threading.Thread(target=httpd.serve_forever, daemon=True).start()
# ...
threading.Event().wait()  # 主线程永远阻塞
```

- `ThreadingHTTPServer` = `HTTPServer` + `ThreadingMixIn`
- `serve_forever` 运行在 **daemon thread**
- 主线程在 `Event().wait()` 永远阻塞
- DNS responder 运行在另一个 daemon thread

### 死亡机制

`BaseServer.serve_forever()` 简化逻辑：

```python
while not self.__shutdown_request:
    ready = selector.select(poll_interval)
    if ready:
        self._handle_request_noblock()
```

当以下任一情况发生：
1. SSL `wrap_socket` 在 server_side 遇到损坏的 client hello → 抛异常
2. `selector.select()` 遇到损坏的 fd → 抛 `OSError` (EBADF)
3. `socket.accept()` 遇到底层 TCP 栈异常

serve_forever 线程**因未捕获异常退出**。但由于它是 daemon thread：
- 异常不会传播到主线程
- 主线程继续 `Event().wait()`
- DNS 线程继续 `recvfrom()`
- **systemd 看到 PID 还在 → 认为 healthy**

### 为什么不是资源耗尽

- fd 数不多
- 线程数不多  
- 没有 OOM
- 没有 CPU 100%

### 为什么不是 CLOSE-WAIT 累积

R4/R7 修复（finish() 关闭 + 连接超时）已在代码中，但 handler 仍然全灭。CLOSE-WAIT 只是 socket 状态 symptom，不是 root cause。

## 对比：正常进程 27817 的线程栈

```
Thread 1: futex_wait_queue_me  ← 主线程 Event().wait()
Thread 2: do_poll               ← serve_forever 正常 poll
Thread 3: udp_recvmsg           ← DNS responder 正常 recvfrom
```

正常时 serve_forever 在 `poll()` 中等待。15569 死时也可能卡在 poll() 中，但 socket 层不再 accept 新连接（可能是 fd 损坏）。

## 修复方案

**根本修复**：把 `serve_forever` 放到**主线程**运行。当 serve_forever 因异常退出时，主线程继续执行（或抛异常），进程退出，systemd `Restart=always` 自动拉起。

```python
# Before (dangerous: serve_forever in daemon thread)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
threading.Event().wait()

# After (safe: main thread runs serve_forever)
httpd.serve_forever()  # 主线程运行；异常退出 = 进程退出 = systemd 重启
```

DNS 线程保持 daemon（或也 non-daemon），不影响核心逻辑。

## 相关 commit

- 744f0a7: CLOSE-WAIT 修复（R4 finish）
- 7a67ac4: R7 超时加固（扫描器连接挂住）
- 78865c2: watchdog 加入（外部监督）
- 9be8998: watchdog counter reset 修复
- 7f51232: curl HTTP code 探测（Windows MSYS 兼容）
