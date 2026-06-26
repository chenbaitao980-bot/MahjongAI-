# 部署指南（手机零配置）

## 核心方案

**原理**：
- PC 热点 + `dns_divert.py` 在网络层拦截 DNS（包括硬编码的 119.29.29.29/223.5.5.5）
- 热更请求自动落到 `setup_mitm.py`
- 注入 NetConf（改大厅地址）+ ResEnsure（跳过校验本地资源）
- 热更完成后，手机断热点切 4G，之后任意网络都能读牌

**手机不需要改任何设置**！

---

## 一、本地部署（PC 热点端）

### 前提
- PC 开启移动热点
- 以管理员身份运行

### 启动命令
```bash
# 在项目根目录，管理员终端
python remote/noconfig/hijack/run_hijack.py --host-ip 192.168.137.1
```

或使用脚本：
```batch
# 以管理员身份运行
scripts\start_local_mitm.bat
```

### 流程
1. PC 开热点，手机连接
2. 运行上述命令
3. 手机开游戏，等待热更
4. 看到 `NetConf.luac` 和 `ResEnsure.luac` 下载成功后，手机断热点
5. 之后手机任意网络（4G/WiFi）都能读牌

---

## 二、ECS 部署

### 方式 A：手动 SSH
```bash
ssh root@8.136.37.136
# 密码: Ysydxhyz111

# 重启服务
systemctl restart mahjong-tcp-proxy mahjong-relay-noconfig mahjong-mitm-hotupdate

# 检查状态
systemctl status mahjong-tcp-proxy mahjong-relay-noconfig mahjong-mitm-hotupdate
```

### 方式 B：Python 脚本同步代码
```bash
ECS_PASSWORD="Ysydxhyz111" python scripts/ecs_deploy_paramiko.py
```

---

## 三、验证

### ECS 服务状态
```bash
ssh root@8.136.37.136 "systemctl is-active mahjong-tcp-proxy mahjong-relay-noconfig"
```

### Relay 页面
访问: http://8.136.37.136:8002/state?token=d4a8e1f29c6b7305e8d1f264

### 端口检查
```bash
ssh root@8.136.37.136 "netstat -tlnp | grep -E '5748|5749|7777|8002'"
```

---

## 四、阿里云安全组

需要放行：
- TCP 5748/5749（大厅代理）
- TCP 7777（游服代理）
- TCP 8002（relay 展示）

---

## 五、故障排查

### 本地热更没触发
- 检查 `dns_divert` 日志是否拦截到 DNS 请求
- 检查手机是否连在 PC 热点上

### ECS 连接不上
- 检查安全组是否放行
- 检查 `tcp_proxy` 服务状态

### 手牌不显示
- 检查 `tcp_proxy` 日志是否有 `0x2bc0 hand_trusted`
- 检查 relay 8002 是否在监听