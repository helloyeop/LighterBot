#!/bin/bash

# VPS Deployment Script for Lighter API
# Run this script to deploy the application to your VPS

VPS_IP="158.247.223.133"
VPS_USER="root"
APP_DIR="/opt/lighter_api"

echo "🚀 Deploying Lighter API to VPS..."

# Create deployment package
echo "📦 Creating deployment package..."
tar --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='*.log' \
    -czf lighter_api_deploy.tar.gz \
    src/ \
    main.py \
    requirements.txt \
    .env

echo "📁 Package created: lighter_api_deploy.tar.gz"

echo "📋 Next steps to run on your VPS:"
echo ""
echo "1. Connect to your VPS:"
echo "   ssh root@${VPS_IP}"
echo ""
echo "2. Install Python and pip if not already installed:"
echo "   apt update && apt install -y python3 python3-pip python3-venv"
echo ""
echo "3. Create application directory:"
echo "   mkdir -p ${APP_DIR}"
echo "   cd ${APP_DIR}"
echo ""
echo "4. Upload and extract the deployment package:"
echo "   # From your local machine, upload the package:"
echo "   scp lighter_api_deploy.tar.gz root@${VPS_IP}:${APP_DIR}/"
echo ""
echo "   # On VPS, extract:"
echo "   tar -xzf lighter_api_deploy.tar.gz"
echo ""
echo "5. Create virtual environment and install dependencies:"
echo "   python3 -m venv venv"
echo "   source venv/bin/activate"
echo "   pip install -r requirements.txt"
echo ""
echo "6. Test the application:"
echo "   python3 main.py"
echo ""
echo "7. Create systemd service for auto-start:"
echo "   # Create service file"
echo "   cat > /etc/systemd/system/lighter-api.service << 'EOF'"
echo "[Unit]"
echo "Description=Lighter API Trading Bot"
echo "After=network.target"
echo ""
echo "[Service]"
echo "Type=simple"
echo "User=root"
echo "WorkingDirectory=${APP_DIR}"
echo "Environment=PATH=${APP_DIR}/venv/bin"
echo "ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/main.py"
echo "Restart=always"
echo "RestartSec=10"
echo ""
echo "[Install]"
echo "WantedBy=multi-user.target"
echo "EOF"
echo ""
echo "8. Enable and start the service:"
echo "   systemctl daemon-reload"
echo "   systemctl enable lighter-api"
echo "   systemctl start lighter-api"
echo ""
echo "9. Check service status:"
echo "   systemctl status lighter-api"
echo ""
echo "10. Test webhook endpoint:"
echo "    curl http://localhost:8000/webhook/health"
echo ""
echo "🎯 The application will be available at http://localhost:8000"
echo "🌐 Webhooks will be accessible at https://ypab5.com/webhook/tradingview"