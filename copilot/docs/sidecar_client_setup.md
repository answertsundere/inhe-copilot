# 千牛 Sidecar 客服电脑接入说明

## 使用场景

后端只需要在主机运行一份，例如：

```text
http://192.168.110.144:5000
```

每个客服电脑都必须运行自己的 Sidecar。网页本身不能读取千牛窗口，Sidecar 才能读取本机千牛并把上下文发给后端。

## 一键安装方式

客服电脑只需要复制整个 `copilot` 文件夹，然后双击：

```text
scripts\sidecar\install_sidecar_client.bat
```

安装脚本会自动完成：

- 检查后端 `http://192.168.110.144:5000`
- 检查 Python
- 如果没有 Python，会尝试用 winget 自动安装 Python 3.12
- 创建 `.venv-sidecar`
- 安装依赖
- 保存本机 Sidecar 配置到 `data\sidecar\client.env`
- 在桌面创建 `INHE客服Sidecar` 快捷方式

以后客服只需要双击桌面 `INHE客服Sidecar`。

注意：为了让客服不用每次输入 VLM API Key，安装脚本会把 Key 保存到客服电脑本机的 `data\sidecar\client.env`。这台电脑应只给内部客服使用。

## 手动安装方式

如果一键安装失败，再按下面步骤手动处理。

## 客服电脑准备

1. 确认客服电脑和主机在同一局域网。
2. 确认客服电脑能打开：

```text
http://192.168.110.144:5000/copilot-panel
```

3. 安装 Python 3.11+，安装时勾选 `Add Python to PATH`。
4. 复制整个 `copilot` 项目目录到客服电脑。
5. 在项目目录执行一次依赖安装：

```powershell
python -m pip install -r requirements.txt
```

## 启动方式

双击：

```text
scripts\sidecar\start_sidecar_client.bat
```

首次启动会要求输入 VLM API Key，输入时不会显示。脚本只在当前窗口进程内使用该 Key，不会写入文件。

## 正常使用

1. 打开千牛接待中心。
2. 不要最小化千牛窗口。
3. 打开 Copilot 面板：

```text
http://192.168.110.144:5000/copilot-panel
```

4. Sidecar 会自动读取当前千牛会话，并把客户消息、订单候选、商品候选发送到后端。
5. Copilot 只生成建议回复，不会自动发送到千牛。

## 常见问题

### 网页能打开，但不自动识别

检查客服电脑是否运行了 Sidecar。只打开网页不会读取千牛。

### 提示 window_minimized

千牛窗口被最小化或不可见。恢复千牛接待中心窗口到前台。

### 后端连接失败

检查主机是否运行后端，主机防火墙是否放行 5000 端口，客服电脑是否能访问：

```text
http://192.168.110.144:5000/api/health
```

### VLM 识别失败

确认 API Key 有效，且模型、请求地址可用。当前脚本默认：

```text
SIDECAR_VISION_BASE_URL=https://apihub.agnes-ai.com/v1
SIDECAR_VISION_MODEL=agnes-2.0-flash
```
