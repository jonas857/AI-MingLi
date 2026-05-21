# 腾讯云部署说明

## 准备

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm nginx
```

项目依赖本地 Node 包 `bazi-mcp`，因此部署时需要执行：

```bash
npm install
```

## Python 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 环境变量

复制模板并填写真实密钥：

```bash
cp env.template .env
```

生产环境建议至少设置：

```bash
FLASK_ENV=production
FLASK_DEBUG=false
SECRET_KEY=change-me
ENABLE_MCP_BAZI=true
ENABLE_MCP_ZIWEI=false
BAZI_CALC_PROVIDER=auto
```

开发者后台和 `/api/debug/*` 已移除，不再需要 `ENABLE_DEBUG_ROUTES` 或 `DEV_ADMIN_PIN`。

## systemd

```bash
sudo tee /etc/systemd/system/bazi.service >/dev/null <<'EOF'
[Unit]
Description=Bazi Analysis System
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/bazi-new
EnvironmentFile=/path/to/bazi-new/.env
ExecStart=/path/to/bazi-new/start-simplified-server.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable bazi
sudo systemctl restart bazi
sudo systemctl status bazi
```

## 验证

```bash
curl http://127.0.0.1:5002/api/status
```

如启用紫微 MCP，分析页会通过 `POST /api/ziwei/chart` 获取紫微排盘。
