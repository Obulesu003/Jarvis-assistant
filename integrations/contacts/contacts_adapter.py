"""
Contacts adapter using Windows Contacts via pywin32.
Integrates with Windows People app and contacts.
"""

import logging
import os
from dataclasses import dataclass

from integrations.base.adapter import ActionResult, BaseIntegrationAdapter

logger = logging.getLogger(__name__)


@dataclass
class Contact:
    """Contact representation."""
    name: str
    email: str
    phone: str
    company: str
    title: str
    notes: str


class ContactsAdapter(BaseIntegrationAdapter):
    """
    Windows Contacts adapter.

    Uses multiple sources:
    1. Windows People app (via COM)
    2. Windows Contacts folder (C:\\Users\\*\\Contacts)
    3. Outlook contacts (if available)
    """

    SERVICE_NAME = "contacts"
    DEFAULT_TIMEOUT = 15
    DEFAULT_CACHE_TTL = 600  # 10 minutes

    def __init__(self):
        super().__init__()
        self._contacts_cache = None
        self._load_contacts()
        logger.info("[Contacts] Adapter initialized")

    def get_capabilities(self) -> list[str]:
        """Return list of supported operations."""
        return [
            "get_contact",
            "search_contacts",
            "list_contacts",
            "get_relationship_context",
        ]

    def _load_contacts(self):
        """Load contacts from Windows sources."""
        contacts = {}

        # Method 1: Load from Windows Contacts folder (vCard files)
        try:
            contacts_folder = os.path.join(os.path.expanduser("~"), "Contacts")
            if os.path.exists(contacts_folder):
                for filename in os.listdir(contacts_folder):
                    if filename.endswith(".vcf"):
                        filepath = os.path.join(contacts_folder, filename)
                        contact = self._parse_vcard(filepath)
                        if contact:
                            key = contact.email or contact.name
                            contacts[key.lower()] = contact
        except Exception as e:
            logger.warning(f"[Contacts] Could not load from Contacts folder: {e}")

        # Method 2: Try Outlook contacts via COM
        try:
            outlook_contacts = self._get_outlook_contacts()
            for contact in outlook_contacts:
                key = contact.email or contact.name
                contacts[key.lower()] = contact
        except Exception as e:
            logger.warning(f"[Contacts] Could not load Outlook contacts: {e}")

        self._contacts_cache = contacts
        logger.info(f"[Contacts] Loaded {len(contacts)} contacts")

    def _parse_vcard(self, filepath: str) -> Contact | None:
        """Parse a vCard file."""
        try:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()

            name = ""
            email = ""
            phone = ""
            company = ""
            title = ""
            notes = ""

            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("FN:"):
                    name = line[3:]
                elif line.startswith("N:"):
                    parts = line[3:].split(";")
                    if len(parts) >= 2:
                        name = f"{parts[1]} {parts[0]}".strip()
                elif line.startswith("EMAIL"):
                    email = line.split(":")[-1].strip()
                elif line.startswith("TEL"):
                    phone = line.split(":")[-1].strip()
                elif line.startswith("ORG:"):
                    company = line[4:].strip()
                elif line.startswith("TITLE:"):
                    title = line[6:].strip()
                elif line.startswith("NOTE:"):
                    notes = line[5:].strip()

            if name or email:
                return Contact(
                    name=name,
                    email=email,
                    phone=phone,
                    company=company,
                    title=title,
                    notes=notes,
                )
        except Exception as e:
            logger.warning(f"[Contacts] Could not parse vCard {filepath}: {e}")

        return None

    def _get_outlook_contacts(self) -> list[Contact]:
        """Get contacts from Outlook via COM."""
        contacts = []
        try:
            import win32com.client

            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")

            # Get Contacts folder
            contacts_folder = namespace.GetDefaultFolder(10)  # olFolderContacts

            for item in contacts_folder.Items:
                try:
                    name = getattr(item, "FullName", "") or getattr(item, "Subject", "")
                    email = getattr(item, "Email1Address", "") or ""
                    phone = getattr(item, "MobileTelephoneNumber", "") or getattr(item, "TelephoneNumber", "") or ""
                    company = getattr(item, "CompanyName", "") or ""
                    title = getattr(item, "JobTitle", "") or ""

                    if name or email:
                        contacts.append(
                            Contact(
                                name=name.strip(),
                                email=email.strip() if email else "",
                                phone=phone.strip() if phone else "",
                                company=company.strip() if company else "",
                                title=title.strip() if title else "",
                                notes="",
                            )
                        )
                except Exception:
                    continue

        except ImportError:
            logger.warning("[Contacts] pywin32 not installed, Outlook contacts unavailable")
        except Exception as e:
            logger.warning(f"[Contacts] Error accessing Outlook contacts: {e}")

        return contacts

    def _is_session_active(self) -> bool:
        """Check if contacts are accessible."""
        return self._contacts_cache is not None

    def _execute_action(self, action: str, **kwargs) -> ActionResult:
        """Route action to appropriate method."""
        method_name = f"_action_{action}"
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            try:
                return method(**kwargs)
            except Exception as e:
                return ActionResult(success=False, error=str(e))
        else:
            return ActionResult(success=False, error=f"Unknown action: {action}")

    def _action_get_contact(self, name: str | None = None, email: str | None = None, **kwargs) -> ActionResult:
        """Get a specific contact by name or email."""
        if not name and not email:
            return ActionResult(success=False, error="Name or email required")

        try:
            if email:
                contact = self._contacts_cache.get(email.lower())
                if contact:
                    return ActionResult(success=True, data=self._contact_to_dict(contact))

            if name:
                # Search by name (partial match)
                name_lower = name.lower()
                for key, contact in self._contacts_cache.items():
                    if name_lower in contact.name.lower() or name_lower in key:
                        return ActionResult(success=True, data=self._contact_to_dict(contact))

            return ActionResult(success=False, error=f"Contact not found: {name or email}")

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_search_contacts(self, query: str, max_results: int = 20, **kwargs) -> ActionResult:
        """Search contacts by name, email, or company."""
        try:
            query_lower = query.lower()
            results = []

            for contact in self._contacts_cache.values():
                score = 0
                matched_fields = []

                if query_lower in contact.name.lower():
                    score = 10
                    matched_fields.append("name")
                elif query_lower in contact.email.lower():
                    score = 8
                    matched_fields.append("email")
                elif query_lower in contact.company.lower():
                    score = 5
                    matched_fields.append("company")
                elif query_lower in contact.phone:
                    score = 6
                    matched_fields.append("phone")

                if score > 0:
                    results.append(
                        {
                            "name": contact.name,
                            "email": contact.email,
                            "phone": contact.phone,
                            "company": contact.company,
                            "score": score,
                            "matched_fields": matched_fields,
                        }
                    )

            # Sort by score
            results.sort(key=lambda x: x["score"], reverse=True)
            results = results[:max_results]

            return ActionResult(success=True, data=results)

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_list_contacts(self, max_results: int = 100, **kwargs) -> ActionResult:
        """List all contacts."""
        try:
            contacts_list = []
            for contact in list(self._contacts_cache.values())[:max_results]:
                contacts_list.append(self._contact_to_dict(contact))

            return ActionResult(success=True, data=contacts_list)

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_get_relationship_context(self, identifier: str, **kwargs) -> ActionResult:
        """Get relationship context for a contact."""
        try:
            # Search for the contact
            contact = None
            identifier_lower = identifier.lower()

            for c in self._contacts_cache.values():
                if (
                    identifier_lower in c.name.lower()
                    or identifier_lower in c.email.lower()
                    or identifier_lower in c.company.lower()
                ):
                    contact = c
                    break

            if not contact:
                return ActionResult(success=False, error=f"Contact not found: {identifier}")

            # Get context from memory (if available)
            context = self._get_memory_context(contact.email)

            return ActionResult(
                success=True,
                data={
                    "contact": self._contact_to_dict(contact),
                    "memory": context,
                    "found": True,
                }
            )

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _get_memory_context(self, email: str | None = None) -> dict:
        """Get relationship context from memory."""
        context = {}
        try:
            from memory.memory_manager import MemoryManager

            mm = MemoryManager()
            memory = mm.load_memory()

            # Look for relationship data
            relationships = memory.get("relationships", {})
            notes = memory.get("notes", {})

            # Search for this contact in relationships
            if email:
                for key, entry in relationships.items():
                    if email.lower() in str(entry).lower():
                        context[key] = entry
                for key, entry in notes.items():
                    if email.lower() in str(entry).lower():
                        context[key] = entry

        except Exception as e:
            logger.debug(f"[Contacts] Could not load memory context: {e}")

        return context

    def _contact_to_dict(self, contact: Contact) -> dict:
        """Convert Contact to dictionary."""
        return {
            "name": contact.name,
            "email": contact.email,
            "phone": contact.phone,
            "company": contact.company,
            "title": contact.title,
            "notes": contact.notes,
        }

    def refresh(self):
        """Reload contacts from sources."""
        self._load_contacts()
        self.invalidate_cache()

    def requires_approval(self, action: str, params: dict) -> tuple[bool, str]:
        """Check if action requires approval. Contacts are read-only in Phase 1."""
        return False, ""

    def add_contact_note(self, email: str, note: str):
        """Add a note to a contact in memory."""
        try:
            from memory.memory_manager import MemoryManager

            mm = MemoryManager()
            memory = mm.load_memory()

            notes = memory.get("notes", {})
            note_key = f"contact_{email.replace('@', '_at_')}"
            notes[note_key] = {"value": note, "updated": str(self._get_date())}

            memory["notes"] = notes
            mm.save_memory(memory)

        except Exception as e:
            logger.error(f"[Contacts] Could not save note: {e}")

    def update_last_contacted(self, email: str):
        """Update last contacted timestamp."""
        try:
            from memory.memory_manager import MemoryManager

            mm = MemoryManager()
            memory = mm.load_memory()

            # Create or update contact entry
            contacts = memory.get("contacts", {})
            contact_key = email
            if contact_key in contacts:
                data = contacts[contact_key]
                if isinstance(data, dict):
                    data["last_contacted"] = str(self._get_date())
                else:
                    data = {"last_contacted": str(self._get_date())}
            else:
                data = {"last_contacted": str(self._get_date())}

            contacts[contact_key] = data
            memory["contacts"] = contacts
            mm.save_memory(memory)

        except Exception as e:
            logger.error(f"[Contacts] Could not update last contacted: {e}")

    def _get_date(self):
        """Get current date."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")
