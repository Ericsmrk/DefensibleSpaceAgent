# Deploying to `clearsafe.org`

This repo now includes a Flask web app (`web_app.py`) that can be hosted and attached to your custom domain.

## 1) Host the app
Recommended: Render.

- Connect your GitHub repo.
- Create a **Web Service**.
- Build command:
  `pip install -r requirements.txt && pip install gunicorn`
- Start command:
  `gunicorn web_app:app --bind 0.0.0.0:$PORT`
- Health check path:
  `/healthz`

Alternative: use the included `render.yaml` for blueprint deploy.

## 2) Set environment variables
In Render dashboard, add:
- `OPENAI_API_KEY` (optional; enables live LLM calls)
- `GOOGLE_MAPS_KEY` (optional; enables live geocoding)

Without them, app still runs using deterministic fallback logic.


## Key management (important)
- Never commit real keys to GitHub.
- Set `OPENAI_API_KEY` and `GOOGLE_MAPS_KEY` only in your hosting provider environment-variable settings.
- If using GitHub Pages as frontend, keep all key usage on backend only (`/api/assess`), not in browser JS.

## 3) Add custom domain
In Render service settings:
- Add custom domain `clearsafe.org`
- Add custom domain `www.clearsafe.org`

Render will provide DNS targets.

## 4) Configure DNS at your domain registrar
At your DNS provider (where `clearsafe.org` is managed):
- Add record(s) exactly as instructed by Render.
- Typical pattern:
  - `www` -> CNAME to your Render domain
  - apex/root `@` -> A/ALIAS per Render guidance

## 5) Verify TLS + propagation
- Wait for DNS propagation.
- Confirm `https://clearsafe.org/` loads.
- Confirm API endpoint: `https://clearsafe.org/healthz` returns `{ "ok": true }`.

## 6) Smoke test
- Visit homepage and run one assessment.
- Confirm JSON and recommendation render.

## Notes
I cannot directly log into your registrar/hosting account from this environment, but the repo is now prepared so you can complete deployment quickly.
