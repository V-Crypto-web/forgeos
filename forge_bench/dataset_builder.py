import json
import requests
import os
import argparse

def fetch_issues(repo, labels, state="open", limit=20):
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    
    import time
    issues = []
    page = 1
    while len(issues) < limit:
        params = {
            "state": state,
            "labels": labels,
            "per_page": 100,
            "page": page
        }
        
        # Add retry loop
        retries = 3
        resp = None
        for r in range(retries):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=15)
                if resp.status_code == 200:
                    break
                elif resp.status_code == 403:
                    print(f"Rate limited or forbidden on {repo}. Waiting 10s...")
                    time.sleep(10)
                else:
                    print(f"Failed to fetch {repo}: {resp.status_code}. Retrying...")
                    time.sleep(2)
            except requests.exceptions.Timeout:
                print(f"Timeout on {repo} page {page}. Retrying...")
                time.sleep(2)
            except Exception as e:
                print(f"Error fetching {repo}: {e}")
                time.sleep(2)
                
        if not resp or resp.status_code != 200:
            print(f"Failed to fetch {repo} after retries.")
            break
            
        data = resp.json()
        if not data:
            break
            
        for issue in data:
            if "pull_request" not in issue: # Only issues, not PRs
                issues.append(issue)
                if len(issues) >= limit:
                    break
        page += 1
    return issues

def main():
    repos = {
        "psf/requests": {"name": "requests", "labels": "bug"},
        "encode/starlette": {"name": "starlette", "labels": "bug"},
        "marshmallow-code/marshmallow": {"name": "marshmallow", "labels": "bug"},
        "pallets/flask": {"name": "flask", "labels": "bug"},
        "pallets/click": {"name": "click", "labels": "bug"}
    }
    
    dataset = []
    base_id = 1000
    
    for repo_full, info in repos.items():
        print(f"Fetching issues for {repo_full}...")
        issues = fetch_issues(repo_full, info["labels"], limit=10)
        for i in issues:
            desc = i.get("body") or ""
            # Clean up long descriptions
            if len(desc) > 1000:
                desc = desc[:1000] + "... [truncated]"
            
            dataset.append({
                "id": base_id,
                "repo_name": info["name"],
                "repo_url": f"https://github.com/{repo_full}",
                "category": "Bug Fix",
                "title": i.get("title", ""),
                "description": desc,
                "github_url": i.get("html_url", ""),
                "original_issue_number": i.get("number")
            })
            base_id += 1
            
    with open("forge_bench/taxonomy_tasks.json", "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=4)
    print(f"Generated forge_bench/taxonomy_tasks.json with {len(dataset)} tasks.")

if __name__ == "__main__":
    main()
