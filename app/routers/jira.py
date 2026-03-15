import os
import zipfile
import shutil
from typing import List
from fastapi import APIRouter, status, Request, HTTPException, BackgroundTasks
from app.services.jira_service import jira_service
from app.services.ai_service import ai_service
from app.schemas.jira_schemas import (
    JiraCommentRequest, 
    JiraCommentResponse, 
    JiraTransitionsResponse, 
    JiraSearchResponse,
    JiraIssue,
    JiraTransitionRequest
)

router = APIRouter(prefix="/jira", tags=["Jira"])

async def fetch_issue_details_task(issue_key: str):
    """
    Background task to fetch comprehensive issue context and trigger AI generation.
    Collects summary, description, attachments, and comments.
    """
    try:
        print(f"Starting background context collection for {issue_key}...")
        
        # 1. Fetch Issue Core Details (Summary, Description, Attachments)
        fields = "summary,description,attachment,status"
        issue_data = await jira_service.get_issue(issue_key, fields)
        
        # 2. Fetch All Comments
        comments = await jira_service.get_comments(issue_key)
        
        # 3. Handle Attachments (Metadata + Downloading + Extraction)
        attachments_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
            "attachments", 
            issue_key
        )
        os.makedirs(attachments_dir, exist_ok=True)
        
        attachment_list = []
        for att in issue_data.get("fields", {}).get("attachment", []):
            filename = att.get("filename")
            content_url = att.get("content")
            local_path = os.path.join(attachments_dir, filename)
            
            try:
                print(f"Downloading attachment: {filename}...")
                content = await jira_service.download_attachment(content_url)
                with open(local_path, "wb") as f:
                    f.write(content)
                
                # Auto-extract if it's a zip file
                extracted_path = None
                if filename.lower().endswith(".zip"):
                    extracted_path = os.path.join(attachments_dir, "extracted", filename[:-4])
                    os.makedirs(extracted_path, exist_ok=True)
                    print(f"Extracting {filename} to {extracted_path}...")
                    with zipfile.ZipFile(local_path, 'r') as zip_ref:
                        zip_ref.extractall(extracted_path)
                
                attachment_list.append({
                    "filename": filename,
                    "local_path": local_path,
                    "extracted_to": extracted_path,
                    "mime_type": att.get("mimeType"),
                    "status": "downloaded"
                })
            except Exception as att_err:
                print(f"Failed to download {filename}: {att_err}")
                attachment_list.append({
                    "filename": filename,
                    "status": "failed",
                    "error": str(att_err)
                })

        # 4. Structure the data for AI context
        issue_context = {
            "issue_key": issue_key,
            "summary": issue_data.get("fields", {}).get("summary"),
            "description": jira_service.parse_adf_to_text(issue_data.get("fields", {}).get("description")),
            "status": issue_data.get("fields", {}).get("status", {}).get("name"),
            "comments": comments,
            "attachments": attachment_list
        }
        
        print(f"Successfully collected context for {issue_key}")
        
        # 5. Trigger AI Generation
        print(f"🚀 Triggering AI Generation for {issue_key}...")
        ai_result = await ai_service.generate_oas(issue_context)
        
        print(f"🏁 Final Result for {issue_key}: {ai_result['status']}")
        return ai_result
        
    except Exception as e:
        print(f"Error in background task for {issue_key}: {e}")

@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def jira_webhook(payload: Request, background_tasks: BackgroundTasks):
    """Webhook listener for Jira events."""
    data = await payload.json()
    issue_key = data.get("issue", {}).get("key")
    
    if issue_key:
        print(f"Webhook received for {issue_key}. Dispatching background task...")
        background_tasks.add_task(fetch_issue_details_task, issue_key)
    
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
