import os
import requests
from typing import Dict, Any

class GitHubConnector:
    """
    Handles interactions with GitHub API to fetch issues and create Pull Requests.
    Required for closed-loop execution.
    """
    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN")
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self.token}" if self.token else ""
        }
        self.base_url = "https://api.github.com"
        
    def fetch_issue(self, repo_full_name: str, issue_number: int) -> Dict[str, Any]:
        """
        Fetches issue details (title, body) from GitHub.
        """
        if not self.token:
            # MVP Mock for offline testing
            return {
                "title": f"Mock Issue #{issue_number}",
                "body": "This is a mocked issue description since GITHUB_TOKEN is not set."
            }
            
        url = f"{self.base_url}/repos/{repo_full_name}/issues/{issue_number}"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "title": data.get("title", ""),
                "body": data.get("body", "")
            }
        else:
            raise Exception(f"Failed to fetch issue {issue_number} from {repo_full_name}. Status: {response.status_code}")

    def create_pull_request(self, repo_full_name: str, title: str, body: str, head_branch: str, base_branch: str = "main", draft: bool = True) -> str:
        """
        Creates a Draft PR on GitHub and returns its URL.
        """
        if not self.token:
            # MVP Mock
            return f"https://github.com/mock/{repo_full_name}/pull/999"
            
        url = f"{self.base_url}/repos/{repo_full_name}/pulls"
        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
            "draft": draft
        }
        
        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 201:
            return response.json().get("html_url", "")
        else:
            raise Exception(f"Failed to create PR. Status: {response.status_code}, Error: {response.text}")

    def get_commit_check_runs(self, repo_full_name: str, ref: str) -> Dict[str, Any]:
        """
        Fetches check runs for a specific commit ref (branch name or commit hash).
        """
        if not self.token:
            # MVP Mock
            return {
                "total_count": 1, 
                "check_runs": [
                    {
                        "name": "mock-ci", 
                        "status": "completed", 
                        "conclusion": "success", 
                        "output": {"summary": "Mock CI passed"}
                    }
                ]
            }
            
        url = f"{self.base_url}/repos/{repo_full_name}/commits/{ref}/check-runs"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to fetch check runs. Status: {response.status_code}, Error: {response.text}")
