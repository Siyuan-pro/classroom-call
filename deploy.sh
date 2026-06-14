#!/bin/bash
# ============================================
# 课堂喊人传话系统 - 一键部署脚本
# 适用于：腾讯云/阿里云 Ubuntu 20.04+ 服务器
# 使用：bash deploy.sh
# ============================================

set -e

echo ""
echo "============================================"
echo "  课堂喊人传话系统 - 一键部署"
echo "============================================"
echo ""

# 检查是否 root
if [ "$EUID" -ne 0 ]; then
  echo "请使用 root 用户运行: sudo bash deploy.sh"
  exit 1
fi

# 1. 安装系统依赖
echo "[1/6] 安装系统依赖..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv nginx git > /dev/null 2>&1
echo "  完成"

# 2. 下载代码
echo "[2/6] 下载代码..."
if [ -d "/opt/classroom-call" ]; then
  cd /opt/classroom-call && git pull
else
  git clone https://github.com/Siyuan-pro/classroom-call.git /opt/classroom-call
fi
cd /opt/classroom-call
echo "  完成"

# 3. 安装 Python 依赖
echo "[3/6] 安装 Python 依赖..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -q
echo "  完成"

# 4. 配置 systemd 服务（开机自启）
echo "[4/6] 配置服务..."
cat > /etc/systemd/system/classroom-call.service << 'EOF'
[Unit]
Description=Classroom Call System
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/classroom-call
ExecStart=/opt/classroom-call/venv/bin/python server.py 9000
Restart=always
RestartSec=3
Environment=PORT=9000

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable classroom-call
systemctl restart classroom-call
echo "  完成"

# 5. 配置 Nginx 反向代理（80 端口访问）
echo "[5/6] 配置 Nginx..."
cat > /etc/nginx/sites-available/classroom-call << 'EOF'
server {
    listen 80;
    server_name _;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/classroom-call /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx
echo "  完成"

# 6. 开放防火墙端口
echo "[6/6] 配置防火墙..."
if command -v ufw &> /dev/null; then
  ufw allow 80/tcp > /dev/null 2>&1 || true
  ufw allow 9000/tcp > /dev/null 2>&1 || true
fi
if command -v firewall-cmd &> /dev/null; then
  firewall-cmd --permanent --add-port=80/tcp > /dev/null 2>&1 || true
  firewall-cmd --permanent --add-port=9000/tcp > /dev/null 2>&1 || true
  firewall-cmd --reload > /dev/null 2>&1 || true
fi
echo "  完成"

# 获取公网 IP
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s ip.sb 2>/dev/null || echo "YOUR_SERVER_IP")

echo ""
echo "============================================"
echo "  部署成功！"
echo "============================================"
echo ""
echo "  老师控制台: http://${PUBLIC_IP}/teacher"
echo "  教室显示屏: http://${PUBLIC_IP}/display"
echo "  首页入口:   http://${PUBLIC_IP}/"
echo ""
echo "  注意："
echo "  - 服务器开机自启，重启也不会停"
echo "  - 管理命令: systemctl restart/stop/status classroom-call"
echo "  - 云服务器安全组需放行 80 端口"
echo ""
