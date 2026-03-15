from pydantic import BaseModel, Field
from typing import List, Optional

class JiraCommentRequest(BaseModel):
    comment: str

class JiraCommentResponse(BaseModel):
    id: str
    author: str
    created: str
    body: str

class JiraTransitionRequest(BaseModel):
    transition_id: str

class JiraTransition(BaseModel):
    id: str
    name: str

class JiraTransitionsResponse(BaseModel):
    transitions: List[JiraTransition]

class JiraIssueFields(BaseModel):
    summary: Optional[str] = None
    description: Optional[dict] = None  # ADF format
    status: Optional[dict] = None

    class Config:
        extra = "allow"

class JiraIssue(BaseModel):
    id: str
    key: Optional[str] = None
    fields: Optional[JiraIssueFields] = None

    model_config = {
        "extra": "allow",
        "populate_by_name": True,
        "from_attributes": True
    }

class JiraSearchResponse(BaseModel):
    total: Optional[int] = None
    isLast: Optional[bool] = None
    issues: List[JiraIssue]

    model_config = {
        "populate_by_name": True,
        "from_attributes": True
    }
