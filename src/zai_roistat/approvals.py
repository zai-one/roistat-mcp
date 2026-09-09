"""Persistent approvals. Acceptance is an explicit local operator CLI operation."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from zai_roistat.policy import PolicyStore


@dataclass(slots=True)
class ApprovalRecord:
    approval_id: UUID
    principal_id: str
    provider: str
    operation: str
    request_hash: str
    estimated_cost: float
    budget_limit: float
    status: str
    expires_at: datetime
    budget_unlimited: bool


class ApprovalStore:
    def __init__(self, policy: PolicyStore):
        self.policy = policy
        with policy.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS approvals(
                    account TEXT NOT NULL, approval_id TEXT NOT NULL, actor TEXT NOT NULL,
                    provider TEXT NOT NULL, operation TEXT NOT NULL, args_hash TEXT NOT NULL,
                    expires REAL NOT NULL, status TEXT NOT NULL,
                    PRIMARY KEY(account, approval_id));
                CREATE TABLE IF NOT EXISTS approval_events(
                    account TEXT NOT NULL, approval_id TEXT NOT NULL, event TEXT NOT NULL,
                    origin TEXT NOT NULL, at REAL NOT NULL);
            """)

    async def create_approval(self, approval: ApprovalRecord) -> None:
        if approval.status != "prepared" or approval.provider != "roistat":
            raise PermissionError("only unaccepted Roistat drafts may be created")
        with self.policy.connect() as db:
            db.execute(
                "INSERT INTO approvals VALUES(?, ?, ?, ?, ?, ?, ?, 'prepared')",
                (
                    self.policy.account,
                    str(approval.approval_id),
                    str(approval.principal_id),
                    approval.provider,
                    approval.operation,
                    approval.request_hash,
                    approval.expires_at.timestamp(),
                ),
            )

    async def get_approval(self, approval_id: UUID) -> ApprovalRecord | None:
        with self.policy.connect() as db:
            row = db.execute(
                "SELECT actor, provider, operation, args_hash, expires, status FROM approvals "
                "WHERE account=? AND approval_id=?",
                (self.policy.account, str(approval_id)),
            ).fetchone()
        if row is None:
            return None
        return ApprovalRecord(
            approval_id,
            row[0],
            row[1],
            row[2],
            row[3],
            0.0,
            0.0,
            row[5],
            datetime.fromtimestamp(row[4], UTC),
            True,
        )

    def accept(self, approval_id: UUID, *, principal: str, request_hash: str) -> bool:
        now = datetime.now(UTC).timestamp()
        with self.policy.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE approvals SET status='accepted' WHERE account=? AND approval_id=? "
                "AND actor=? AND args_hash=? AND status='prepared' AND expires>?",
                (self.policy.account, str(approval_id), principal, request_hash, now),
            ).rowcount
            if changed:
                db.execute(
                    "INSERT INTO approval_events VALUES(?, ?, 'accepted', 'local-operator-cli', ?)",
                    (self.policy.account, str(approval_id), now),
                )
            return changed == 1

    async def consume_approval(self, approval_id: UUID) -> bool:
        now = datetime.now(UTC).timestamp()
        with self.policy.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE approvals SET status='consumed' WHERE account=? AND approval_id=? "
                "AND status='accepted' AND expires>?",
                (self.policy.account, str(approval_id), now),
            ).rowcount
            if changed:
                db.execute(
                    "INSERT INTO approval_events VALUES(?, ?, 'consumed', 'mcp-apply', ?)",
                    (self.policy.account, str(approval_id), now),
                )
            return changed == 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-path", type=Path, required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--approval-id", type=UUID, required=True)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--request-hash", required=True)
    parser.add_argument("--accept", action="store_true", required=True)
    args = parser.parse_args()
    if not args.state_path.is_file():
        parser.exit(2, "existing state file required\n")
    store = ApprovalStore(PolicyStore(args.state_path, args.account, 30, 30))
    accepted = store.accept(args.approval_id, principal=args.principal, request_hash=args.request_hash)
    print(json.dumps({"accepted": accepted, "approval_id": str(args.approval_id)}))
    raise SystemExit(0 if accepted else 1)


if __name__ == "__main__":
    main()
