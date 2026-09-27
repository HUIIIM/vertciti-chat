# AGENTS.md - instructions for AI coding agents working in this repo

Repo: vertciti-chat (HUIIIM, private). Brand: vertciti (lowercase).
Stack: Python backend (FastAPI) + vanilla JS static frontend

## Rules
1. **Never commit secrets.** API keys/tokens/passwords go in env vars or GitHub Secrets only.
   Run `pre-commit run --all-files` (gitleaks) before committing.
2. Conventional commits: `feat|fix|chore|docs|ci|sec: short summary`.
3. Git author email: use the GitHub noreply address of the pusher. **Never invent emails.**
4. Python: type hints on new functions; run `ruff check .` and `pytest -q` before commit.
   New Python files must parse: `python3 -c "import ast; ast.parse(open('f').read())"`.
5. Node: `npm run lint` advisory, `npm run test` and `npm run build` must pass.
6. No third-party code copied into the repo (D148 clean-room: learn ideas, don't copy).
7. Brand hygiene: public-facing names use `vertciti` (lowercase).
8. Docs/decision updates: significant behavior changes also update README and decision-log.

## Commands
- Python tests: `pytest -q` (run from the directory holding requirements.txt)
- Lint: `ruff check .`
- Node tests: `npm run test`; build: `npm run build`; lint: `npm run lint`

## Annotations
Use ASCII `[]` for status tags, e.g. [实证/公开/推断/未确认]. Never use 【】.
