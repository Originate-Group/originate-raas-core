"""GitHub Integration Service (CR-010: RAAS-COMP-051).

Handles:
- RAAS-FEAT-043: GitHub Repository Configuration
- RAAS-FEAT-044: Work Item to GitHub Issue Sync
- RAAS-FEAT-045: GitHub Webhook Event Handling

Uses Fernet symmetric encryption for credentials storage.
"""
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime
from typing import Optional
from uuid import UUID

import httpx
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from .models import (
    GitHubConfiguration,
    GitHubAuthType,
    WorkItem,
    WorkItemType,
    WorkItemStatus,
)
from .work_item_state_machine import validate_work_item_transition, triggers_cr_merge

logger = logging.getLogger("raas-core.github")

# Environment variable for encryption key
# In production, this should be set securely (e.g., from secrets manager)
ENCRYPTION_KEY_ENV = "RAAS_GITHUB_ENCRYPTION_KEY"


def get_encryption_key() -> bytes:
    """Get or generate the encryption key for GitHub credentials.

    In production, this should be stored securely and rotated periodically.
    """
    key = os.environ.get(ENCRYPTION_KEY_ENV)
    if key:
        return key.encode()

    # For development/testing, generate a key (NOT for production!)
    logger.warning(
        f"No {ENCRYPTION_KEY_ENV} environment variable set. "
        "Using generated key - DO NOT USE IN PRODUCTION!"
    )
    return Fernet.generate_key()


def encrypt_credentials(credentials: str) -> bytes:
    """Encrypt credentials using Fernet symmetric encryption."""
    key = get_encryption_key()
    f = Fernet(key)
    return f.encrypt(credentials.encode())


def decrypt_credentials(encrypted: bytes) -> str:
    """Decrypt credentials."""
    key = get_encryption_key()
    f = Fernet(key)
    return f.decrypt(encrypted).decode()


def generate_webhook_secret() -> str:
    """Generate a secure webhook secret."""
    return secrets.token_hex(32)


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature (HMAC-SHA256).

    GitHub sends signature in format: sha256=<hex digest>
    """
    if not signature.startswith("sha256="):
        return False

    expected_signature = signature[7:]  # Remove "sha256=" prefix
    computed = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed, expected_signature)


class GitHubClient:
    """GitHub API client for RaaS integration."""

    BASE_URL = "https://api.github.com"

    def __init__(self, config: GitHubConfiguration):
        self.config = config
        self._token: Optional[str] = None

    @property
    def token(self) -> str:
        """Get decrypted access token."""
        if not self._token and self.config.encrypted_credentials:
            self._token = decrypt_credentials(self.config.encrypted_credentials)
        return self._token or ""

    @property
    def headers(self) -> dict:
        """Get headers for GitHub API requests."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @property
    def repo_url(self) -> str:
        """Get repository API URL."""
        return f"{self.BASE_URL}/repos/{self.config.repository_owner}/{self.config.repository_name}"

    async def create_issue(
        self,
        work_item: WorkItem,
        affected_requirements: list[str],
    ) -> dict:
        """Create a GitHub Issue for a Work Item.

        Returns the created issue data including number and URL.
        """
        # Build issue title with type prefix
        type_prefix = {
            WorkItemType.CR: "CR",
            WorkItemType.BUG: "BUG",
            WorkItemType.DEBT: "DEBT",
            WorkItemType.RELEASE: "REL",
        }.get(work_item.work_item_type, "WI")

        title = f"[{type_prefix}] {work_item.title}"

        # Build issue body
        body_parts = [
            f"**RaaS Work Item**: `{work_item.human_readable_id}`",
            "",
            work_item.description or "_No description provided._",
            "",
        ]

        if affected_requirements:
            body_parts.extend([
                "## Affected Requirements",
                "",
            ])
            for req in affected_requirements:
                body_parts.append(f"- `{req}`")
            body_parts.append("")

        body_parts.extend([
            "---",
            f"_Synced from RaaS at {datetime.utcnow().isoformat()}Z_",
        ])

        body = "\n".join(body_parts)

        # Get labels from mapping
        label_mapping = self.config.label_mapping or {}
        type_key = work_item.work_item_type.value
        labels = []
        if type_key in label_mapping:
            labels.append(label_mapping[type_key])

        # Priority label
        priority_labels = {
            "critical": "priority:critical",
            "high": "priority:high",
            "medium": "priority:medium",
            "low": "priority:low",
        }
        if work_item.priority in priority_labels:
            labels.append(priority_labels[work_item.priority])

        # Create the issue
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.repo_url}/issues",
                headers=self.headers,
                json={
                    "title": title,
                    "body": body,
                    "labels": labels,
                },
            )

            if response.status_code == 201:
                data = response.json()
                logger.info(
                    f"Created GitHub Issue #{data['number']} for Work Item {work_item.human_readable_id}"
                )
                return data
            else:
                logger.error(
                    f"Failed to create GitHub Issue: {response.status_code} - {response.text}"
                )
                raise Exception(f"GitHub API error: {response.status_code}")

    async def update_issue(
        self,
        issue_number: int,
        state: Optional[str] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
    ) -> dict:
        """Update a GitHub Issue."""
        update_data = {}
        if state:
            update_data["state"] = state
        if title:
            update_data["title"] = title
        if body:
            update_data["body"] = body

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.repo_url}/issues/{issue_number}",
                headers=self.headers,
                json=update_data,
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(
                    f"Failed to update GitHub Issue #{issue_number}: {response.status_code}"
                )
                raise Exception(f"GitHub API error: {response.status_code}")

    async def get_issue(self, issue_number: int) -> dict:
        """Get a GitHub Issue by number."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.repo_url}/issues/{issue_number}",
                headers=self.headers,
            )

            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"GitHub API error: {response.status_code}")

    async def add_issue_comment(self, issue_number: int, comment: str) -> dict:
        """Add a comment to a GitHub Issue."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.repo_url}/issues/{issue_number}/comments",
                headers=self.headers,
                json={"body": comment},
            )

            if response.status_code == 201:
                return response.json()
            else:
                raise Exception(f"GitHub API error: {response.status_code}")

    async def create_webhook(self, webhook_url: str, secret: str) -> dict:
        """Create a webhook on the repository.

        Returns the created webhook data including ID.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.repo_url}/hooks",
                headers=self.headers,
                json={
                    "name": "web",
                    "active": True,
                    "events": ["issues", "pull_request", "release"],
                    "config": {
                        "url": webhook_url,
                        "content_type": "json",
                        "secret": secret,
                        "insecure_ssl": "0",
                    },
                },
            )

            if response.status_code == 201:
                data = response.json()
                logger.info(f"Created GitHub webhook {data['id']} for {self.config.full_repo_name}")
                return data
            else:
                logger.error(
                    f"Failed to create webhook: {response.status_code} - {response.text}"
                )
                raise Exception(f"GitHub API error: {response.status_code}")

    async def delete_webhook(self, webhook_id: str) -> bool:
        """Delete a webhook from the repository."""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.repo_url}/hooks/{webhook_id}",
                headers=self.headers,
            )

            return response.status_code == 204

    async def verify_token(self) -> bool:
        """Verify that the token is valid and has access to the repo."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.repo_url,
                headers=self.headers,
            )
            return response.status_code == 200


