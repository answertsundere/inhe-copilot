#!/bin/bash
# INHE 客服系统一键部署脚本
# 使用方式: bash deploy.sh
# 前提: 服务器已有 Python 3.10+、Node.js 18+、Nginx

set -e

APP_DIR="/opt/inhe-copilot"
REPO_DIR="$APP_DIR/copilot"
SERVICE_NAME="inhe-copilot"

echo "=========================================="
echo "  INHE 客服系统部署"
echo "  目标目录: $APP_DIR"
echo "=========================================="

# 1. 创建目录
echo "[1/6] 创建目录..."
sudo mkdir -p $APP_DIR
sudo mkdir -p /etc/nginx/ssl

# 2. 复制项目文件
echo "[2/6] 复制项目文件..."
# 从当前机器上传到服务器，或用 git clone
# sudo cp -r copilot/ $REPO_DIR/
echo "  请先将项目文件上传到 $REPO_DIR"
echo "  方式1: scp -r copilot/ user@www.inhe.ccwu.cc:$REPO_DIR/"
echo "  方式2: cd $REPO_DIR && git clone <repo-url> ."

# 3. 安装 Python 依赖
echo "[3/6] 安装 Python 依赖..."
if [ ! -d "$REPO_DIR/venv" ]; then
    sudo python3 -m venv $REPO_DIR/venv
fi
sudo $REPO_DIR/venv/bin/pip install -r $REPO_DIR/requirements.txt

# 4. 安装 Node.js 依赖并构建前端
echo "[4/6] 构建前端..."
cd $REPO_DIR/frontend
npm install
npm run build
cd $REPO_DIR

# 5. 配置 Nginx
echo "[5/6] 配置 Nginx..."
sudo cp deploy/nginx_inhe.conf /etc/nginx/sites-available/inhe-copilot
sudo ln -sf /etc/nginx/sites-available/inhe-copilot /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 6. 配置 systemd 服务
echo "[6/6] 配置 systemd 服务..."
sudo cp deploy/inhe-copilot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl start $SERVICE_NAME

echo ""
echo "=========================================="
echo "  部署完成！"
echo "=========================================="
echo ""
echo "  访问地址:"
echo "    客服助手:   https://www.inhe.ccwu.cc/"
echo "    知识库管理: https://www.inhe.ccwu.cc/kb-admin/"
echo ""
echo "  常用命令:"
echo "    查看状态:   sudo systemctl status $SERVICE_NAME"
echo "    查看日志:   sudo journalctl -u $SERVICE_NAME -f"
echo "    重启服务:   sudo systemctl restart $SERVICE_NAME"
echo "    更新部署:   cd $REPO_DIR && git pull && cd frontend && npm run build && cd .. && sudo systemctl restart $SERVICE_NAME"
echo ""
echo "  注意: 请确保 SSL 证书已放置到 /etc/nginx/ssl/"
echo "        请确保 .env 文件已配置到 $REPO_DIR/.env"
