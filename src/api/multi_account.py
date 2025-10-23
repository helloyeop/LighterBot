"""
API endpoints for multi-account management
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List, Optional
from datetime import datetime
import structlog
from src.core.account_manager import account_manager
from src.services.multi_account_signal_service import multi_account_signal_service

logger = structlog.get_logger()
router = APIRouter(prefix="/api/accounts", tags=["multi-account"])


@router.get("/")
async def get_all_accounts():
    """Get all configured accounts"""
    try:
        accounts = account_manager.get_all_accounts()
        return {
            "accounts": accounts,
            "total": len(accounts),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error("Failed to get accounts", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{account_index}")
async def get_account_info(account_index: int):
    """Get specific account information"""
    try:
        # Get account config
        config = account_manager.get_account_config(account_index)
        if not config:
            raise HTTPException(status_code=404, detail=f"Account {account_index} not found")

        # Get client and account info
        client = await account_manager.get_client(account_index)
        account_info = await client.get_account_info()

        # Get current positions from tracking
        positions = await multi_account_signal_service.get_account_positions(account_index)

        return {
            "account_index": account_index,
            "name": config.get('name', 'Unknown'),
            "active": config.get('active', True),
            "allowed_symbols": config.get('allowed_symbols', []),
            "balance": account_info.get('balance', {}),
            "positions": positions,
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get account info for {account_index}", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{account_index}/positions")
async def get_account_positions(account_index: int):
    """Get positions for specific account"""
    try:
        # Verify account exists
        config = account_manager.get_account_config(account_index)
        if not config:
            raise HTTPException(status_code=404, detail=f"Account {account_index} not found")

        # Get positions from DEX
        client = await account_manager.get_client(account_index)
        dex_positions = await client.get_positions()

        # Get tracked positions
        tracked_positions = await multi_account_signal_service.get_account_positions(account_index)

        return {
            "account_index": account_index,
            "account_name": config.get('name', 'Unknown'),
            "dex_positions": dex_positions,
            "tracked_positions": tracked_positions,
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get positions for account {account_index}", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions/all")
async def get_all_positions():
    """Get positions for all accounts"""
    try:
        all_positions = {}
        accounts = account_manager.get_all_accounts()

        for account_config in accounts:
            if account_config.get('active', True):
                account_index = account_config['account_index']
                try:
                    # Get positions for this account
                    positions = await multi_account_signal_service.get_account_positions(account_index)
                    all_positions[account_index] = {
                        "name": account_config.get('name', 'Unknown'),
                        "positions": positions
                    }
                except Exception as e:
                    logger.error(f"Failed to get positions for account {account_index}: {e}")
                    all_positions[account_index] = {
                        "name": account_config.get('name', 'Unknown'),
                        "positions": {},
                        "error": str(e)
                    }

        return {
            "accounts": all_positions,
            "total_accounts": len(all_positions),
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error("Failed to get all positions", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{account_index}/reload")
async def reload_account(account_index: int):
    """Reload/reconnect specific account"""
    try:
        config = account_manager.get_account_config(account_index)
        if not config:
            raise HTTPException(status_code=404, detail=f"Account {account_index} not found")

        # Recreate client connection
        await account_manager._create_client(account_index)

        return {
            "status": "success",
            "message": f"Account {account_index} reloaded successfully",
            "account_name": config.get('name', 'Unknown'),
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reload account {account_index}", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload-config")
async def reload_configuration():
    """Reload account configuration from accounts.json"""
    try:
        # Close existing clients
        await account_manager.close_all_clients()

        # Reload configuration
        account_manager.load_accounts()

        accounts = account_manager.get_all_accounts()

        return {
            "status": "success",
            "message": "Configuration reloaded successfully",
            "accounts_loaded": len(accounts),
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error("Failed to reload configuration", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balance/summary")
async def get_balance_summary():
    """Get balance summary for all accounts"""
    try:
        summary = {
            "total_balance": 0,
            "accounts": []
        }

        accounts = account_manager.get_all_accounts()

        for account_config in accounts:
            if account_config.get('active', True):
                account_index = account_config['account_index']
                try:
                    client = await account_manager.get_client(account_index)
                    account_info = await client.get_account_info()
                    balance = account_info.get('balance', {})
                    available = float(balance.get('available_balance', 0))

                    summary["accounts"].append({
                        "account_index": account_index,
                        "name": account_config.get('name', 'Unknown'),
                        "available_balance": available,
                        "collateral": float(balance.get('collateral', 0))
                    })
                    summary["total_balance"] += available

                except Exception as e:
                    logger.error(f"Failed to get balance for account {account_index}: {e}")
                    summary["accounts"].append({
                        "account_index": account_index,
                        "name": account_config.get('name', 'Unknown'),
                        "error": str(e)
                    })

        summary["timestamp"] = datetime.utcnow().isoformat()
        return summary

    except Exception as e:
        logger.error("Failed to get balance summary", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))