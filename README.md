# REIVRO

REIVRO is being built to verify AI-generated development work, learn from failures, and prevent recurring mistakes from creating rework.

**VERIFY → LEARN → PREVENT**

AI coding agents can generate code, execute tasks, and report completion. Their claims do not always match the actual state of the repository. REIVRO aims to close that gap through evidence-based verification and reusable protections.

## Current MVP — AVAILABLE

The local MVP analyzes public GitHub pull requests and produces summaries grounded in traceable source evidence. It verifies cited excerpts, not arbitrary task completion or overall code correctness. This is the first verification foundation toward the broader Rework Firewall vision.

## Product direction — IN DEVELOPMENT / PLANNED

- **VERIFY (IN DEVELOPMENT):** expand the PR evidence foundation to compare task requirements and agent claims against code, diffs, tests and logs.
- **LEARN (PLANNED):** turn detected failures into reusable project knowledge and developer-approved protections.
- **PREVENT (PLANNED):** apply relevant reviewed safeguards to reduce recurring mistakes and rework.
- **PROTOTYPE:** Regression Test Generator has upstream validation records but no runtime adapter. It is not executable through the current workflow.

The Rework Firewall is a product direction, not an implemented end-to-end guarantee. Cross-agent support and productivity gains have not been demonstrated. The skills catalog remains a technical inventory, not the product's primary promise.

See [product direction and capability boundaries](docs/PRODUCT.md).

## Developer Preview V0.1

Use the [local Developer Preview quickstart](docs/DEVELOPER_PREVIEW.md) for operator-approved task verification and reusable project protections.

## Quick start on Linux or Windows with WSL

1. On Windows, open PowerShell and run `wsl --install -d Ubuntu` if WSL is not installed. Restart if prompted, then launch **Ubuntu**. Run the commands below in Ubuntu (Bash). On Linux, use your regular terminal.
2. Install Git and Python 3.12 in that Linux environment. On Ubuntu 24.04, run `sudo apt update && sudo apt install git python3.12`.
3. Clone and launch from the repository root.

   ```sh
   git clone https://github.com/sovereis/REIVRO.git
   cd REIVRO
   python3.12 -B -m server.scop_web
   ```

4. Keep the terminal open and visit **http://127.0.0.1:8765** in your browser. On WSL, that can be your Windows browser. Try `https://github.com/pallets/flask/pull/5808` and tick the read-only GitHub consent box before generating a summary.

Workflow completion means REIVRO ran its required steps and matched the cited excerpts. Review each claim in context before deciding whether to accept it or request rework.

## Optional local recording

An unrecorded review works immediately. To enable recording and human evaluation, stop REIVRO with Ctrl+C and restart it with a dedicated private directory outside every Git checkout. On WSL, use its Linux filesystem (for example, a path under your WSL home).

```sh
mkdir -m 700 "$HOME/scop-measurements"
python3.12 -B -m server.scop_web --store-dir "$HOME/scop-measurements"
```

Recording and feedback each require explicit consent in the browser. Leave unknown durations blank.

## Troubleshooting

- **Wrong shell or missing Python:** in Windows Terminal, select Ubuntu or run `wsl -d Ubuntu`, then check `python3.12 --version` and `cd` to the checkout.
- **Local origin denied:** open the exact address printed by REIVRO, including `127.0.0.1` and the port. If your Windows browser cannot reach WSL, verify the server is still running and check WSL localhost forwarding. Keep the listener on loopback.
- **Recording disabled:** restart with `--store-dir` or continue without recording.
- **Invalid URL:** use the PR's main page, with a positive PR number and no extra path, query, or fragment.
- **GitHub unavailable:** check connectivity from Linux or WSL, confirm the PR is public, and retry after rate limits reset if applicable. Missing patch evidence can also block a review.

See the [web architecture and developer tests](server/WEB.md).

## Public landing on Vercel

Deploy only the `landing` root directory using its [Vercel setup guide](landing/README.md#deploy-to-vercel-after-approval). The production signup API requires configured Supabase storage and server-only environment variables. Git-triggered deployments are disabled in the configuration. The Workspace continues to run locally through the commands above.
