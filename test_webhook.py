#!/usr/bin/env python3
"""Test webhook endpoint with different payloads"""

import requests
import json
import time

# VPS endpoint
VPS_URL = "http://45.76.210.218/webhook/tradingview/account/143145"

# Test payloads
test_payloads = [
    {
        "name": "Test with sale field",
        "payload": {
            "secret": "lighter_to_the_moon_2918",
            "sale": "long",
            "symbol": "BTC",
            "leverage": 1,
            "quantity": 0.001
        }
    },
    {
        "name": "Test with action field",
        "payload": {
            "secret": "lighter_to_the_moon_2918",
            "action": "buy",
            "symbol": "BTC",
            "leverage": 1,
            "quantity": 0.001
        }
    },
    {
        "name": "Test short position",
        "payload": {
            "secret": "lighter_to_the_moon_2918",
            "sale": "short",
            "symbol": "BTC",
            "leverage": 1,
            "quantity": 0.001
        }
    }
]

def test_webhook(url, payload, name):
    print(f"\n{'='*50}")
    print(f"Testing: {name}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    print(f"{'='*50}")

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")

        if response.status_code == 200:
            print("✅ SUCCESS - Webhook accepted")
        else:
            print("❌ FAILED - Webhook rejected")

    except requests.exceptions.Timeout:
        print("❌ TIMEOUT - Server did not respond in 10 seconds")
    except requests.exceptions.ConnectionError as e:
        print(f"❌ CONNECTION ERROR - {e}")
    except Exception as e:
        print(f"❌ ERROR - {e}")

if __name__ == "__main__":
    print("Testing VPS webhook endpoint...")

    for test in test_payloads:
        test_webhook(VPS_URL, test["payload"], test["name"])
        time.sleep(2)  # Wait 2 seconds between tests

    print("\n" + "="*50)
    print("Testing complete!")
    print("\nNOTE: Check VPS logs with:")
    print("journalctl -u lighter-api -f")