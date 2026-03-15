from pydantic import BaseModel

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
