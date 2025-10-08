#!/usr/bin/env python3
"""
Simple startup script for Lighter Trading Bot
"""
import sys
import os
import asyncio
import subprocess

def check_python_version():
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        sys.exit(1)
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} detected")

def check_env_file():
    if not os.path.exists(".env"):
        print("❌ .env file not found!")
        print("📝 Copy .env.example to .env and configure your API keys:")
        print("   cp .env.example .env")
        print("   # Edit .env file with your Lighter API keys")
        return False
    print("✅ .env file found")
    return True

def install_dependencies():
    print("📦 Installing dependencies...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                      check=True, capture_output=True)
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False

def main():
    print("🚀 Starting Lighter Trading Bot Setup...")

    # Check Python version
    check_python_version()

    # Check environment file
    if not check_env_file():
        sys.exit(1)

    # Install dependencies
    if not install_dependencies():
        sys.exit(1)

    # Create data directory
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    print("✅ Directories created")

    print("\n🎯 Starting trading bot...")
    print("📊 Access API docs at: http://127.0.0.1:8000/docs")
    print("💻 Monitor logs in console")
    print("🛑 Press Ctrl+C to stop\n")

    # Start the application
    try:
        import uvicorn
        uvicorn.run(
            "main:app",
            host="127.0.0.1",
            port=8000,
            reload=False,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n✋ Trading bot stopped by user")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()