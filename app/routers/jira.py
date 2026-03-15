from fastapi import APIRouter, status, Request, HTTPException
from app.services.jira_service import jira_service
from app.schemas.jira_schemas import (
    JiraCommentRequest, 
    JiraCommentResponse, 
    JiraTransitionsResponse, 
    JiraSearchResponse,
    JiraIssue,
    JiraTransitionRequest
)
from typing import List

router = APIRouter(prefix="/jira", tags=["Jira"])

@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def jira_webhook(payload: Request):
    """Webhook listener for Jira events."""
    data = await payload.json()
    issue_key = data.get("issue", {}).get("key")
    summary = data.get("issue", {}).get("fields", {}).get("summary")
    
    print(f"Webhook received for {issue_key}: {summary}")
    return {"status": "accepted"}

@router.get("/issue/{issue_key}", response_model=JiraIssue, response_model_exclude_none=True)
async def get_jira_issue(issue_key: str, fields: str = None):
    """Fetch structured issue details from Jira."""
    try:
        return await jira_service.get_issue(issue_key, fields)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/search", response_model=JiraSearchResponse, response_model_exclude_none=True)
async def search_jira_issues(jql: str):
    """Search for issues using JQL."""
    try:
        return await jira_service.search_issues(jql)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/issue/{issue_key}/transitions", response_model=JiraTransitionsResponse)
async def get_issue_transitions(issue_key: str):
    """List available workflow transitions for an issue."""
    try:
        return await jira_service.get_transitions(issue_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/issue/{issue_key}/transitions")
async def perform_issue_transition(issue_key: str, req: JiraTransitionRequest):
    """Move an issue to a new status."""
    try:
        return await jira_service.do_transition(issue_key, req.transition_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/issue/{issue_key}")
async def update_jira_issue(issue_key: str, update_data: dict):
    """Update issue fields in Jira (e.g. {'summary': 'New Title'})."""
    try:
        return await jira_service.update_issue(issue_key, update_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/issue/{issue_key}/comment", response_model=List[JiraCommentResponse])
async def get_issue_comments(issue_key: str):
    """Retrieve all comments for a specific issue."""
    try:
        return await jira_service.get_comments(issue_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/issue/{issue_key}/comment")
async def add_issue_comment(issue_key: str, req: JiraCommentRequest):
    """Post a new comment to a Jira issue."""
    try:
        return await jira_service.add_comment(issue_key, req.comment)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
