import os
import time
import httpx
import jwt
import shutil
import subprocess
from github import Github, Auth
from dotenv import load_dotenv

load_dotenv()

# In-memory cache for installation access tokens
# Format: {installation_id: {"token": str, "expires_at": int}}
TOKEN_CACHE = {}

# Base directory to store cloned repositories
BASE_REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "repos")

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
# Load the PEM file contents from an environment variable
GITHUB_PRIVATE_KEY = os.getenv("GITHUB_PRIVATE_KEY").replace("\\n", "\n")
GITHUB_INSTALLATION_ID = os.getenv("GITHUB_INSTALLATION_ID")
GITHUB_OWNER_NAME = os.getenv("GITHUB_OWNER_NAME")

def get_jwt() -> str:
    """Generates a JWT token for the GitHub App."""
    if not GITHUB_APP_ID or not GITHUB_PRIVATE_KEY:
        raise ValueError("GitHub App ID or Private Key not found in environment (GITHUB_APP_ID, GITHUB_PRIVATE_KEY)")

    now = int(time.time())
    payload = {
        "iat": now - 60, # 60 seconds ago to handle clock skew
        "exp": now + (10 * 60), # 10 minutes maximum expiration
        "iss": GITHUB_APP_ID
    }
    
    try:
        encoded_jwt = jwt.encode(payload, GITHUB_PRIVATE_KEY, algorithm="RS256")
        return encoded_jwt
    except Exception as e:
        raise Exception(f"Failed to generate JWT. This is usually due to an incorrectly formatted GITHUB_PRIVATE_KEY in .env. Original error: {str(e)}")

