"""Who is asking, and what that implies for SQL and for the cache key.

The trap this module exists to close: caching keyed on the query, row-level
security applied per user. Both correct alone; together, one user's rows served
to another. The fix is that the *policy fingerprint* — not the user id — is part
of every cache key. Users with identical access then share cache entries, which
is where the efficiency comes from; users with different access cannot collide.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Identity:
    subject: str
    roles: tuple[str, ...] = ()
    # SQL fragments ANDed into every scan. In production these are Snowflake
    # row access policies and the compiler only needs to know they apply; here
    # the compiler injects them so the local stack behaves the same way.
    row_predicates: tuple[str, ...] = ()
    # None means "every metric in the model".
    allowed_metrics: frozenset[str] | None = None

    def may_read(self, metric: str) -> bool:
        return self.allowed_metrics is None or metric in self.allowed_metrics

    def fingerprint(self) -> str:
        """Hash of the *policy*, deliberately not of the subject."""
        payload = {
            "roles": sorted(self.roles),
            "row_predicates": sorted(self.row_predicates),
            "allowed_metrics": sorted(self.allowed_metrics)
            if self.allowed_metrics is not None
            else None,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


# Development identities. Real deployments resolve these from the IdP and the
# warehouse's own policy catalogue; the shape is what matters here.
ANALYST = Identity(subject="analyst@example.com", roles=("analyst",))

EMEA_ANALYST = Identity(
    subject="emea.analyst@example.com",
    roles=("analyst", "emea"),
    row_predicates=("region IN ('EMEA')",),
)

RESTRICTED = Identity(
    subject="contractor@example.com",
    roles=("contractor",),
    row_predicates=("region IN ('EMEA')",),
    allowed_metrics=frozenset({"exception.count", "severity.signed_z"}),
)

DEV_IDENTITIES: dict[str, Identity] = {
    "analyst": ANALYST,
    "emea": EMEA_ANALYST,
    "restricted": RESTRICTED,
}


def resolve(name: str | None) -> Identity:
    if not name:
        return ANALYST
    return DEV_IDENTITIES.get(name, ANALYST)
