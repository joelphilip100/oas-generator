import os
import time
import httpx
import jwt
import shutil
import tempfile
import zipfile
import uuid
from github import Github, Auth, GithubException
from dotenv import load_dotenv

load_dotenv()

class GitHubService:
    def __init__(self):
        # In-memory cache for installation access tokens
        # Format: {installation_id: {"token": str, "expires_at": int}}
        self._token_cache = {}
        
        # Base directory to store cloned repositories (pointing to root/repos)
        self.base_repo_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
            "repos"
        )

    def _get_jwt(self) -> str:
        """Generates a JWT token for the GitHub App."""
        app_id = os.getenv("GITHUB_APP_ID")
        private_key = os.getenv("GITHUB_PRIVATE_KEY")
        
        if not app_id or not private_key:
            raise ValueError("GitHub App ID or Private Key not found in environment (GITHUB_APP_ID, GITHUB_PRIVATE_KEY)")

        private_key = private_key.replace("\\n", "\n")
        
        now = int(time.time())
        payload = {
            "iat": now - 60,         # 60 seconds ago to handle clock skew
            "exp": now + (10 * 60),  # 10 minutes maximum expiration
            "iss": app_id
        }
        
        try:
            return jwt.encode(payload, private_key, algorithm="RS256")
        except Exception as e:
            raise Exception(f"Failed to generate JWT. Check GITHUB_PRIVATE_KEY format. Error: {str(e)}")

    def get_installation_access_token(self, installation_id: int, app_jwt: str = None) -> str:
        """Retrieves an installation access token using the JWT, with caching."""
        now = int(time.time())
        
        # Check cache
        cached_entry = self._token_cache.get(installation_id)
        if cached_entry and cached_entry["expires_at"] > (now + 60):
            return cached_entry["token"]
            
        if not app_jwt:
            app_jwt = self._get_jwt()
            
        headers = {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github.v3+json"
        }
        url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        
        response = httpx.post(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        token = data["token"]
        # Cache for 55 minutes
        self._token_cache[installation_id] = {
            "token": token,
            "expires_at": now + (55 * 60) 
        }
        
        return token

    def find_installation_for_repo(self, repo_name: str):
        """Optimized lookup from env, falls back to searching app installations."""
        inst_id_env = os.getenv("GITHUB_INSTALLATION_ID")
        owner_env = os.getenv("GITHUB_OWNER_NAME")

        if inst_id_env and owner_env:
            return {
                "installation_id": int(inst_id_env),
                "owner": owner_env,
                "repo_name": repo_name
            }

        app_jwt = self._get_jwt()
        headers = {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Get installations
        url = "https://api.github.com/app/installations"
        response = httpx.get(url, headers=headers)
        response.raise_for_status()
        installations = response.json()
        
        for inst in installations:
            inst_id = inst["id"]
            token = self.get_installation_access_token(inst_id, app_jwt=app_jwt)
            repo_url = "https://api.github.com/installation/repositories"
            repo_response = httpx.get(repo_url, headers={"Authorization": f"token {token}"})
            repos = repo_response.json().get("repositories", [])
            
            for r in repos:
                if r["name"].lower() == repo_name.lower():
                    return {
                        "installation_id": inst_id,
                        "owner": r["owner"]["login"],
                        "repo_name": r["name"]
                    }
                    
        raise Exception(f"Repository '{repo_name}' not found for this GitHub App.")

    def get_github_client(self, installation_id: int, token: str = None) -> Github:
        """Returns an authenticated PyGithub client."""
        if not token:
            token = self.get_installation_access_token(installation_id)
        return Github(auth=Auth.Token(token))

    def _get_repo_object(self, installation_id: int, owner: str, repo_name: str, token: str = None):
        """Helper to get a PyGithub repo object."""
        client = self.get_github_client(installation_id, token=token)
        return client.get_repo(f"{owner}/{repo_name}")

    def clone_repo(self, installation_id: int, owner: str, repo_name: str, token: str = None, ref: str = "main"):
        """Downloads repo archive and extracts into a unique sandbox."""
        if not token:
            token = self.get_installation_access_token(installation_id)
            
        url = f"https://api.github.com/repos/{owner}/{repo_name}/zipball/{ref}"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }

        run_id = str(uuid.uuid4())[:8]
        dest_path = os.path.join(self.base_repo_dir, owner, f"{repo_name}_{run_id}")
        
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        if os.path.exists(dest_path):
            shutil.rmtree(dest_path)
        os.makedirs(dest_path, exist_ok=True)

        with tempfile.NamedTemporaryFile() as tmp_file:
            with httpx.stream("GET", url, headers=headers, follow_redirects=True) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    tmp_file.write(chunk)
            
            tmp_file.seek(0)
            with zipfile.ZipFile(tmp_file) as z:
                top_level_dir = z.namelist()[0].split('/')[0]
                for member in z.infolist():
                    if member.filename == f"{top_level_dir}/":
                        continue
                    relative_path = member.filename[len(top_level_dir)+1:]
                    if not relative_path:
                        continue
                    target_path = os.path.join(dest_path, relative_path)
                    if member.is_dir():
                        os.makedirs(target_path, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        with open(target_path, 'wb') as f:
                            f.write(z.read(member))

        return {
            "status": "success",
            "message": f"Successfully sandboxed {owner}/{repo_name}",
            "local_path": dest_path,
            "run_id": run_id
        }

    def cleanup_repo(self, local_path: str):
        """Removes a sandbox directory."""
        if local_path and os.path.exists(local_path):
            try:
                shutil.rmtree(local_path)
            except Exception as e:
                print(f"Cleanup Error for {local_path}: {e}")
        return {"status": "success"}

    def purge_all_sandboxes(self):
        """Finds and deletes all folders with a unique ID suffix in the repos directory."""
        cleaned = []
        errors = []
        if os.path.exists(self.base_repo_dir):
            for root, dirs, files in os.walk(self.base_repo_dir):
                for d in dirs:
                    if "_" in d and len(d.split("_")[-1]) == 8:
                        full_path = os.path.join(root, d)
                        try:
                            shutil.rmtree(full_path)
                            cleaned.append(full_path)
                        except Exception as e:
                            errors.append(f"Failed to delete {full_path}: {e}")
        
        return {"status": "success", "purged": len(cleaned), "errors": errors}

    def create_branch(self, installation_id: int, owner: str, repo_name: str, base_branch: str, new_branch: str, token: str = None):
        """Creates a new branch off a base branch. If branch exists, returns success."""
        repo = self._get_repo_object(installation_id, owner, repo_name, token=token)
        
        try:
            # Check if it already exists
            repo.get_git_ref(f"heads/{new_branch}")
            return {"message": f"Branch {new_branch} already exists", "status": "existing"}
        except GithubException as e:
            if e.status == 404:
                # Branch doesn't exist, create it
                base_ref = repo.get_git_ref(f"heads/{base_branch}")
                repo.create_git_ref(ref=f"refs/heads/{new_branch}", sha=base_ref.object.sha)
                return {"message": f"Branch {new_branch} created", "status": "created"}
            # If it's some other error (auth, rate limit, etc), re-raise it
            raise e

    def find_file_in_repo(self, installation_id: int, owner: str, repo_name: str, file_path: str, ref: str = "main", token: str = None):
        """Retrieves file content."""
        repo = self._get_repo_object(installation_id, owner, repo_name, token=token)
        try:
            file_contents = repo.get_contents(file_path, ref=ref)
            if isinstance(file_contents, list):
                return {"error": "Path is a directory"}
            return {
                "path": file_contents.path,
                "sha": file_contents.sha,
                "content": file_contents.decoded_content.decode('utf-8')
            }
        except Exception as e:
            return {"error": str(e)}

    def commit_file_to_branch(self, installation_id: int, owner: str, repo_name: str, branch_name: str, file_path: str, content: str, message: str, token: str = None):
        """Creates or updates a file."""
        repo = self._get_repo_object(installation_id, owner, repo_name, token=token)
        try:
            file_contents = repo.get_contents(file_path, ref=branch_name)
            repo.update_file(path=file_path, message=message, content=content, sha=file_contents.sha, branch=branch_name)
            return {"message": f"File {file_path} updated"}
        except Exception:
            repo.create_file(path=file_path, message=message, content=content, branch=branch_name)
            return {"message": f"File {file_path} created"}

    def get_repo_tree(self, installation_id: int, owner: str, repo_name: str, ref: str = "main", token: str = None):
        """Returns recursive file tree."""
        repo = self._get_repo_object(installation_id, owner, repo_name, token=token)
        sha = repo.get_branch(ref).commit.sha
        tree = repo.get_git_tree(sha, recursive=True)
        return {
            "tree": [
                {"path": item.path, "type": item.type, "size": item.size}
                for item in tree.tree
            ]
        }

    def create_pull_request(self, installation_id: int, owner: str, repo_name: str, title: str, body: str, head_branch: str, base_branch: str = "main", token: str = None):
        """Creates a PR. If one already exists for this branch, returns the existing one."""
        repo = self._get_repo_object(installation_id, owner, repo_name, token=token)
        try:
            pr = repo.create_pull(title=title, body=body, head=head_branch, base=base_branch)
            return {"pr_number": pr.number, "pr_url": pr.html_url, "status": "created"}
        except GithubException as e:
            if e.status == 422:
                # Often means PR already exists. Let's try to find it.
                pulls = repo.get_pulls(state='open', head=f"{owner}:{head_branch}", base=base_branch)
                for pr in pulls:
                    return {"pr_number": pr.number, "pr_url": pr.html_url, "status": "existing"}
            raise e

# Singleton instance
github_service = GitHubService()
