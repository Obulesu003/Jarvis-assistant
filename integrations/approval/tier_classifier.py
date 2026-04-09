"""
Approval tier classification for actions.
Defines which actions require approval and at what level.
"""

from enum import Enum


class ActionTier(Enum):
    """
    Action approval tiers.

    TIER_0_SILENT: Execute immediately, no notification
    TIER_1_INFO: Show what will happen, auto-proceed after delay
    TIER_2_CONFIRM: Require explicit yes/no confirmation
    TIER_3_BLOCK: Block unless explicitly enabled in config
    """

    TIER_0_SILENT = 0
    TIER_1_INFO = 1
    TIER_2_CONFIRM = 2
    TIER_3_BLOCK = 3

    def __str__(self) -> str:
        return f"Tier {self.value}"

    @property
    def display_name(self) -> str:
        names = {
            ActionTier.TIER_0_SILENT: "SILENT",
            ActionTier.TIER_1_INFO: "INFO",
            ActionTier.TIER_2_CONFIRM: "CONFIRM",
            ActionTier.TIER_3_BLOCK: "BLOCK",
        }
        return names.get(self, "UNKNOWN")

    @property
    def description(self) -> str:
        descriptions = {
            ActionTier.TIER_0_SILENT: "Execute silently (no approval needed)",
            ActionTier.TIER_1_INFO: "Show what will happen, auto-proceed",
            ActionTier.TIER_2_CONFIRM: "Require explicit confirmation",
            ActionTier.TIER_3_BLOCK: "Blocked unless enabled in config",
        }
        return descriptions.get(self, "")


