# REIVRO for Claude Code

When the operator asks for a REIVRO submission, use the installed REIVRO CLI from its trusted checkout:

```bash
python3 -m server.scop_agent_integration submit --agent claude-code --project OWNER/REPO --task-id TASK_UUID --event-id EVENT_UUID --pr PR_NUMBER --head-sha GIT_HEAD
```

Use the assigned task ID and the full Git HEAD of the submitted change. Give the JSON to the operator. Treat a separately supplied REIVRO report as feedback on that exact HEAD. Surface the protection ID and a violation when present. Wait for feedback from the operator. Only address a violation after the operator explicitly sends a report with `feedback.decision=correction_authorized` for this task and HEAD. Submit a new event only after an authorized correction. Do not invoke another agent session or retry on your own. Leave approval, revocation, artifact export and credentials to the operator.
