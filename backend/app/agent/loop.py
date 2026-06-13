from dataclasses import dataclass, field

import httpx
import logging
import google.generativeai as genai  # type: ignore

from app.models.enums import PRSeverity
from app.agent.prompts import SYSTEM_PROMPT
from app.core.config import settings

logger = logging.getLogger(__name__)


MAX_ITERATIONS = 10
MAX_RETRIES = 1

@dataclass
class AgentResult:
    summary: str
    risk_score: int
    issues: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    iterations: int = 0


async def _fetch_pr_diff(repo_full_name: str, pr_number: int, github_token: str) -> dict:
    """Fetch the first 20 changed files for a pull request from GitHub."""

    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params={"per_page": 20})
    except httpx.HTTPError as exc:
        return {"error": f"GitHub API request failed: {exc}"}

    if response.status_code != 200:
        return {"error": f"GitHub API error: {response.status_code}", "details": response.text}

    files = response.json()
    if not isinstance(files, list):
        return {"error": "Unexpected GitHub API response format"}

    return {
        "files_changed": len(files),
        "files": [
            {
                "filename": file_data.get("filename"),
                "status": file_data.get("status"),
                "additions": file_data.get("additions", 0),
                "deletions": file_data.get("deletions", 0),
                "changes": file_data.get("changes", 0),
                "patch": file_data.get("patch", ""),
            }
            for file_data in files[:20]
        ],
    }


