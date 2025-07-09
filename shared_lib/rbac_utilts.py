# shared_lib/rbac_utils.py

from typing import List, Set
from enum import Enum
from shared_lib.rbac_policy import RBAC_POLICIES
from shared_lib.intents_enum import IntentName
from shared_lib.tool_enum import AllowedToolName


def get_user_permissions(user_roles: List[str]) -> dict:
    allowed_intents: Set[str] = set()
    allowed_tools: Set[str] = set()

    for role in user_roles:
        role_policy = RBAC_POLICIES.get(role, {})
        intents = role_policy.get("allowed_intents", [])
        tools = role_policy.get("allowed_tools", [])

        if "*" in intents:
            allowed_intents = {"*"}
        else:
            allowed_intents.update(
                [i.value if isinstance(i, Enum) else i for i in intents]
            )

        if "*" in tools:
            allowed_tools = {"*"}
        else:
            allowed_tools.update(
                [t.value if isinstance(t, Enum) else t for t in tools]
            )

    return {
        "intents": allowed_intents,
        "tools": allowed_tools,
    }


def is_intent_allowed(intent: str, allowed_intents: Set[str]) -> bool:
    return "*" in allowed_intents or intent in allowed_intents


def are_tools_allowed(plan: List[dict], allowed_tools: Set[str]) -> bool:
    for step in plan:
        name = step.get("name")
        if not name:
            continue
        if "*" not in allowed_tools and name not in allowed_tools:
            return False
    return True
