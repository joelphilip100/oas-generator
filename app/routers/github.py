from fastapi import APIRouter, HTTPException
import app.services.github_service as gh_services
import app.schemas.github_schemas as github_schemas
from app.utils.gh_utils import resolve_gh_details

router = APIRouter(prefix="/github", tags=["GitHub"])

@router.get("/lookup/{repo_name}")
def lookup_repo(repo_name: str):
    try:
        return gh_services.find_installation_for_repo(repo_name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/purge-sandboxes")
def purge_sandboxes():
    """Manual trigger to clean up all unique sandbox folders in the repos directory."""
    try:
        return gh_services.purge_all_sandboxes()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/clone")
async def clone_repository(req: github_schemas.CloneRequest, cleanup: bool = False):
    local_path = None
    try:
        await resolve_gh_details(req)
        result = gh_services.clone_repo(req.installation_id, req.owner, req.repo_name)
        local_path = result.get("local_path")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cleanup and local_path:
            gh_services.cleanup_repo(local_path)

@router.post("/branch")
async def create_branch(req: github_schemas.BranchRequest):
    try:
        await resolve_gh_details(req)
        return gh_services.create_branch(req.installation_id, req.owner, req.repo_name, req.base_branch, req.new_branch)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/file")
async def get_file(req: github_schemas.FileRequest):
    try:
        await resolve_gh_details(req)
        result = gh_services.find_file_in_repo(req.installation_id, req.owner, req.repo_name, req.file_path, req.ref)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/commit")
async def commit_file(req: github_schemas.CommitRequest):
    try:
        await resolve_gh_details(req)
        return gh_services.commit_file_to_branch(
            req.installation_id, req.owner, req.repo_name, req.branch_name, req.file_path, req.content, req.message
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/pr")
async def create_pr(req: github_schemas.PullRequestRequest):
    try:
        await resolve_gh_details(req)
        return gh_services.create_pull_request(
            req.installation_id, req.owner, req.repo_name, req.title, req.body, req.head_branch, req.base_branch
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/tree")
async def get_tree(req: github_schemas.FileRequest):
    try:
        await resolve_gh_details(req)
        return gh_services.get_repo_tree(req.installation_id, req.owner, req.repo_name, req.ref)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/integrated-workflow")
async def integrated_workflow(req: github_schemas.IntegratedWorkflowRequest):
    local_path = None
    try:
        await resolve_gh_details(req)

        # 1. Fetch token ONCE at the start of the workflow
        token = gh_services.get_installation_access_token(req.installation_id)

        # 2. Clone Repo (Creates a unique sandbox)
        clone_result = gh_services.clone_repo(req.installation_id, req.owner, req.repo_name, token=token)
        local_path = clone_result["local_path"]

        # 3. Create Branch
        gh_services.create_branch(
            req.installation_id, req.owner, req.repo_name, req.base_branch, req.branch_name, token=token
        )

        # 4. Commit Changes
        gh_services.commit_file_to_branch(
            req.installation_id,
            req.owner,
            req.repo_name,
            req.branch_name,
            req.file_path,
            req.new_content,
            req.commit_message,
            token=token
        )

        # 5. Create PR
        pr_result = gh_services.create_pull_request(
            req.installation_id,
            req.owner,
            req.repo_name,
            req.pr_title,
            req.pr_body,
            req.branch_name,
            req.base_branch,
            token=token
        )

        return {
            "status": "success",
            "message": "Workflow completed successfully",
            "pr": pr_result
        }
    except Exception as e:
        print(f"Workflow Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if local_path:
            print(f"Cleaning up sandbox: {local_path}")
            gh_services.cleanup_repo(local_path)
