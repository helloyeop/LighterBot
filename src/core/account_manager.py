"""
Account Manager - Wrapper for backward compatibility
This file maintains compatibility while using the improved account_manager_v2
"""

# Import the improved version
from .account_manager_v2 import (
    AccountManagerV2 as AccountManager,
    LighterAccountClientV2 as LighterAccountClient,
    account_manager_v2
)

# Export for backward compatibility
account_manager = account_manager_v2

# Re-export classes for any direct imports
__all__ = ['AccountManager', 'LighterAccountClient', 'account_manager']