def _calculate_risk_score(
    lines_added: int,
    lines_removed: int,
    files_changed: int,
    has_db_migrations: bool,
    touches_auth_files: bool,
    touches_api_contracts: bool,
    test_files_ratio: float,
) -> dict:
    """
    Deterministic risk score
    Returns a score 0-100 and a risk level label (LOW / MEDIUM / HIGH).
    Breakdown:
      Size Impact       — max 30 pts  (churn + file count)
      Architectural     — max 55 pts  (migrations, auth, API contracts)
      Test Penalty      — max 15 pts  (penalises missing test coverage)
    """

    # 1.Size Impact (Max 30 points)
    total_churn = lines_added + lines_removed
    churn_score = min(total_churn // 50, 15)        # 1 point per 50 lines changed
    files_score = min(files_changed * 2, 15)        # 2 points per file changed
    size_impact  = churn_score + files_score

    # 2. Architectural Impact (Max 55 points)
    critical_impact = 0
    if has_db_migrations:
        critical_impact += 25                      
    if touches_auth_files:
        critical_impact += 20                      
    if touches_api_contracts:
        critical_impact += 10                   

    # 3. Safety Net Modifier (Max 15 points)
    test_penalty = 0
    if test_files_ratio < 0.1:              
        test_penalty = 15
    elif test_files_ratio < 0.25:           
        test_penalty = 5

    # 4. Aggregate and Normalise to 0-100
    raw_score = size_impact + critical_impact + test_penalty
    score = max(0, min(int(raw_score), 100))

    if score >= 80:
        risk_level = PRSeverity.CRITICAL
    elif score >= 60:
        risk_level = PRSeverity.HIGH
    elif score >= 30:
        risk_level = PRSeverity.MEDIUM
    else:
        risk_level = PRSeverity.LOW

    return {"risk_score": score, "risk_level": risk_level.value}


async def _post_pr_comment(
        repo_full_name: str,
        pr_number: int,
        summary: str,
        risk_score: int,
        risk_level: str,
        issues: list[dict],
        github_token: str
) -> dict:
    url = f"https://api.github.com/repos/{repo_full_name}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    body_md = "## DevPulse AI Review\n\n"
    body_md += f"**Risk Score:** {risk_score}/100 ({risk_level.upper()})\n\n"
    body_md += f"**Summary:**\n{summary}\n\n"
    body_md += f"### Issues Found ({len(issues)})\n"

    if not issues:
        body_md += "No issues found\n"
    else:
        for issue in issues:
            severity  = issue.get("severity", "info").upper()
            file_name = issue.get("file", "unknown file")
            desc      = issue.get("description", "")
            sugg      = issue.get("suggestion", "")
            body_md  += f"- **[{severity}]** `{file_name}`: {desc}\n"
            if sugg:
                body_md += f"  - *Suggestion:* {sugg}\n"

    payload = {
        "body": body_md
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        return {"error": f"GitHub API request failed: {exc}"}

    if response.status_code != 201:
        return {"error": f"GitHub API error: {response.status_code}", "details": response.text}

    return {"success": True, "comment_url": response.json().get("html_url")}

ASYNC_TOOLS = {
    "fetch_pr_diff": _fetch_pr_diff,
    "post_pr_comment": _post_pr_comment,
}

SYNC_TOOLS = {
    "calculate_risk_score": _calculate_risk_score,
}

async def execute_tool(tool_name: str, github_token: str, args: dict) -> dict:
    try:
        if tool_name in ASYNC_TOOLS:
            result = await ASYNC_TOOLS[tool_name](**args, github_token=github_token)  # type: ignore
        elif tool_name in SYNC_TOOLS:
            result = SYNC_TOOLS[tool_name](**args)  # type: ignore
        else:
            return {
                "tool_executed": False,
                "error": {
                    "type": "invalid_tool_name",
                    "message": f"Unknown tool: {tool_name}",
                },
            }

        return {"tool_executed": True, "result": result}

    except Exception as e:
        return {
            "tool_executed": False,
            "error": {
                "type": "tool_execution_error",
                "message": str(e),
            },
        }

    

# ── Tool Schemas (teaches Gemini what tools exist and how to call them) ──────

TOOLS = [
    genai.protos.Tool(
        function_declarations=[

            # ── Tool 1: fetch_pr_diff ──────────────────────────────────────────
            genai.protos.FunctionDeclaration(
                name="fetch_pr_diff",
                description=(
                    "Fetches the complete list of changed files and their diff patches for a GitHub "
                    "Pull Request. The result contains each file's filename, status "
                    "(added/modified/deleted), lines added, lines removed, and the raw patch text "
                    "showing exactly what changed. Analyse the patch text carefully — it is the "
                    "primary source of truth for your entire review. "

                    "WHEN TO CALL: Always call this tool FIRST, before any other tool. "
                    "You cannot review code you have not seen. "

                    "WHEN NOT TO CALL: Never call this tool more than once per task. "
                    "Do not call it again after you have already received the diff. "
                    "Do not call it after calculate_risk_score or post_pr_comment. "

                    "DO: Read the 'patch' field of each file carefully. The patch uses unified diff "
                    "format — lines starting with '+' were added, lines starting with '-' were removed. "
                    "Use this to understand what the developer actually changed before forming any opinion. "

                    "DO NOT: Skip this tool and guess what the PR contains based on the title alone. "
                    "Example of what NOT to do: PR title is 'Fix login bug' — do NOT assume the bug "
                    "is fixed or what was changed without reading the actual diff first."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "repo_full_name": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description=(
                                "The GitHub repository in exact 'owner/repo' format, e.g. "
                                "'harkamal/devpulse'. Extract this directly from the task data "
                                "you received at the start. Do not guess or modify it."
                            ),
                        ),
                        "pr_number": genai.protos.Schema(
                            type=genai.protos.Type.INTEGER,
                            description=(
                                "The pull request number (e.g. 42). This is the short number "
                                "displayed in the GitHub UI as '#42', NOT the long internal "
                                "GitHub PR ID. Extract it directly from the task data."
                            ),
                        ),
                    },
                    required=["repo_full_name", "pr_number"],
                ),
            ),

            # ── Tool 2: calculate_risk_score ───────────────────────────────────
            genai.protos.FunctionDeclaration(
                name="calculate_risk_score",
                description=(
                    "Calculates a deterministic deployment risk score (0–100) based on the "
                    "characteristics of the Pull Request. The score is computed from three factors: "
                    "size of the change, architectural sensitivity of the files touched, and test "
                    "coverage ratio. The result returns both a numeric 'risk_score' integer and a "
                    "'risk_level' string ('low', 'medium', 'high', or 'critical'). "

                    "WHEN TO CALL: Call this AFTER you have fetched and fully read the diff. "
                    "You need the diff data to correctly compute the boolean flags and file counts. "

                    "WHEN NOT TO CALL: Do NOT call this before fetch_pr_diff — you will not have "
                    "the data needed to fill the parameters accurately. "
                    "Do NOT call this more than once — the score is deterministic and calling it "
                    "twice wastes a round trip and produces the same result. "
                    "Do NOT call this after post_pr_comment — the review is already posted. "

                    "DO: Sum the 'additions' and 'deletions' fields from every file in the diff "
                    "to get lines_added and lines_removed. Carefully inspect every filename to "
                    "determine the boolean flags. Example: if 'alembic/versions/001_add_users.py' "
                    "is in the diff, set has_db_migrations=True. "

                    "DO NOT: Estimate or guess the line counts. Do not set has_db_migrations=True "
                    "just because the PR title mentions 'database'. You must verify by looking at "
                    "the actual filenames in the diff result. "
                    "DO NOT pass the result object itself — extract 'risk_score' and 'risk_level' "
                    "and pass those exact values unchanged to post_pr_comment."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "lines_added": genai.protos.Schema(
                            type=genai.protos.Type.INTEGER,
                            description=(
                                "Total number of lines added across ALL files in this PR. "
                                "Calculate this by summing the 'additions' field from every "
                                "file object returned by fetch_pr_diff."
                            ),
                        ),
                        "lines_removed": genai.protos.Schema(
                            type=genai.protos.Type.INTEGER,
                            description=(
                                "Total number of lines removed across ALL files in this PR. "
                                "Calculate this by summing the 'deletions' field from every "
                                "file object returned by fetch_pr_diff."
                            ),
                        ),
                        "files_changed": genai.protos.Schema(
                            type=genai.protos.Type.INTEGER,
                            description=(
                                "Total count of files modified in this PR. Use the "
                                "'files_changed' integer returned directly by fetch_pr_diff."
                            ),
                        ),
                        "has_db_migrations": genai.protos.Schema(
                            type=genai.protos.Type.BOOLEAN,
                            description=(
                                "Set to true if ANY changed file path contains keywords "
                                "strongly associated with database schema changes: 'migrations/', "
                                "'alembic/', 'flyway/', or if the filename ends in '.sql'. "
                                "These changes carry high risk of data loss or deployment downtime "
                                "and must be flagged even if the code looks simple."
                            ),
                        ),
                        "touches_auth_files": genai.protos.Schema(
                            type=genai.protos.Type.BOOLEAN,
                            description=(
                                "Set to true if ANY changed file path contains keywords related "
                                "to authentication or authorisation: 'auth', 'security', 'login', "
                                "'logout', 'token', 'password', 'oauth', 'jwt', 'session', "
                                "'permission', or 'middleware'. Even a small bug in these files "
                                "can create critical security vulnerabilities."
                            ),
                        ),
                        "touches_api_contracts": genai.protos.Schema(
                            type=genai.protos.Type.BOOLEAN,
                            description=(
                                "Set to true if ANY changed file path contains keywords that "
                                "indicate public API surface changes: 'router', 'routes', "
                                "'api/', 'endpoints/', 'schemas/', 'serializers/', or if the "
                                "file defines Pydantic models or TypeScript interfaces consumed "
                                "by external clients. Changes here may silently break API clients."
                            ),
                        ),
                        "test_files_ratio": genai.protos.Schema(
                            type=genai.protos.Type.NUMBER,
                            description=(
                                "A float between 0.0 and 1.0 representing the proportion of "
                                "changed files that are test files. Calculate as: "
                                "(count of test files) / (total files_changed). "
                                "A file is a test file if its path contains 'test_', '_test', "
                                "'/tests/', or '/spec/'. If there are zero test files, pass 0.0. "
                                "A low ratio penalises the risk score, reflecting that untested "
                                "changes are inherently riskier to deploy."
                            ),
                        ),
                    },
                    required=[
                        "lines_added",
                        "lines_removed",
                        "files_changed",
                        "has_db_migrations",
                        "touches_auth_files",
                        "touches_api_contracts",
                        "test_files_ratio",
                    ],
                ),
            ),

            # ── Tool 3: post_pr_comment ────────────────────────────────────────
            genai.protos.FunctionDeclaration(
                name="post_pr_comment",
                description=(
                    "Posts the final structured review as a Markdown comment directly on the "
                    "GitHub Pull Request. This is the only output the developer will ever see — "
                    "it is your entire deliverable. "

                    "WHEN TO CALL: Call this LAST and only ONCE, after both fetch_pr_diff and "
                    "calculate_risk_score have successfully completed. "

                    "WHEN NOT TO CALL: Do NOT call this before fetch_pr_diff — you have not "
                    "read the code yet and have nothing real to report. "
                    "Do NOT call this before calculate_risk_score — you will not have the "
                    "risk_score and risk_level values to pass. "
                    "Do NOT call this more than once — calling it twice posts a duplicate "
                    "comment on the PR, which makes DevPulse look broken. "
                    "Do NOT call this if fetch_pr_diff returned an error — report the failure "
                    "cleanly instead of posting a meaningless review. "

                    "DO: Be specific. Quote exact filenames from the diff. Reference actual variable "
                    "or function names from the patch. Provide suggestions a developer can act on "
                    "immediately. Write the summary as a senior engineer would — concise, direct, "
                    "and grounded in what you actually read. "
                    "Good summary example: 'This PR adds the OAuth callback handler in auth/oauth.py. "
                    "The token exchange logic is correct, but access tokens are logged in plaintext "
                    "on line 58, which is a critical security issue. No tests were added.' "

                    "DO NOT: Pad the review with generic advice like 'consider adding error handling' "
                    "unless you saw a specific place in the diff where it is missing. "
                    "Do not restate the PR title as the summary. "
                    "Do not invent issues that do not appear in the diff. "
                    "Bad summary example: 'This PR makes changes to the codebase. Overall the code "
                    "looks okay but could be improved.' — this is useless to the developer."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "repo_full_name": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description=(
                                "The same 'owner/repo' string used in fetch_pr_diff. "
                                "Copy it exactly — do not modify."
                            ),
                        ),
                        "pr_number": genai.protos.Schema(
                            type=genai.protos.Type.INTEGER,
                            description=(
                                "The same PR number used in fetch_pr_diff. "
                                "Copy it exactly — do not modify."
                            ),
                        ),
                        "summary": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description=(
                                "A 2–4 sentence plain English overview of your assessment. "
                                "Lead with the most important finding. Mention specific file "
                                "names. Example: 'This PR adds the OAuth login flow across "
                                "3 files. The core logic in auth/oauth.py looks sound, but the "
                                "token is stored in localStorage which is vulnerable to XSS. "
                                "No tests were added for the new endpoints.' "
                                "Do NOT just restate the PR title. Write like a senior engineer."
                            ),
                        ),
                        "risk_score": genai.protos.Schema(
                            type=genai.protos.Type.INTEGER,
                            description=(
                                "The integer 'risk_score' value returned by calculate_risk_score. "
                                "Copy this value exactly. Do NOT re-calculate or adjust it."
                            ),
                        ),
                        "risk_level": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description=(
                                "The string 'risk_level' value returned by calculate_risk_score "
                                "(one of: 'low', 'medium', 'high', 'critical'). "
                                "Copy this value exactly. Do NOT re-calculate or adjust it."
                            ),
                        ),
                        "issues": genai.protos.Schema(
                            type=genai.protos.Type.ARRAY,
                            description=(
                                "A list of specific, actionable findings discovered in the diff. "
                                "Only include real issues found in the actual code — never "
                                "hallucinate problems. If the code is clean, pass an empty list []. "
                                "Order issues from most severe to least severe."
                            ),
                            items=genai.protos.Schema(
                                type=genai.protos.Type.OBJECT,
                                properties={
                                    "severity": genai.protos.Schema(
                                        type=genai.protos.Type.STRING,
                                        description=(
                                            "How critical this issue is. Must be exactly one of: "
                                            "'critical' (security hole, data loss, crash), "
                                            "'high' (significant bug, likely to fail in production), "
                                            "'medium' (code smell, bad practice, partial risk), "
                                            "'low' (minor improvement, readability), "
                                            "'info' (observation, not a problem)."
                                        ),
                                    ),
                                    "file": genai.protos.Schema(
                                        type=genai.protos.Type.STRING,
                                        description=(
                                            "The exact filename from the diff where this issue "
                                            "was found, e.g. 'backend/app/api/auth.py'. "
                                            "Copy it verbatim from the fetch_pr_diff result."
                                        ),
                                    ),
                                    "description": genai.protos.Schema(
                                        type=genai.protos.Type.STRING,
                                        description=(
                                            "A specific description of the problem. Reference the "
                                            "actual code — quote variable names, function names, "
                                            "or line snippets. Bad: 'Error handling is missing.' "
                                            "Good: 'The call to db.commit() on line 42 has no "
                                            "try/except, so a database error will return a 500 "
                                            "with no useful message to the client.'"
                                        ),
                                    ),
                                    "suggestion": genai.protos.Schema(
                                        type=genai.protos.Type.STRING,
                                        description=(
                                            "A concrete, specific fix for the described problem. "
                                            "Provide a code snippet or a clear action if possible. "
                                            "Bad: 'Add error handling.' "
                                            "Good: 'Wrap db.commit() in a try/except SQLAlchemyError "
                                            "block and return a 422 with a structured error body.'"
                                        ),
                                    ),
                                },
                            ),
                        ),
                    },
                    required=[
                        "repo_full_name",
                        "pr_number",
                        "summary",
                        "risk_score",
                        "risk_level",
                        "issues",
                    ],
                ),
            ),
        ]
    )
]


