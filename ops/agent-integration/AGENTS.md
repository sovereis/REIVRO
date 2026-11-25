# REIVRO for Codex

When the operator asks for a REIVRO submission, use the installed REIVRO CLI from its trusted checkout:

```bash
python3 -m server.scop_agent_integration submit --agent codex --project OWNER/REPO --task-id TASK_UUID --event-id EVENT_UUID --pr PR_NUMBER --head-sha GIT_HEAD
```

Use the assigned task ID and the full Git HEAD of the submitted change. Give the JSON to the operator. Treat a separately supplied REIVRO report as feedback on that exact HEAD. Surface the protection ID and a violation when present. Wait for authorization before editing to address a finding. Leave approval, revocation, artifact export and credentials to the operator.
