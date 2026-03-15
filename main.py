from fastapi import FastAPI, status, Request, HTTPException
from pydantic import BaseModel
import github_service as gh_services

app = FastAPI()

# Models
class GitHubBaseRequest(BaseModel):
    repo_name: str
    installation_id: int | None = None
    owner: str | None = None

class CloneRequest(GitHubBaseRequest):
    pass

class BranchRequest(GitHubBaseRequest):
    base_branch: str
    new_branch: str

class FileRequest(GitHubBaseRequest):
    file_path: str
    ref: str = "main"

class CommitRequest(GitHubBaseRequest):
    branch_name: str
    file_path: str
    content: str
    message: str

class PullRequestRequest(GitHubBaseRequest):
    title: str
    body: str
    head_branch: str
    base_branch: str = "main"

class IntegratedWorkflowRequest(BaseModel):
    repo_name: str
    file_path: str
    new_content: str
    commit_message: str
    branch_name: str
    pr_title: str
    pr_body: str
    base_branch: str = "main"
    installation_id: int | None = None
    owner: str | None = None

class IntegratedWorkflowRequest(BaseModel):
    repo_name: str
    file_path: str
    new_content: str
    commit_message: str
    branch_name: str
    pr_title: str
    pr_body: str
    base_branch: str = "main"
    installation_id: int | None = None
    owner: str | None = None

@app.get("/")
def main():
    return {"message": "Hello World"}

@app.post("/jira-webhook", status_code=status.HTTP_202_ACCEPTED)
async def jira_webhook(payload: Request):
    data = await payload.json()
    print(data)
    issue_key = data.get("issue", {}).get("key")
    summary = data.get("issue", {}).get("fields", {}).get("summary")

    print(issue_key)
    print(summary)
    
    return {"status": "accepted"}

# --- Utility Functions ---

async def resolve_gh_details(req: GitHubBaseRequest | IntegratedWorkflowRequest):
    """Utility to auto-populate installation_id and owner if missing."""
    if not req.installation_id or not req.owner:
        details = gh_services.find_installation_for_repo(req.repo_name)
        req.installation_id = details["installation_id"]
        req.owner = details["owner"]
    return req

# --- GitHub endpoints ---

@app.get("/github/lookup/{repo_name}")
def lookup_repo(repo_name: str):
    try:
        return gh_services.find_installation_for_repo(repo_name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/github/clone")
async def clone_repository(req: CloneRequest):
    try:
        await resolve_gh_details(req)
        return gh_services.clone_repo(req.installation_id, req.owner, req.repo_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/github/branch")
async def create_branch(req: BranchRequest):
    try:
        await resolve_gh_details(req)
        return gh_services.create_branch(req.installation_id, req.owner, req.repo_name, req.base_branch, req.new_branch)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/github/file")
async def get_file(req: FileRequest):
    try:
        await resolve_gh_details(req)
        result = gh_services.find_file_in_repo(req.installation_id, req.owner, req.repo_name, req.file_path, req.ref)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/github/commit")
async def commit_file(req: CommitRequest):
    try:
        await resolve_gh_details(req)
        return gh_services.commit_file_to_branch(
            req.installation_id, req.owner, req.repo_name, req.branch_name, req.file_path, req.content, req.message
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/github/pr")
async def create_pr(req: PullRequestRequest):
    try:
        await resolve_gh_details(req)
        return gh_services.create_pull_request(
            req.installation_id, req.owner, req.repo_name, req.title, req.body, req.head_branch, req.base_branch
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/github/tree")
async def get_tree(req: FileRequest):
    try:
        await resolve_gh_details(req)
        return gh_services.get_repo_tree(req.installation_id, req.owner, req.repo_name, req.ref)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/github/integrated-workflow")
async def integrated_workflow(req: IntegratedWorkflowRequest):
    try:
        await resolve_gh_details(req)

        # 2. Clone Repo
        gh_services.clone_repo(req.installation_id, req.owner, req.repo_name)

        # 3. Create Branch
        gh_services.create_branch(
            req.installation_id, req.owner, req.repo_name, req.base_branch, req.branch_name
        )

        # 4. Commit Changes
        gh_services.commit_file_to_branch(
            req.installation_id,
            req.owner,
            req.repo_name,
            req.branch_name,
            req.file_path,
            req.new_content,
            req.commit_message
        )

        # 5. Create PR
        pr_result = gh_services.create_pull_request(
            req.installation_id,
            req.owner,
            req.repo_name,
            req.pr_title,
            req.pr_body,
            req.branch_name,
            req.base_branch
        )

        return {
            "status": "success",
            "message": "Workflow completed successfully",
            "pr": pr_result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
