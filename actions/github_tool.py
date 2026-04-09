# actions/github_tool.py
# GitHub repository management via PyGithub or REST API.
# Requires: pip install PyGithub
# API token stored in config/api_keys.json as "github_token"

import logging  # migrated from print()
import json
import sys
from pathlib import Path

try:
    from github import Github
    _PYGITHUB_OK = True
except ImportError:
    _PYGITHUB_OK = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def _get_github_token() -> str | None:
    """Get GitHub token from config."""
    try:
        from core.api_key_manager import get_api_keys
        keys = get_api_keys()
        return keys.get("github_token")
    except Exception:
        pass
    try:
        cfg = BASE_DIR / "config" / "api_keys.json"
        if cfg.exists():
            with open(cfg, encoding="utf-8") as f:
                return json.load(f).get("github_token")
    except Exception:
        pass
    return None


def _get_client() -> Github | None:
    token = _get_github_token()
    if not token:
        return None
    try:
        return Github(token)
    except Exception as e:
        logging.getLogger("GitHub").info(f"Client creation failed: {e}")
        return None


def _handle_list_repos(params: dict, player) -> str:
    """List the user's repositories."""
    client = _get_client()
    if not client:
        return (
            "GitHub token not configured. Please add your GitHub personal access token "
            "to config/api_keys.json as 'github_token', sir."
        )

    try:
        user = client.get_user()
        repos = user.get_repos(sort="updated", direction="desc")
        lines = ["Your repositories:"]
        count = 0
        for repo in repos:
            if count >= 20:
                lines.append(f"... and {repo.totalCount - 20} more")
                break
            lang = f" [{repo.language}]" if repo.language else ""
            lines.append(f"  - {repo.full_name}{lang} (stars: {repo.stargazers_count})")
            count += 1
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list repositories, sir: {e}"


def _handle_create_issue(params: dict, player) -> str:
    """Create a GitHub issue on a repository."""
    client = _get_client()
    if not client:
        return "GitHub token not configured, sir."

    repo_name = params.get("repo", "").strip()
    title     = params.get("title", "").strip()
    body      = params.get("body", "").strip()
    labels    = params.get("labels", [])

    if not repo_name or not title:
        return "Please specify both 'repo' (owner/repo) and 'title' for the issue, sir."

    try:
        repo = client.get_repo(repo_name)
        issue = repo.create_issue(title=title, body=body, labels=labels)
        return f"Issue created: #{issue.number} -- '{issue.title}' in {repo_name}, sir."
    except Exception as e:
        return f"Failed to create issue, sir: {e}"


def _handle_list_issues(params: dict, player) -> str:
    """List open issues on a repository."""
    client = _get_client()
    if not client:
        return "GitHub token not configured, sir."

    repo_name = params.get("repo", "").strip()
    state     = params.get("state", "open")
    if not repo_name:
        return "Please specify the 'repo' (owner/repo) to list issues, sir."

    try:
        repo   = client.get_repo(repo_name)
        issues = repo.get_issues(state=state, sort="updated", direction="desc")
        lines  = [f"Open issues in {repo_name}:"]
        count  = 0
        for issue in issues:
            if issue.pull_request:
                continue  # skip PRs
            if count >= 15:
                lines.append("... and more")
                break
            labels = f" [{', '.join(l.name for l in issue.labels[:2])}]" if issue.labels else ""
            lines.append(f"  #{issue.number}: {issue.title}{labels}")
            count += 1
        if count == 0:
            return f"No open issues in {repo_name}, sir."
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list issues, sir: {e}"


def _handle_get_commits(params: dict, player) -> str:
    """Get recent commits from a repository."""
    client = _get_client()
    if not client:
        return "GitHub token not configured, sir."

    repo_name = params.get("repo", "").strip()
    count     = min(int(params.get("count", 10)), 30)
    branch    = params.get("branch", "main")

    if not repo_name:
        return "Please specify the 'repo' (owner/repo), sir."

    try:
        repo    = client.get_repo(repo_name)
        commits = repo.get_commits(sha=branch)
        lines   = [f"Recent commits in {repo_name} ({branch}):"]
        for i, commit in enumerate(commits[:count]):
            msg  = commit.commit.message.split("\n")[0][:72]
            date = commit.commit.author.date.strftime("%Y-%m-%d")
            author = commit.commit.author.name[:20]
            lines.append(f"  {date} {author}: {msg}")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to get commits, sir: {e}"


def _handle_repo_stats(params: dict, player) -> str:
    """Get repository statistics."""
    client = _get_client()
    if not client:
        return "GitHub token not configured, sir."

    repo_name = params.get("repo", "").strip()
    if not repo_name:
        return "Please specify the 'repo' (owner/repo), sir."

    try:
        repo = client.get_repo(repo_name)
        lines = [
            f"Repository: {repo.full_name}",
            f"Description: {repo.description or 'None'}",
            f"Stars: {repo.stargazers_count}",
            f"Forks: {repo.forks_count}",
            f"Language: {repo.language or 'None'}",
            f"Open Issues: {repo.open_issues_count}",
            f"License: {repo.license.name if repo.license else 'None'}",
            f"Last push: {repo.pushed_at.strftime('%Y-%m-%d %H:%M') if repo.pushed_at else 'Unknown'}",
            f"URL: {repo.html_url}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to get repo stats, sir: {e}"


_GITHUB_ACTIONS = {
    "list_repos":  _handle_list_repos,
    "create_issue": _handle_create_issue,
    "list_issues": _handle_list_issues,
    "get_commits": _handle_get_commits,
    "repo_stats":  _handle_repo_stats,
}


def github_tool(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """
    GitHub repository management.

    parameters:
        action   : list_repos | create_issue | list_issues | get_commits | repo_stats
        repo     : owner/repo format (e.g. "FatihMakes/Mark-XXXV")
        title    : Issue title (for create_issue)
        body     : Issue body (for create_issue)
        labels   : List of label names (for create_issue)
        count    : Number of results (default: 10)
        branch   : Branch name (default: main)
        state    : open | closed (for list_issues, default: open)
    """
    if not _PYGITHUB_OK:
        return (
            "PyGithub is not installed. Run: pip install PyGithub "
            "Then add your GitHub personal access token to config/api_keys.json "
            "as 'github_token', sir."
        )

    params  = parameters or {}
    action  = params.get("action", "list_repos").lower().strip()

    if player:
        player.write_log(f"[GitHub] Action: {action}")

    logging.getLogger("GitHub").info('Action: {action}  Params: {params}')

    handler = _GITHUB_ACTIONS.get(action)
    if handler is None:
        return (
            f"Unknown GitHub action: '{action}'. "
            "Available: list_repos, create_issue, list_issues, get_commits, repo_stats."
        )

    try:
        return handler(params, player)
    except Exception as e:
        logging.getLogger("GitHub").info('Error in {action}: {e}')
        return f"GitHub {action} failed, sir: {e}"
