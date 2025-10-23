#!/usr/bin/env python3
"""
Migration script: Convert single account system to multi-account system
This script reads .env file and creates/updates accounts.json
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

def migrate_to_multi_account():
    """Migrate from .env single account to accounts.json multi-account"""

    # Load environment variables
    env_path = Path('.env')
    if not env_path.exists():
        print("❌ .env file not found")
        return False

    load_dotenv(env_path)

    # Get account details from .env
    account_config = {
        "account_index": int(os.getenv('LIGHTER_ACCOUNT_INDEX', 0)),
        "api_key_index": int(os.getenv('LIGHTER_API_KEY_INDEX', 0)),
        "api_key": os.getenv('LIGHTER_API_KEY', ''),
        "api_secret": os.getenv('LIGHTER_API_SECRET', ''),
        "name": "Primary Account",
        "active": True,
        "allowed_symbols": []  # Empty = all symbols allowed
    }

    # Check if allowed_symbols is set in env
    allowed_symbols_env = os.getenv('ALLOWED_SYMBOLS', '')
    if allowed_symbols_env:
        account_config["allowed_symbols"] = [s.strip() for s in allowed_symbols_env.split(',')]

    # Prepare accounts.json structure
    accounts_json = {
        "accounts": [account_config],
        "default_account_index": account_config["account_index"]
    }

    # Check if accounts.json already exists
    config_dir = Path('config')
    config_dir.mkdir(exist_ok=True)

    accounts_file = config_dir / 'accounts.json'

    if accounts_file.exists():
        print("⚠️  accounts.json already exists")

        # Load existing file
        with open(accounts_file, 'r') as f:
            existing = json.load(f)

        # Check if this account already exists
        existing_indices = [acc['account_index'] for acc in existing.get('accounts', [])]

        if account_config['account_index'] in existing_indices:
            print(f"Account {account_config['account_index']} already exists in accounts.json")
            response = input("Do you want to update it? (y/n): ").lower()

            if response == 'y':
                # Update existing account
                for i, acc in enumerate(existing['accounts']):
                    if acc['account_index'] == account_config['account_index']:
                        existing['accounts'][i] = account_config
                        break
                accounts_json = existing
            else:
                print("Migration cancelled")
                return False
        else:
            # Add to existing accounts
            response = input("Do you want to add this account to existing accounts? (y/n): ").lower()

            if response == 'y':
                existing['accounts'].append(account_config)
                accounts_json = existing
            else:
                print("Migration cancelled")
                return False

    # Write accounts.json
    with open(accounts_file, 'w') as f:
        json.dump(accounts_json, f, indent=2)

    print(f"✅ Successfully migrated to multi-account system")
    print(f"📁 Configuration saved to: {accounts_file}")
    print(f"📊 Total accounts: {len(accounts_json['accounts'])}")

    # Display account summary
    print("\n📋 Account Summary:")
    for acc in accounts_json['accounts']:
        status = "🟢 Active" if acc['active'] else "🔴 Inactive"
        symbols = acc['allowed_symbols'] if acc['allowed_symbols'] else "All"
        print(f"  - {acc['name']} (Index: {acc['account_index']})")
        print(f"    Status: {status}")
        print(f"    Allowed Symbols: {symbols}")

    # Provide usage instructions
    print("\n📝 Usage Instructions:")
    print("1. The system now uses accounts.json for configuration")
    print("2. You can add more accounts by editing config/accounts.json")
    print("3. Webhook URLs:")
    print(f"   - Specific account: /webhook/tradingview/account/{account_config['account_index']}")
    print("   - All accounts: /webhook/tradingview")
    print("\n4. To use only this single account, just keep 1 account in accounts.json")
    print("5. The old signal_trading_service.py is no longer needed")

    return True

def check_system_status():
    """Check current system configuration status"""
    print("\n🔍 Checking System Status...")

    # Check .env
    if Path('.env').exists():
        print("✅ .env file found")
    else:
        print("❌ .env file not found")

    # Check accounts.json
    accounts_file = Path('config/accounts.json')
    if accounts_file.exists():
        print("✅ accounts.json found")

        with open(accounts_file, 'r') as f:
            accounts = json.load(f)

        num_accounts = len(accounts.get('accounts', []))
        print(f"   - {num_accounts} account(s) configured")

        if num_accounts == 1:
            print("   - Running in single-account mode")
        else:
            print("   - Running in multi-account mode")
    else:
        print("❌ accounts.json not found (using legacy single-account mode)")

    # Check if old service is still referenced
    main_file = Path('main.py')
    if main_file.exists():
        with open(main_file, 'r') as f:
            content = f.read()

        if 'signal_trading_service' in content and 'multi_account_signal_service' not in content:
            print("⚠️  main.py still uses old signal_trading_service")
            print("   Run migration to update to multi-account system")
        elif 'multi_account_signal_service' in content:
            print("✅ main.py uses multi-account service")
        else:
            print("✅ main.py properly configured")

if __name__ == "__main__":
    print("=" * 50)
    print("Multi-Account Migration Tool")
    print("=" * 50)

    # Check current status
    check_system_status()

    # Ask user if they want to migrate
    print("\n" + "=" * 50)
    response = input("\nDo you want to migrate to multi-account system? (y/n): ").lower()

    if response == 'y':
        if migrate_to_multi_account():
            print("\n✅ Migration completed successfully!")
            print("\n⚠️  Note: You no longer need signal_trading_service.py")
            print("The multi-account system handles both single and multiple accounts.")
        else:
            print("\n❌ Migration failed or cancelled")
    else:
        print("\nMigration cancelled")