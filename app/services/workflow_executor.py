import os
import zipfile
from app.services.jira_service import jira_service
from app.services.ai_service import ai_service
from app.services.github_service import github_service

class WorkflowExecutor:
    """
    Orchestrator Service: Manages the end-to-end flow.
    Jira Webhook -> Context Collection -> AI Generation -> GitHub PR.
    """

    async def execute_jira_to_gh_workflow(self, issue_key: str):
        """
        Runs the full pipeline starting from a Jira issue key.
        """
        try:
            print(f"🔄 Workflow: Starting pipeline for {issue_key}...")
            
            # 1. Collect Context from Jira
            issue_context = await self._collect_jira_context(issue_key)
            
            # 2. Trigger AI Generation
            print(f"🚀 Workflow: Triggering AI Generation for {issue_key}...")
            ai_result = await ai_service.generate_oas(issue_context)
            
            # 3. GitHub Workflow
            print(f"🌲 Workflow: Pushing OAS to GitHub for {issue_key}...")
            
            # Configuration (can be moved to .env later for more flexibility)
            repo_name = os.getenv("GITHUB_REPO_NAME", "oas-generator")
            owner = os.getenv("GITHUB_OWNER_NAME", "joelphilip100")
            installation_id = os.getenv("GITHUB_INSTALLATION_ID")
            
            # Setup specific details for this run
            branch_name = f"oas-gen-{issue_key.lower()}"
            file_path = f"schemas/openapi-{issue_key.lower()}.yaml"
            commit_message = f"Add generated OAS for Jira Issue {issue_key}"
            pr_title = f"OAS Generation: {issue_key} - {issue_context['summary']}"
            pr_body = f"Automatic OAS generation triggered by Jira issue [{issue_key}]({os.getenv('JIRA_URL')}/browse/{issue_key}).\n\n**Description:** {issue_context['summary']}"
            
            # Get token
            token = github_service.get_installation_access_token(installation_id)
            
            # Clone and Prepare (Unique Sandbox)
            clone_result = github_service.clone_repo(installation_id, owner, repo_name, token=token)
            local_sandbox = clone_result["local_path"]
            
            try:
                # Create Branch
                github_service.create_branch(installation_id, owner, repo_name, "main", branch_name, token=token)
                
                # Commit OAS file
                github_service.commit_file_to_branch(
                    installation_id, owner, repo_name, branch_name, 
                    file_path, ai_result["raw_text"], commit_message, token=token
                )
                
                # Create Pull Request
                pr_result = github_service.create_pull_request(
                    installation_id, owner, repo_name, pr_title, pr_body, branch_name, "main", token=token
                )
                
                print(f"🎉 Workflow: PR created successfully: {pr_result['pr_url']}")
                ai_result["pr_url"] = pr_result["pr_url"]
                
            finally:
                # Cleanup sandbox
                github_service.cleanup_repo(local_sandbox)
            print(f"🏁 Workflow: Pipeline complete for {issue_key}")
            return ai_result
            
        except Exception as e:
            print(f"❌ Workflow Error for {issue_key}: {e}")
            raise e

    async def _collect_jira_context(self, issue_key: str):
        """Internal helper to fetch and organize all Jira data/files."""
        print(f"📥 Workflow: Collecting Jira data for {issue_key}...")
        
        # Core fields
        fields = "summary,description,attachment,status"
        issue_data = await jira_service.get_issue(issue_key, fields)
        comments = await jira_service.get_comments(issue_key)
        
        # Attachment Management
        # project_root/attachments/KEY
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
                print(f" 💾 Downloading attachment: {filename}...")
                content = await jira_service.download_attachment(content_url)
                with open(local_path, "wb") as f:
                    f.write(content)
                
                # Auto-extract ZIPs
                extracted_path = None
                if filename.lower().endswith(".zip"):
                    extracted_path = os.path.join(attachments_dir, "extracted", filename[:-4])
                    os.makedirs(extracted_path, exist_ok=True)
                    print(f" 📂 Extracting {filename} to {extracted_path}...")
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
                print(f" ⚠️ Failed to download {filename}: {att_err}")
                attachment_list.append({"filename": filename, "status": "failed", "error": str(att_err)})

        return {
            "issue_key": issue_key,
            "summary": issue_data.get("fields", {}).get("summary"),
            "description": jira_service.parse_adf_to_text(issue_data.get("fields", {}).get("description")),
            "status": issue_data.get("fields", {}).get("status", {}).get("name"),
            "comments": comments,
            "attachments": attachment_list
        }

# Singleton instance
workflow_executor = WorkflowExecutor()
