import os
import httpx
import base64
from dotenv import load_dotenv

load_dotenv()

class JiraService:
    def __init__(self):
        self.base_url = os.getenv("JIRA_URL")
        self.email = os.getenv("JIRA_EMAIL")
        self.api_token = os.getenv("JIRA_API_TOKEN")
        
        if not all([self.base_url, self.email, self.api_token]):
            # We don't raise here to allow the app to start, but methods will check
            pass

    def _get_headers(self):
        """Generates basic auth headers for Jira Cloud API."""
        # Always fetch from environment to get the latest values
        email = os.getenv("JIRA_EMAIL")
        api_token = os.getenv("JIRA_API_TOKEN")

        if not email or not api_token:
            raise ValueError("JIRA_EMAIL and JIRA_API_TOKEN must be set in .env")
        
        auth_string = f"{email}:{api_token}"
        base64_auth = base64.b64encode(auth_string.encode()).decode()
        
        return {
            "Authorization": f"Basic {base64_auth}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    async def _make_request(self, method: str, path: str, params: dict = None, json_data: dict = None):
        """Internal helper to make authenticated async requests to Jira."""
        base_url = os.getenv("JIRA_URL")
        if not base_url:
            raise ValueError("JIRA_URL is not set in .env")
            
        # Ensure path starts with / and base_url does NOT end with / to avoid double slash
        base = base_url.rstrip("/")
        if not path.startswith("/"):
            path = f"/{path}"
            
        url = f"{base}{path}"
        headers = self._get_headers()
        
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.request(method, url, headers=headers, params=params, json=json_data)
            
            # If we still get a 404/403, we return a clearer error for the user
            if response.status_code in [403, 404]:
                raise Exception(f"Jira permission/existence error: {response.text}")
                
            response.raise_for_status()
            if response.status_code == 204:
                return {"status": "success"}
            return response.json()

    async def get_issue(self, issue_key: str, fields: str = None):
        """Fetches details for a specific Jira issue."""
        params = {"fields": fields} if fields else {}
        return await self._make_request("GET", f"/rest/api/3/issue/{issue_key}", params=params)

    async def search_issues(self, jql: str):
        """Searches for Jira issues using JQL."""
        data = await self._make_request("GET", "/rest/api/3/search/jql", params={"jql": jql})
        
        # Ensure 'total' is set (fallback to issues count if missing)
        if "total" not in data and "issues" in data:
            data["total"] = len(data["issues"])
        return data

    async def get_transitions(self, issue_key: str):
        """Fetches available transitions for an issue."""
        return await self._make_request("GET", f"/rest/api/3/issue/{issue_key}/transitions")

    async def do_transition(self, issue_key: str, transition_id: str):
        """Performs a transition (status change) on an issue."""
        payload = {"transition": {"id": transition_id}}
        return await self._make_request("POST", f"/rest/api/3/issue/{issue_key}/transitions", json_data=payload)

    async def update_issue(self, issue_key: str, update_data: dict):
        """Updates issue fields (e.g. summary, description)."""
        # Jira expect data inside a "fields" block for most updates
        payload = {"fields": update_data}
        return await self._make_request("PUT", f"/rest/api/3/issue/{issue_key}", json_data=payload)

    async def add_comment(self, issue_key: str, comment_text: str):
        """Adds a multi-line comment using Atlassian Document Format."""
        lines = comment_text.split('\n')
        content_blocks = [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line if line.strip() else " "}]
            }
            for line in lines
        ]

        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": content_blocks
            }
        }
        return await self._make_request("POST", f"/rest/api/3/issue/{issue_key}/comment", json_data=payload)

    def parse_adf_to_text(self, adf_body: dict) -> str:
        """Converts Atlassian Document Format (ADF) back into plain text."""
        if not adf_body or "content" not in adf_body:
            return ""
        
        lines = []
        for block in adf_body.get("content", []):
            if block.get("type") == "paragraph":
                paragraph_text = "".join(
                    item.get("text", "") 
                    for item in block.get("content", []) 
                    if item.get("type") == "text"
                )
                lines.append(paragraph_text)
        return "\n".join(lines)

    async def get_comments(self, issue_key: str):
        """Retrieves and parses all comments for an issue."""
        data = await self._make_request("GET", f"/rest/api/3/issue/{issue_key}/comment")
        
        return [
            {
                "id": c.get("id"),
                "author": c.get("author", {}).get("displayName"),
                "created": c.get("created"),
                "body": self.parse_adf_to_text(c.get("body"))
            }
            for c in data.get("comments", [])
        ]

    async def download_attachment(self, url: str) -> bytes:
        """Downloads the binary content of an attachment."""
        headers = self._get_headers()
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.content


# Singleton instance for easy import
jira_service = JiraService()