class GitHubWebhookHandler:
    """Handler for GitHub webhook events (RAAS-FEAT-045)."""

    def __init__(self, db: Session):
        self.db = db

    def find_work_item_by_issue(
        self,
        issue_number: int,
        repo_owner: str,
        repo_name: str,
    ) -> Optional[WorkItem]:
        """Find a Work Item linked to a GitHub Issue."""
        # Search by implementation_refs containing the issue URL
        expected_url_part = f"/{repo_owner}/{repo_name}/issues/{issue_number}"

        # Query work items and check implementation_refs
        work_items = self.db.query(WorkItem).all()
        for wi in work_items:
            refs = wi.implementation_refs or {}
            issue_url = refs.get("github_issue_url", "")
            if expected_url_part in issue_url:
                return wi

        return None

    async def handle_issue_event(
        self,
        action: str,
        issue: dict,
        repository: dict,
        user_id: Optional[UUID] = None,
    ) -> Optional[dict]:
        """Handle GitHub Issue events.

        Actions: opened, closed, reopened, edited, deleted
        """
        issue_number = issue.get("number")
        repo_owner = repository.get("owner", {}).get("login")
        repo_name = repository.get("name")
        issue_state = issue.get("state")  # open or closed

        work_item = self.find_work_item_by_issue(issue_number, repo_owner, repo_name)
        if not work_item:
            logger.debug(f"No Work Item found for issue #{issue_number}")
            return None

        result = {"work_item_id": str(work_item.id), "action": action}

        if action == "closed" and work_item.status not in [
            WorkItemStatus.IMPLEMENTED,
            WorkItemStatus.VALIDATED,
            WorkItemStatus.DEPLOYED,
            WorkItemStatus.COMPLETED,
            WorkItemStatus.CANCELLED,
        ]:
            # Issue closed -> Work Item implemented
            try:
                validate_work_item_transition(work_item.status, WorkItemStatus.IMPLEMENTED)
                work_item.status = WorkItemStatus.IMPLEMENTED
                work_item.updated_at = datetime.utcnow()
                result["new_status"] = "implemented"
                logger.info(f"Work Item {work_item.human_readable_id} -> implemented (issue closed)")
            except Exception as e:
                logger.warning(f"Could not transition Work Item: {e}")

        elif action == "reopened" and work_item.status == WorkItemStatus.IMPLEMENTED:
            # Issue reopened -> Work Item back to in_progress
            try:
                validate_work_item_transition(work_item.status, WorkItemStatus.IN_PROGRESS)
                work_item.status = WorkItemStatus.IN_PROGRESS
                work_item.updated_at = datetime.utcnow()
                result["new_status"] = "in_progress"
                logger.info(f"Work Item {work_item.human_readable_id} -> in_progress (issue reopened)")
            except Exception as e:
                logger.warning(f"Could not transition Work Item: {e}")

        self.db.commit()
        return result

    async def handle_pull_request_event(
        self,
        action: str,
        pull_request: dict,
        repository: dict,
    ) -> Optional[dict]:
        """Handle GitHub Pull Request events.

        Actions: opened, closed, merged, synchronize
        """
        pr_number = pull_request.get("number")
        pr_url = pull_request.get("html_url")
        pr_merged = pull_request.get("merged", False)
        pr_body = pull_request.get("body", "")

        # Try to find linked Work Item from PR body
        # Look for patterns like "CR-010" or "IR-003"
        import re
        hrid_pattern = r'\b(IR|CR|BUG|WI)-\d{3,}\b'
        matches = re.findall(hrid_pattern, pr_body, re.IGNORECASE)

        if not matches:
            return None

        results = []
        for match in matches:
            work_item = self.db.query(WorkItem).filter(
                WorkItem.human_readable_id.ilike(match)
            ).first()

            if work_item:
                # Store PR URL in implementation_refs
                refs = work_item.implementation_refs or {}
                pr_urls = refs.get("pr_urls", [])
                if pr_url not in pr_urls:
                    pr_urls.append(pr_url)
                refs["pr_urls"] = pr_urls

                if action == "closed" and pr_merged:
                    # Get commit SHA from merge
                    merge_commit_sha = pull_request.get("merge_commit_sha")
                    if merge_commit_sha:
                        commit_shas = refs.get("commit_shas", [])
                        if merge_commit_sha not in commit_shas:
                            commit_shas.append(merge_commit_sha)
                        refs["commit_shas"] = commit_shas

                work_item.implementation_refs = refs
                work_item.updated_at = datetime.utcnow()
                results.append({
                    "work_item_id": str(work_item.id),
                    "work_item_hrid": work_item.human_readable_id,
                    "pr_url": pr_url,
                })

        self.db.commit()
        return {"prs_linked": results} if results else None

    async def handle_release_event(
        self,
        action: str,
        release: dict,
        repository: dict,
        user_id: Optional[UUID] = None,
    ) -> Optional[dict]:
        """Handle GitHub Release events.

        When a release is published, trigger deployment status on Work Items.
        """
        if action != "published":
            return None

        release_tag = release.get("tag_name")
        release_name = release.get("name") or release_tag
        release_body = release.get("body", "")
        repo_owner = repository.get("owner", {}).get("login")
        repo_name = repository.get("name")

        # Find Work Items mentioned in release notes or with merged PRs
        import re
        hrid_pattern = r'\b(IR|CR|BUG|WI)-\d{3,}\b'
        matches = re.findall(hrid_pattern, release_body, re.IGNORECASE)

        results = []
        for match in matches:
            work_item = self.db.query(WorkItem).filter(
                WorkItem.human_readable_id.ilike(match)
            ).first()

            if work_item and work_item.status in [
                WorkItemStatus.IMPLEMENTED,
                WorkItemStatus.VALIDATED,
            ]:
                # Store release tag
                refs = work_item.implementation_refs or {}
                refs["release_tag"] = release_tag

                # Transition to deployed
                try:
                    validate_work_item_transition(work_item.status, WorkItemStatus.DEPLOYED)
                    old_status = work_item.status
                    work_item.status = WorkItemStatus.DEPLOYED
                    work_item.implementation_refs = refs
                    work_item.updated_at = datetime.utcnow()

                    results.append({
                        "work_item_id": str(work_item.id),
                        "work_item_hrid": work_item.human_readable_id,
                        "new_status": "deployed",
                        "release_tag": release_tag,
                    })

                    logger.info(
                        f"Work Item {work_item.human_readable_id} -> deployed (release {release_tag})"
                    )
                except Exception as e:
                    logger.warning(f"Could not transition Work Item to deployed: {e}")

        self.db.commit()
        return {"deployed_items": results} if results else None
