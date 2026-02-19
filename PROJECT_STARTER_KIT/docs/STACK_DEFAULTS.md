# Stack Defaults (Use Only If Needed)

This is the default full stack used in recent projects. Treat each block as optional based on project scope.

## Default full stack
- App build: React + Vite + TypeScript
- IDE/workflow: VS Code + Codex
- Version control: GitHub
- App hosting: Render
- Automation server: n8n (hosted on Render or equivalent)
- Database/auth/storage: Supabase
- Operational docs: Notion

## Optional selection rules
- If no database needs: skip Supabase.
- If no automations/webhooks needs: skip n8n.
- If static-only app: keep Render app hosting only.
- If no structured documentation needs: Notion can be optional.

## Environment handover practice
- Never commit `.env.local`.
- Keep `ENV_PRODUCTION_HANDOVER.txt` in secure handover package if needed.
- Share sensitive tokens via secure channel, not in public repos.
