#!/usr/bin/env python3
import asyncio
import sys
sys.path.append('/Users/hyeondong-yeob/Library/CloudStorage/OneDrive-개인/workspace_python/lighter_api/src')
from utils.price_fetcher import price_fetcher

async def main():
    prices = await price_fetcher.get_all_prices()
    # Filter out ETH, APEX, FF and sort by price (excluding very low value tokens)
    filtered = {k: v for k, v in prices.items() if k not in ['ETH', 'APEX', 'FF'] and v > 0.01}
    sorted_tokens = sorted(filtered.items(), key=lambda x: x[1], reverse=True)

    print('Available tokens (excluding ETH, APEX, FF):')
    for symbol, price in sorted_tokens[:15]:  # Show top 15
        print(f'{symbol}: ${price:.4f}')

if __name__ == "__main__":
    asyncio.run(main())