def get_installation_access_token(installation_id: int, app_jwt: str = None) -> str:
    """Retrieves an installation access token using the JWT, with caching."""
    global TOKEN_CACHE
    
    now = int(time.time())
    
    # Check if token exists and is still valid (with a 60s buffer)
    cached_entry = TOKEN_CACHE.get(installation_id)
    if cached_entry and cached_entry["expires_at"] > (now + 60):
        return cached_entry["token"]
        
    if not app_jwt:
        app_jwt = get_jwt()
        
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    
    response = httpx.post(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    
    token = data["token"]
    # GitHub tokens usually last 1 hour. We parse the expires_at from GitHub if available, 
    # or just use a safe window from now. GitHub returns "expires_at": "2024-..."
    # For simplicity and safety, we'll cache it based on the current time + 55 mins.
    TOKEN_CACHE[installation_id] = {
        "token": token,
        "expires_at": now + (55 * 60) 
    }
    
    return token

def find_installation_for_repo(repo_name: str):
    """
    Optimized: Returns the configured owner and installation_id from environment variables.
    Falls back to searching all installations if ENV is missing.
    """
    if GITHUB_INSTALLATION_ID and GITHUB_OWNER_NAME:
        return {
            "installation_id": int(GITHUB_INSTALLATION_ID),
            "owner": GITHUB_OWNER_NAME,
            "repo_name": repo_name
        }

    # Fallback to slower search logic if ENV is missing
    app_jwt = get_jwt()
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # 1. Get all installations
    url = "https://api.github.com/app/installations"
    response = httpx.get(url, headers=headers)
    response.raise_for_status()
    installations = response.json()
    
    for inst in installations:
        inst_id = inst["id"]
        # 2. Reuse the same app_jwt to get installation tokens
        token = get_installation_access_token(inst_id, app_jwt=app_jwt)
        repo_url = "https://api.github.com/installation/repositories"
        repo_response = httpx.get(repo_url, headers={"Authorization": f"token {token}"})
        repos = repo_response.json().get("repositories", [])
        
        # 3. Check if repo matches
        for r in repos:
            if r["name"].lower() == repo_name.lower():
                return {
                    "installation_id": inst_id,
                    "owner": r["owner"]["login"],
                    "repo_name": r["name"]
                }
                
    raise Exception(f"Repository '{repo_name}' not found. Make sure the GitHub App is installed and GITHUB_INSTALLATION_ID is correct if provided.")

def get_github_client(installation_id: int, token: str = None) -> Github:
    """Returns an authenticated PyGithub client for a specific installation."""
    if not token:
        token = get_installation_access_token(installation_id)
    auth = Auth.Token(token)
    return Github(auth=auth)

def clone_repo(installation_id: int, owner: str, repo_name: str, token: str = None):
    """
    Clones a repository into the 'repos' folder. 
    If the folder already exists, it replaces it with a fresh clone.
    """
    if not token:
        token = get_installation_access_token(installation_id)
    clone_url = f"https://x-access-token:{token}@github.com/{owner}/{repo_name}.git"
    
    # Destination structure: repos/owner/repo_name
    dest_path = os.path.join(BASE_REPO_DIR, owner, repo_name)
    
    # If folder exists, remove it
    if os.path.exists(dest_path):
        shutil.rmtree(dest_path)
    
    # Ensure parent directory exists
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    
    result = subprocess.run(["git", "clone", clone_url, dest_path], capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"Failed to clone repository: {result.stderr}")
        
    return {
        "status": "success",
        "message": f"Successfully cloned {owner}/{repo_name}",
        "local_path": dest_path
    }


def _get_github_repo(installation_id: int, owner: str, repo_name: str, token: str = None):
    """Helper to get an authenticated repo object."""
    client = get_github_client(installation_id, token=token)
    return client.get_repo(f"{owner}/{repo_name}")

def create_branch(installation_id: int, owner: str, repo_name: str, base_branch: str, new_branch: str, token: str = None):
    """Creates a new branch off a base branch."""
    repo = _get_github_repo(installation_id, owner, repo_name, token=token)
    base_ref = repo.get_git_ref(f"heads/{base_branch}")
    new_ref_name = f"refs/heads/{new_branch}"
    repo.create_git_ref(ref=new_ref_name, sha=base_ref.object.sha)
    return {"message": f"Branch {new_branch} created from {base_branch}"}

def find_file_in_repo(installation_id: int, owner: str, repo_name: str, file_path: str, ref: str = "main", token: str = None):
    """Finds and retrieves a specific file from the repository."""
    repo = _get_github_repo(installation_id, owner, repo_name, token=token)
    try:
        file_contents = repo.get_contents(file_path, ref=ref)
        if isinstance(file_contents, list):
            return {"error": "Path points to a directory, not a specific file."}
        
        content = file_contents.decoded_content.decode('utf-8')
        return {
            "path": file_contents.path,
            "sha": file_contents.sha,
            "content": content
        }
    except Exception as e:
        return {"error": str(e)}

def commit_file_to_branch(installation_id: int, owner: str, repo_name: str, branch_name: str, file_path: str, content: str, message: str, token: str = None):
    """Creates or updates a file in a specific branch."""
    repo = _get_github_repo(installation_id, owner, repo_name, token=token)
    try:
        file_contents = repo.get_contents(file_path, ref=branch_name)
        sha = file_contents.sha
        repo.update_file(
            path=file_path,
            message=message,
            content=content,
            sha=sha,
            branch=branch_name
        )
        return {"message": f"File {file_path} updated in branch {branch_name}"}
    except Exception:
        # File doesn't exist, create it
        repo.create_file(
            path=file_path,
            message=message,
            content=content,
            branch=branch_name
        )
        return {"message": f"File {file_path} created in branch {branch_name}"}

def get_repo_tree(installation_id: int, owner: str, repo_name: str, ref: str = "main", token: str = None):
    """Returns the recursive file tree of the repository."""
    repo = _get_github_repo(installation_id, owner, repo_name, token=token)
    sha = repo.get_branch(ref).commit.sha
    tree = repo.get_git_tree(sha, recursive=True)
    return {
        "tree": [
            {"path": element.path, "type": element.type, "size": element.size}
            for element in tree.tree
        ]
    }

def create_pull_request(installation_id: int, owner: str, repo_name: str, title: str, body: str, head_branch: str, base_branch: str = "main", token: str = None):
    """Creates a Pull Request from head_branch into base_branch."""
    repo = _get_github_repo(installation_id, owner, repo_name, token=token)
    pr = repo.create_pull(
        title=title,
        body=body,
        head=head_branch,
        base=base_branch
    )
    return {
        "pr_number": pr.number,
        "pr_url": pr.html_url,
        "state": pr.state
    }
