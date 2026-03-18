"""
Safety Classifier for Hedgehog

Classifies actions into safety levels and manages approval workflow.

Safety Levels:
- SAFE: Read-only operations, no side effects (auto-execute)
- MODERATE: Write operations with bounded impact (log and execute)
- RISKY: Operations that could affect system state (require confirmation)
- DESTRUCTIVE: Operations that could cause data loss (block or require admin)
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from hedgehog.tools.base import SafetyLevel

logger = logging.getLogger(__name__)


class ApprovalStatus(Enum):
    """Approval status for actions."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"
    BLOCKED = "blocked"


@dataclass
class ActionClassification:
    """Classification result for an action."""
    action: str
    safety_level: SafetyLevel
    approval_status: ApprovalStatus
    reason: str
    requires_confirmation: bool = False
    risk_factors: List[str] = field(default_factory=list)
    mitigations: List[str] = field(default_factory=list)
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class SafetyClassifier:
    """
    Classifies actions and manages approval workflow.

    Rules:
    1. SAFE actions are auto-approved
    2. MODERATE actions are logged and executed
    3. RISKY actions require confirmation (or admin override)
    4. DESTRUCTIVE actions are blocked unless admin explicitly approves
    """

    def __init__(self, config=None):
        """Initialize classifier."""
        self.config = config
        self.pending_approvals: Dict[str, ActionClassification] = {}

        # Keywords that indicate risk
        self.risky_keywords = {
            "delete", "drop", "truncate", "remove", "destroy",
            "restart", "stop", "kill", "terminate",
            "update", "modify", "change", "alter",
            "send", "transfer", "execute", "run",
        }

        # Keywords that indicate destructive actions
        self.destructive_keywords = {
            "drop table", "delete all", "truncate table",
            "rm -rf", "force delete", "wipe", "format",
            "reset --hard", "force push",
        }

        # Protected resources
        self.protected_tables = {
            "qualified_wallets", "user_wallets", "authorized_users",
            "position_lifecycle", "transactions",
        }

        self.protected_services = {
            "database", "main_bot", "webhook_server",
        }

    def classify(self, action: str, params: Dict[str, Any] = None) -> ActionClassification:
        """
        Classify an action into safety levels.

        Args:
            action: Action name or description
            params: Action parameters

        Returns:
            ActionClassification with safety level and approval status
        """
        params = params or {}
        action_lower = action.lower()
        risk_factors = []
        mitigations = []

        # Check for destructive patterns
        for pattern in self.destructive_keywords:
            if pattern in action_lower:
                risk_factors.append(f"Contains destructive keyword: {pattern}")
                return ActionClassification(
                    action=action,
                    safety_level=SafetyLevel.DESTRUCTIVE,
                    approval_status=ApprovalStatus.BLOCKED,
                    reason=f"Action contains destructive pattern: {pattern}",
                    requires_confirmation=True,
                    risk_factors=risk_factors,
                )

        # Check for protected resources
        for table in self.protected_tables:
            if table in action_lower:
                if any(kw in action_lower for kw in ["update", "delete", "insert"]):
                    risk_factors.append(f"Modifies protected table: {table}")

        for service in self.protected_services:
            if service in action_lower:
                if any(kw in action_lower for kw in ["restart", "stop", "kill"]):
                    risk_factors.append(f"Affects protected service: {service}")

        # Check for risky keywords
        risky_matches = [kw for kw in self.risky_keywords if kw in action_lower]
        if risky_matches:
            risk_factors.extend([f"Contains risky keyword: {kw}" for kw in risky_matches[:3]])

        # Classify based on risk factors
        if len(risk_factors) >= 3 or any("protected" in rf for rf in risk_factors):
            safety_level = SafetyLevel.RISKY
            approval_status = ApprovalStatus.PENDING
            requires_confirmation = True
        elif len(risk_factors) >= 1:
            safety_level = SafetyLevel.MODERATE
            approval_status = ApprovalStatus.AUTO_APPROVED
            requires_confirmation = False
            mitigations.append("Action logged for audit")
        else:
            safety_level = SafetyLevel.SAFE
            approval_status = ApprovalStatus.AUTO_APPROVED
            requires_confirmation = False

        # Generate reason
        if risk_factors:
            reason = f"Classified as {safety_level.name} due to: {', '.join(risk_factors[:2])}"
        else:
            reason = "No risk factors detected"

        return ActionClassification(
            action=action,
            safety_level=safety_level,
            approval_status=approval_status,
            reason=reason,
            requires_confirmation=requires_confirmation,
            risk_factors=risk_factors,
            mitigations=mitigations,
        )

    def classify_tool_use(
        self,
        tool_name: str,
        tool_safety: SafetyLevel,
        params: Dict[str, Any]
    ) -> ActionClassification:
        """
        Classify tool usage based on tool safety level and parameters.

        Args:
            tool_name: Name of the tool
            tool_safety: Tool's declared safety level
            params: Tool parameters

        Returns:
            ActionClassification
        """
        risk_factors = []
        mitigations = []

        # Start with tool's declared safety level
        safety_level = tool_safety
        action = f"{tool_name}({', '.join(f'{k}={v}' for k, v in list(params.items())[:3])})"

        # Analyze parameters for additional risk
        param_str = str(params).lower()

        # Check for SQL-like patterns
        if "query" in params or "sql" in param_str:
            sql = params.get("query", "")
            if any(kw in sql.upper() for kw in ["DROP", "DELETE", "TRUNCATE"]):
                safety_level = SafetyLevel.DESTRUCTIVE
                risk_factors.append("SQL contains destructive operation")

        # Check for file path patterns
        for key in ["path", "file", "directory"]:
            if key in params:
                path = str(params[key])
                if any(p in path for p in ["/root", "/etc", "/var", "~/"]):
                    risk_factors.append(f"Accesses sensitive path: {path[:30]}")
                    if safety_level.value < SafetyLevel.RISKY.value:
                        safety_level = SafetyLevel.RISKY

        # Determine approval status
        if safety_level == SafetyLevel.DESTRUCTIVE:
            approval_status = ApprovalStatus.BLOCKED
            requires_confirmation = True
        elif safety_level == SafetyLevel.RISKY:
            approval_status = ApprovalStatus.PENDING
            requires_confirmation = True
        else:
            approval_status = ApprovalStatus.AUTO_APPROVED
            requires_confirmation = False
            mitigations.append("Tool execution logged")

        reason = f"Tool '{tool_name}' safety: {safety_level.name}"
        if risk_factors:
            reason += f" | Risks: {', '.join(risk_factors[:2])}"

        return ActionClassification(
            action=action,
            safety_level=safety_level,
            approval_status=approval_status,
            reason=reason,
            requires_confirmation=requires_confirmation,
            risk_factors=risk_factors,
            mitigations=mitigations,
        )

    def request_approval(self, classification: ActionClassification, request_id: str):
        """
        Request approval for an action.

        Args:
            classification: The action classification
            request_id: Unique ID for this approval request
        """
        self.pending_approvals[request_id] = classification
        logger.info(
            f"Approval requested for '{classification.action}' "
            f"(safety: {classification.safety_level.name}, id: {request_id})"
        )

    def approve(self, request_id: str, approver: str = "admin") -> bool:
        """
        Approve a pending action.

        Args:
            request_id: Approval request ID
            approver: Who approved (default: admin)

        Returns:
            True if approved, False if not found
        """
        if request_id not in self.pending_approvals:
            return False

        classification = self.pending_approvals[request_id]

        # Cannot approve DESTRUCTIVE actions without explicit override
        if classification.safety_level == SafetyLevel.DESTRUCTIVE:
            if approver != "admin_override":
                logger.warning(
                    f"Destructive action '{classification.action}' requires admin_override"
                )
                return False

        classification.approval_status = ApprovalStatus.APPROVED
        classification.approved_by = approver
        classification.approved_at = datetime.now()

        logger.info(
            f"Action '{classification.action}' approved by {approver}"
        )

        return True

    def reject(self, request_id: str, reason: str = "") -> bool:
        """
        Reject a pending action.

        Args:
            request_id: Approval request ID
            reason: Rejection reason

        Returns:
            True if rejected, False if not found
        """
        if request_id not in self.pending_approvals:
            return False

        classification = self.pending_approvals[request_id]
        classification.approval_status = ApprovalStatus.REJECTED
        classification.reason = reason or "Rejected by admin"

        logger.info(
            f"Action '{classification.action}' rejected: {classification.reason}"
        )

        return True

    def get_pending(self, request_id: str) -> Optional[ActionClassification]:
        """Get a pending approval request."""
        return self.pending_approvals.get(request_id)

    def clear_pending(self, request_id: str):
        """Clear a pending approval."""
        self.pending_approvals.pop(request_id, None)

    def get_all_pending(self) -> List[ActionClassification]:
        """Get all pending approvals."""
        return list(self.pending_approvals.values())

    def is_auto_approved(self, classification: ActionClassification) -> bool:
        """Check if action can be auto-approved."""
        return classification.safety_level in [SafetyLevel.SAFE, SafetyLevel.MODERATE]

    def should_block(self, classification: ActionClassification) -> bool:
        """Check if action should be blocked."""
        return (
            classification.safety_level == SafetyLevel.DESTRUCTIVE or
            classification.approval_status == ApprovalStatus.BLOCKED
        )

    def get_safety_summary(self) -> Dict[str, Any]:
        """Get summary of safety status."""
        return {
            "pending_approvals": len(self.pending_approvals),
            "pending_actions": [
                {
                    "action": c.action[:50],
                    "safety": c.safety_level.name,
                    "reason": c.reason[:100],
                }
                for c in self.pending_approvals.values()
            ],
            "protected_tables": list(self.protected_tables),
            "protected_services": list(self.protected_services),
        }


# Singleton instance
_classifier: Optional[SafetyClassifier] = None


def get_safety_classifier() -> SafetyClassifier:
    """Get or create safety classifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = SafetyClassifier()
    return _classifier
