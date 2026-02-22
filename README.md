# Defensible Space Agent

Structured multi-LLM + tools prototype for wildfire defensible-space assessment.

## Domain
**Other Instructor-Approved Domain**: Wildfire Defensible-Space Assessment Agent.

## What it demonstrates
- Multiple LLM calls: planner, generator, validator, reporter.
- Tool use: geocoding + NDVI computation + fuel classification.
- Explicit validation rules for plan/tool args/coordinates.
- Structured JSON intermediate outputs.

## Quickstart (CLI)
```bash
python demo.py
```

## Quickstart (Web UI)
```bash
pip install -r requirements.txt
python web_app.py
```
Open: `http://localhost:8000`

## Optional environment variables for live APIs
- `OPENAI_API_KEY` for ChatGPT calls.
- `GOOGLE_MAPS_KEY` for Google geocoding.

Without keys, the project runs in deterministic mock mode for instructor reproducibility.

## Deploy to your domain (e.g., clearsafe.org)
1. Push this repo to GitHub.
2. Create a web service on Render (or Railway/Fly) using:
   - build command: `pip install -r requirements.txt && pip install gunicorn`
   - start command: `gunicorn web_app:app --bind 0.0.0.0:$PORT`
3. Set environment variables in host dashboard (`OPENAI_API_KEY`, `GOOGLE_MAPS_KEY`).
4. In your DNS provider, add:
   - `A`/`ALIAS` record for `@` pointing to host target
   - `CNAME` for `www` pointing to your host URL
5. Attach custom domain in hosting dashboard and enable TLS.

See `docs/deploy_clearsafe_org.md` for step-by-step details.

## Project structure
- `src/agent.py` orchestration pipeline
- `src/llm_client.py` ChatGPT API client
- `src/tools.py` geocoding + NDVI + classification tools
- `src/validators.py` safety/constraint checks
- `src/prompts.py` prompt templates
- `web_app.py` simple website + JSON API
- `tests/` validator and orchestration checks

## Security
- Do not commit API keys.
- Use environment variables only.
