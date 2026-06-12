# INHE Copilot 部署配置

## 架构

```
用户浏览器
  │
  ▼
https://www.inhe.ccwu.cc/ask/          ← Cloudflare Tunnel
  │
  ▼
http://127.0.0.1:5011                   ← Flask + Waitress (launcher.py)
  │  StripAskPrefix 中间件自动剥离 /ask
  ▼
Flask 路由 (/api/*, /copilot-panel, /kb-admin/...)
```

## 端口分配

| 服务 | 端口 | 说明 |
|------|------|------|
| Copilot 后端 | 5011 | Flask + Waitress, 8 线程 |
| Cloudflare Tunnel | - | 反代到 127.0.0.1:5011 |

## 启动方式

### 后端
```bat
cd D:\桌面文件\客服\copilot
python launcher.py
```

### Sidecar (千牛监控 + VLM)
```bat
cd D:\桌面文件\客服\copilot
start_sidecar.bat
```

## 访问地址

| 页面 | URL |
|------|-----|
| 千牛监控面板 | https://www.inhe.ccwu.cc/ask/copilot-panel |
| 知识库管理 | https://www.inhe.ccwu.cc/ask/kb-admin/ |
| 主控台 | https://www.inhe.ccwu.cc/ask/ |
| 设置 | https://www.inhe.ccwu.cc/ask/settings |
| Sidecar 状态 API | https://www.inhe.ccwu.cc/ask/api/sidecar/status |

## 环境变量

详见 `copilot/.env` 和 `copilot/sidecar.env`

## Cloudflare Tunnel 配置

在 `D:\桌面文件\inhe\cloudflared-config.yml` 的 ingress 中:

```yaml
- hostname: www.inhe.ccwu.cc
  path: /ask/*
  service: http://127.0.0.1:5011
```
