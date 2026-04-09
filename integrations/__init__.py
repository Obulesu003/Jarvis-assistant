"""
Mark-XXXV Integration Package

Provides unified access to service integrations via browser automation
and native Windows APIs. No external API keys required.
"""

from .approval.tier_classifier import ActionTier, TierClassifier
from .approval.workflow import ApprovalWorkflow
from .base.adapter import BaseIntegrationAdapter
from .base.exceptions import (
    ElementNotFoundError,
    IntegrationError,
    RateLimitError,
    ServiceError,
    SessionExpiredError,
)
from .contacts.contacts_adapter import ContactsAdapter
from .outlook.outlook_adapter import OutlookAdapter
from .outlook.outlook_native_adapter import OutlookNativeAdapter
from .system.system_adapter import SystemAutomationAdapter
from .system.windows_app_adapter import WindowsAppAdapter
from .whatsapp.whatsapp_adapter import WhatsAppAdapter

__all__ = [
    "ActionTier",
    # Approval
    "ApprovalWorkflow",
    # Base
    "BaseIntegrationAdapter",
    "ContactsAdapter",
    "ElementNotFoundError",
    "IntegrationError",
    # Adapters
    "OutlookAdapter",
    "OutlookNativeAdapter",
    "RateLimitError",
    "ServiceError",
    "SessionExpiredError",
    "SystemAutomationAdapter",
    "TierClassifier",
    "WhatsAppAdapter",
    "WindowsAppAdapter",
]
