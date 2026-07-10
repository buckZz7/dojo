"""
GitQuest Fork Manager — manages the pool's forks of recognized repos.

Flow:
  1. Pool forks each recognized repo to buckZz7/<repo-name>
  2. Contributor submits code → creates a branch on the fork
  3. Quality gate reviews the branch
  4. If approved → pool opens PR from fork to upstream
  5. If rejected → branch stays on fork, never reaches upstream

Closed/rejected PRs die at the fork. They're invisible to Gittensor validators
and don't affect the pool's credibility ratio.
"""

import subprocess
from dataclasses import dataclass


@dataclass
class ForkInfo:
    fork_url: str
    upstream_url: str
    branch_name: str


def fork_repo(upstream_full_name: str, github_pat: str) -> str:
    """Fork a repo to the pool's GitHub account.

    Returns the fork's full name (e.g. "buckZz7/metagraphed").
    """
    # Use GitHub API to fork
    import requests
    headers = {
        "Authorization": f"token {github_pat}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.post(
        f"https://api.github.com/repos/{upstream_full_name}/forks",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    fork_data = resp.json()
    return fork_data["full_name"]


def create_fork_branch(fork_full_name: str, branch_name: str, github_pat: str) -> bool:
    """Create a new branch on the fork from the default branch."""
    import requests
    headers = {
        "Authorization": f"token {github_pat}",
        "Accept": "application/vnd.github+json",
    }

    # Get default branch
    repo_resp = requests.get(
        f"https://api.github.com/repos/{fork_full_name}",
        headers=headers,
        timeout=15,
    )
    repo_resp.raise_for_status()
    default_branch = repo_resp.json()["default_branch"]

    # Get the SHA of the default branch
    ref_resp = requests.get(
        f"https://api.github.com/repos/{fork_full_name}/git/refs/heads/{default_branch}",
        headers=headers,
        timeout=15,
    )
    ref_resp.raise_for_status()
    sha = ref_resp.json()["object"]["sha"]

    # Create new branch
    create_resp = requests.post(
        f"https://api.github.com/repos/{fork_full_name}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        timeout=15,
    )
    return create_resp.status_code == 201


def open_upstream_pr(
    fork_full_name: str,
    branch_name: str,
    upstream_full_name: str,
    title: str,
    body: str,
    github_pat: str,
) -> dict:
    """Open a PR from the fork to the upstream repo.

    This is the moment the submission becomes visible to Gittensor validators.
    The PR is authored by the pool's GitHub identity (buckZz7).
    """
    import requests
    headers = {
        "Authorization": f"token {github_pat}",
        "Accept": "application/vnd.github+json",
    }

    fork_user = fork_full_name.split("/")[0]
    head = f"{fork_user}:{branch_name}"

    resp = requests.post(
        f"https://api.github.com/repos/{upstream_full_name}/pulls",
        headers=headers,
        json={
            "title": title,
            "body": body,
            "head": head,
            "base": "main",  # or detect default branch
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def check_existing_fork(upstream_full_name: str, pool_username: str, github_pat: str) -> str | None:
    """Check if the pool already has a fork of this repo."""
    import requests
    fork_name = f"{pool_username}/{upstream_full_name.split('/')[-1]}"
    headers = {"Authorization": f"token {github_pat}", "Accept": "application/vnd.github+json"}
    resp = requests.get(f"https://api.github.com/repos/{fork_name}", headers=headers, timeout=15)
    if resp.status_code == 200:
        return fork_name
    return None
