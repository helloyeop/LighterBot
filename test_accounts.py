#!/usr/bin/env python3
"""Test multi-account connection and authentication"""

import asyncio
import json
from lighter_api import BlockchainSigner, LighterApi
from lighter_api.modules import Account as AccountModule

async def test_account(account_config):
    """Test single account connection"""
    print(f"\n{'='*50}")
    print(f"Testing Account: {account_config['name']} (Index: {account_config['account_index']})")
    print(f"API Key Index: {account_config['api_key_index']}")
    print(f"{'='*50}")

    try:
        # Initialize signer
        signer = BlockchainSigner(
            private_key=account_config['api_secret'],
            account_index=account_config['account_index'],
            api_key_index=account_config['api_key_index']
        )

        # Initialize API client
        client = LighterApi(
            api_auth="https://mainnet.zklighter.elliot.ai",
            api="wss://mainnet.zklighter.elliot.ai",
            websocket="wss://mainnet.zklighter.elliot.ai",
            web="https://mainnet.zklighter.elliot.ai"
        )

        # Authenticate
        auth_result = await client.authenticate(signer, account_config['api_key'])
        print(f"✅ Authentication successful!")

        # Get account info
        account_api = AccountModule(client.client)
        account_data = await account_api.account(
            by="index",
            value=str(account_config['account_index'])
        )

        if account_data and hasattr(account_data, 'accounts') and account_data.accounts:
            account = account_data.accounts[0]
            print(f"✅ Account data retrieved successfully")
            if hasattr(account, 'balance'):
                print(f"   Balance info available")
        else:
            print(f"⚠️  No account data returned")

        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False
    finally:
        if 'client' in locals():
            await client.client.close()

async def main():
    # Load accounts configuration
    with open('config/accounts.json', 'r') as f:
        config = json.load(f)

    accounts = config['accounts']

    print("Testing all configured accounts...")
    print(f"Total accounts: {len(accounts)}")

    results = []
    for account in accounts:
        if account.get('active', True):
            success = await test_account(account)
            results.append({
                'name': account['name'],
                'index': account['account_index'],
                'api_key_index': account['api_key_index'],
                'success': success
            })
            await asyncio.sleep(1)  # Small delay between tests

    # Summary
    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    for result in results:
        status = "✅" if result['success'] else "❌"
        print(f"{status} {result['name']} (Index: {result['index']}, API Key Index: {result['api_key_index']})")

    successful = sum(1 for r in results if r['success'])
    print(f"\nSuccess rate: {successful}/{len(results)}")

    if successful < len(results):
        print("\n⚠️  Some accounts failed authentication.")
        print("Check that api_key_index matches the key index on Lighter platform.")

if __name__ == "__main__":
    asyncio.run(main())