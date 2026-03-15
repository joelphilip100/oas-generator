from app.services.github_service import github_service
import app.schemas.github_schemas as github_schemas

async def resolve_gh_details(req: github_schemas.GitHubBaseRequest | github_schemas.IntegratedWorkflowRequest):
    """Utility to auto-populate installation_id and owner if missing."""
    if not req.installation_id or not req.owner:
        details = github_service.find_installation_for_repo(req.repo_name)
        req.installation_id = details["installation_id"]
        req.owner = details["owner"]
    return req
