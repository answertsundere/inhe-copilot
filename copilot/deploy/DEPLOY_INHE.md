# 客服系统部署到 INHE 平台

## 原理

```
用户访问: www.inhe.ccwu.cc/ask/training-samples
              │
              ▼
     Cloudflare Tunnel  (path: /ask/* → service: http://127.0.0.1:5011)
              │  转发原始路径 /ask/training-samples
              ▼
     Flask + WSGI 中间件  (StripPathPrefix)
              │  剥离 /ask → /training-samples
              ▼
     Flask 路由匹配 /training-samples → 正常返回
```

Flask 代码零改动，中间件在 `run_prod.py` 中包装。

## 你只需要做一件事

在 `D:\桌面文件\inhe\cloudflared-config.yml` 的 ingress 最前面加一条：

```yaml
  # 客服 Copilot 知识库系统
  - hostname: www.inhe.ccwu.cc
    path: /ask/*
    service: http://127.0.0.1:5011
```

然后重启 Cloudflare Tunnel。

## 启动客服系统

```bat
:: 方式 1: 一键重启（清缓存+重启）
D:\桌面文件\客服\restart-copilot.bat

:: 方式 2: 手动
cd D:\桌面文件\客服\copilot
python run_prod.py
```

## 访问地址

| 页面 | URL |
|------|-----|
| 客服工作台 | https://www.inhe.ccwu.cc/ask/real-test |
| 训练样本收集 | https://www.inhe.ccwu.cc/ask/training-samples |
| 知识库管理后台 | https://www.inhe.ccwu.cc/ask/kb-admin/ |
| 旧知识库管理 | https://www.inhe.ccwu.cc/ask/knowledge-admin |
| API | https://www.inhe.ccwu.cc/ask/api/kb/* |
| 设置 | https://www.inhe.ccwu.cc/ask/settings |

本地开发仍可直接访问：
- http://127.0.0.1:5011/ask/real-test
- http://127.0.0.1:5011/ask/training-samples
- http://127.0.0.1:5011/ask/kb-admin/
