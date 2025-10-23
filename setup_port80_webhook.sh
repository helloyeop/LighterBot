#!/bin/bash

# Setup script for TradingView webhook support on port 80/443
# This script configures Nginx to proxy webhook requests to the application

VPS_IP="158.247.223.133"
VPS_USER="root"
DOMAIN="ypab5.com"

echo "🔧 Setting up Port 80/443 webhook support for TradingView..."

echo "📋 Steps to configure on your VPS:"
echo ""

echo "1. 📥 Upload nginx configuration:"
echo "   scp nginx/lighter-api.conf root@${VPS_IP}:/etc/nginx/sites-available/lighter-api"
echo ""

echo "2. 🔗 Enable the site:"
echo "   ssh root@${VPS_IP} 'ln -sf /etc/nginx/sites-available/lighter-api /etc/nginx/sites-enabled/'"
echo ""

echo "3. 🧪 Test nginx configuration:"
echo "   ssh root@${VPS_IP} 'nginx -t'"
echo ""

echo "4. 🔄 Restart nginx:"
echo "   ssh root@${VPS_IP} 'systemctl restart nginx'"
echo ""

echo "5. 🚀 Ensure your application is running on port 8000:"
echo "   ssh root@${VPS_IP} 'cd /opt/lighter_api && systemctl start lighter-api'"
echo ""

echo "6. ✅ Test the webhook endpoint:"
echo "   curl https://${DOMAIN}/webhook/health"
echo ""

echo "📝 TradingView Webhook URLs to use:"
echo ""
echo "🎯 For specific account:"
echo "   https://${DOMAIN}/webhook/tradingview/account/143145"
echo ""
echo "🎯 For all accounts:"
echo "   https://${DOMAIN}/webhook/tradingview"
echo ""
echo "📊 Monitor webhook requests:"
echo "   ssh root@${VPS_IP} 'tail -f /var/log/nginx/webhook_access.log'"
echo ""

# Additional configuration for SSL if not set up
echo "🔐 SSL Configuration (if not already set up):"
echo ""
echo "Install Certbot:"
echo "   ssh root@${VPS_IP} 'apt update && apt install -y certbot python3-certbot-nginx'"
echo ""
echo "Get SSL certificate:"
echo "   ssh root@${VPS_IP} 'certbot --nginx -d ${DOMAIN}'"
echo ""

# Firewall configuration
echo "🛡️ Firewall Configuration:"
echo ""
echo "Allow HTTP and HTTPS:"
echo "   ssh root@${VPS_IP} 'ufw allow 80/tcp && ufw allow 443/tcp'"
echo ""

# Auto-execution option
read -p "🤖 Do you want to auto-execute these commands? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]
then
    echo "🚀 Executing setup commands..."

    # Upload nginx config
    echo "📤 Uploading nginx configuration..."
    scp nginx/lighter-api.conf root@${VPS_IP}:/etc/nginx/sites-available/lighter-api

    # Enable site and restart nginx
    echo "🔧 Configuring nginx..."
    ssh root@${VPS_IP} '
        ln -sf /etc/nginx/sites-available/lighter-api /etc/nginx/sites-enabled/
        nginx -t && systemctl restart nginx
        ufw allow 80/tcp && ufw allow 443/tcp
    '

    # Test the endpoint
    echo "🧪 Testing webhook endpoint..."
    sleep 3
    curl -s https://${DOMAIN}/webhook/health | python -m json.tool || echo "Test failed - check if application is running"

    echo "✅ Setup completed!"
    echo ""
    echo "🎯 Your webhook URLs are ready:"
    echo "   - All accounts: https://${DOMAIN}/webhook/tradingview"
    echo "   - Specific account: https://${DOMAIN}/webhook/tradingview/account/143145"

else
    echo "⏸️ Manual setup required. Follow the steps above."
fi