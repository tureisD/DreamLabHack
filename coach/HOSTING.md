# Host DreamCoach with its YAM simulator

The public walkthrough is a separate static site. To let visitors connect their own accounts and run YAM, deploy the full app as a single Docker web service with storage and HTTPS. The gateway validates each Dream Labs key before allocating a workspace. A private cookie selects a separate Python worker and data directory for that browser. Simulator inference and any approved fine-tuning use the visitor’s Dream account. Visitors can optionally enable AI chat with their own OpenAI key.

## Build and verify

Run these commands from the repository root:

```bash
docker build -f coach/Dockerfile -t dreamcoach .
docker run --rm --name dreamcoach -p 127.0.0.1:10000:10000 \
  -e COACH_PUBLIC_ORIGIN=http://127.0.0.1:10000 \
  -e COACH_MAX_ACTIVE_WORKSPACES=1 \
  -v dreamcoach-workspaces:/var/lib/dreamcoach dreamcoach
```

Open `http://127.0.0.1:10000`. Check `/health`, then click **Begin** in the coach conversation and connect a Dream Labs key. Choose **Use 24 bundled demos** to check import and review without starting inference. Verify the base versus fine-tune sidebar with an available checkpoint and a budgeted simulator run.

## Public deployment

- Use the repository root as the Docker build context and `coach/Dockerfile` as the Dockerfile.
- Bind traffic to the container’s `PORT`. Set `COACH_PUBLIC_ORIGIN` to the exact HTTPS origin without a trailing slash. Render provides `RENDER_EXTERNAL_URL` as a default.
- Give the container a persistent volume at `/var/lib/dreamcoach`, writable by UID/GID 10001. Keep one instance per volume. The example `render.yaml` uses a paid web service and disk.
- Keep TLS termination in front of the gateway. Publish its HTTPS URL after checking that two independent browser sessions each see only their own workspace.
- Store no shared Dream Labs or OpenAI key in the deployment environment. The gateway uses visitor keys, and the workers ignore host credentials. The Dream key is saved in the visitor’s workspace with restricted filesystem permissions. Protect the volume and its backups.

Workspace cookies last seven days. The operator should prune expired workspace directories from the protected volume when no jobs are running. The gateway limits saved workspaces and concurrent workers, and stops idle workers while preserving stored results. Increase the worker cap only after measuring simulator memory and CPU on the host. Physical station actions are disabled in hosted mode.