class TierClassifier:
    """
    Classifies actions into approval tiers.

    Default classifications can be overridden via config.
    """

    # Default tier definitions
    DEFAULT_TIERS = {
        # Email actions
        "list_emails": ActionTier.TIER_0_SILENT,
        "search_emails": ActionTier.TIER_0_SILENT,
        "read_email": ActionTier.TIER_0_SILENT,
        "send_email": ActionTier.TIER_1_INFO,
        "reply_email": ActionTier.TIER_2_CONFIRM,
        "forward_email": ActionTier.TIER_2_CONFIRM,
        # Calendar actions
        "list_events": ActionTier.TIER_0_SILENT,
        "get_event": ActionTier.TIER_0_SILENT,
        "create_event": ActionTier.TIER_1_INFO,
        "update_event": ActionTier.TIER_2_CONFIRM,
        "delete_event": ActionTier.TIER_3_BLOCK,
        "find_meeting_time": ActionTier.TIER_0_SILENT,
        "quick_add": ActionTier.TIER_1_INFO,
        # WhatsApp actions
        "send_message": ActionTier.TIER_1_INFO,
        "send_image": ActionTier.TIER_1_INFO,
        "search_chat": ActionTier.TIER_0_SILENT,
        "get_chat_history": ActionTier.TIER_0_SILENT,
        "mark_read": ActionTier.TIER_0_SILENT,
        # Contacts actions
        "get_contact": ActionTier.TIER_0_SILENT,
        "search_contacts": ActionTier.TIER_0_SILENT,
        "list_contacts": ActionTier.TIER_0_SILENT,
        "get_relationship_context": ActionTier.TIER_0_SILENT,
        # Legacy actions (from existing tools)
        "email_tool": ActionTier.TIER_1_INFO,
        "reminder": ActionTier.TIER_1_INFO,
        "calendar_tool": ActionTier.TIER_1_INFO,
    }

    # Actions that are completely blocked by default
    BLOCKED_ACTIONS = {
        "delete_email",
        "delete_event",
        "delete_contact",
        "delete_reminder",
    }

    def __init__(self, config: dict | None = None):
        """
        Initialize classifier with optional config overrides.

        Config format:
        {
            "custom_tiers": {
                "send_email": "TIER_2_CONFIRM"
            },
            "blocked_actions": ["delete_event"],
            "allow_blocked": {
                "delete_event": True
            }
        }
        """
        self._config = config or {}
        self._custom_tiers = self._config.get("custom_tiers", {})
        self._blocked_actions = set(self._config.get("blocked_actions", []))
        self._allow_blocked = self._config.get("allow_blocked", {})

    def classify(self, action: str, params: dict | None = None) -> tuple[ActionTier, str]:
        """
        Classify an action into a tier.

        Returns:
            (tier, summary_text)
        """
        params = params or {}

        # Check if action is blocked
        if action in self.BLOCKED_ACTIONS or action in self._blocked_actions:
            if self._allow_blocked.get(action, False):
                tier = ActionTier.TIER_2_CONFIRM
            else:
                return ActionTier.TIER_3_BLOCK, f"Action '{action}' is blocked for safety. Enable in settings to proceed."

        # Check for custom tier override
        if action in self._custom_tiers:
            tier_name = self._custom_tiers[action]
            try:
                tier = ActionTier[tier_name.upper()]
            except KeyError:
                tier = ActionTier.TIER_1_INFO
            return tier, self._generate_summary(action, params)

        # Check service-prefixed actions
        for prefix in ["outlook_", "whatsapp_", "contacts_"]:
            if action.startswith(prefix):
                base_action = action[len(prefix):]
                tier = self.DEFAULT_TIERS.get(base_action, ActionTier.TIER_1_INFO)
                return tier, self._generate_summary(action, params)

        # Check direct match
        tier = self.DEFAULT_TIERS.get(action, ActionTier.TIER_1_INFO)
        return tier, self._generate_summary(action, params)

    def _generate_summary(self, action: str, params: dict) -> str:
        """Generate human-readable summary of what will happen."""
        # Email summaries
        email_summaries = {
            "send_email": f"Send email to {params.get('to', 'recipient')} about '{params.get('subject', '(no subject)')}'",
            "reply_email": f"Reply to email about '{params.get('subject', '')}'",
            "forward_email": f"Forward email to {params.get('to', 'recipient')}",
            "list_emails": f"List {params.get('folder', 'INBOX')} emails",
            "search_emails": f"Search emails for '{params.get('query', '')}'",
            "read_email": f"Read email about '{params.get('subject', '')}'",
        }

        # Calendar summaries
        calendar_summaries = {
            "create_event": f"Create event: '{params.get('title', 'Untitled')}' on {params.get('start', 'TBD')}",
            "update_event": f"Update event: '{params.get('title', params.get('event_id', ''))}'",
            "delete_event": f"DELETE event: '{params.get('event_id', '')}' - this cannot be undone!",
            "list_events": f"List calendar events for {params.get('date', 'today')}",
            "find_meeting_time": f"Find meeting time for {params.get('attendees', 'participants')}",
        }

        # WhatsApp summaries
        whatsapp_summaries = {
            "send_message": f"Send WhatsApp message to {params.get('receiver', 'contact')}: '{params.get('message', '')[:50]}...'",
            "send_image": f"Send image to {params.get('receiver', 'contact')}" + (f" with caption: '{params.get('caption', '')[:30]}...'" if params.get('caption') else ""),
            "search_chat": f"Search WhatsApp chats for '{params.get('query', '')}'",
            "get_chat_history": f"Get chat history with {params.get('chat_name', 'contact')}",
            "mark_read": f"Mark chat as read: {params.get('chat_name', 'current')}",
        }

        # Contacts summaries
        contacts_summaries = {
            "get_contact": f"Get contact details for '{params.get('name', params.get('email', 'contact'))}'",
            "search_contacts": f"Search contacts for '{params.get('query', '')}'",
            "list_contacts": "List all contacts",
            "get_relationship_context": f"Get relationship context for '{params.get('identifier', 'contact')}'",
        }

        # Combined summaries
        all_summaries = {}
        all_summaries.update(email_summaries)
        all_summaries.update(calendar_summaries)
        all_summaries.update(whatsapp_summaries)
        all_summaries.update(contacts_summaries)

        if action in all_summaries:
            return all_summaries[action]

        # Generic summary
        if params:
            param_str = ", ".join(f"{k}={v!r}" for k, v in list(params.items())[:3])
            return f"{action.replace('_', ' ')} ({param_str})"

        return action.replace("_", " ")

    def get_tier_config(self, tier: ActionTier) -> dict:
        """Get configuration for a tier."""
        configs = {
            ActionTier.TIER_0_SILENT: {"timeout": 0, "require_approval": False, "auto_proceed": True},
            ActionTier.TIER_1_INFO: {"timeout": 5, "require_approval": False, "auto_proceed": True},
            ActionTier.TIER_2_CONFIRM: {"timeout": 30, "require_approval": True, "auto_proceed": False},
            ActionTier.TIER_3_BLOCK: {"timeout": 0, "require_approval": False, "auto_proceed": False, "blocked": True},
        }
        return configs.get(tier, {})

    def is_blocked(self, action: str) -> bool:
        """Check if action is blocked."""
        return action in self.BLOCKED_ACTIONS or action in self._blocked_actions

    def allow_blocked(self, action: str) -> bool:
        """Check if blocked action has been explicitly allowed."""
        return self._allow_blocked.get(action, False)