async def run_agent(github_token: str , pr_data: dict)->AgentResult:
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT,
        tools=TOOLS
    )

    chat = model.start_chat()
    repo_full_name = pr_data.get("repo_full_name")
    pr_number = pr_data.get("pr_number")
    initial_prompt = f"Review PR #{pr_number} for repository {repo_full_name}."
    
    # first message
    response = await chat.send_message_async(initial_prompt)

    iterations = 0
    retries    = 0
    while iterations < MAX_ITERATIONS:
        iterations += 1
        
        if not response.parts or not response.parts[0].function_call:
            if retries >= MAX_RETRIES:
                break
            retries += 1
            error_msg = (
                "SYSTEM ERROR: You responded with plain text instead of a tool call. "
                "You MUST use a function call to proceed. Please call `fetch_pr_diff`, "
                "`calculate_risk_score`, or `post_pr_comment`."
            )
            logger.warning("Model ignored tools, sending correction: %s", response.text)
            response = await chat.send_message_async(error_msg)
            continue
        
        function_call = response.parts[0].function_call
        tool_name = function_call.name
        tool_args = dict(function_call.args)
        logger.info("Model wants to run: %s with %s", tool_name, tool_args)
        tool_result = await execute_tool(tool_name, github_token, tool_args)
        if tool_name == "post_pr_comment":
            # The AI is done
            return AgentResult(
                summary=tool_args.get("summary", ""),
                risk_score=tool_args.get("risk_score", 0),
                issues=tool_args.get("issues", []),
                iterations=iterations
            )
        
        tool_response_part = {
            "function_response": {
                "name": tool_name,
                "response": {"result": tool_result}
            }
        }
        response = await chat.send_message_async(tool_response_part)
        
    return AgentResult(
        summary="Failed: AI Agent exceeded maximum tool calls",
        risk_score=0,
        issues=[]
    )
