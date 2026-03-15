from fastapi import APIRouter, status, Request

router = APIRouter(tags=["Jira"])

@router.post("/jira-webhook", status_code=status.HTTP_202_ACCEPTED)
async def jira_webhook(payload: Request):
    data = await payload.json()
    print(data)
    issue_key = data.get("issue", {}).get("key")
    summary = data.get("issue", {}).get("fields", {}).get("summary")

    print(issue_key)
    print(summary)
    
    return {"status": "accepted"}
