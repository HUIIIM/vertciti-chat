# Contributing

Thanks for your interest in contributing. This is primarily a company-built
repository, but well-scoped contributions are welcome.

## Ground rules

1. **Never commit secrets.** No API keys, tokens, passwords, or private keys —
   in code, config, tests, or history. The gitleaks check runs on every push.
2. **Use a valid commit email** (your GitHub noreply or account email).
3. **Conventional commits**: `feat:`, `fix:`, `docs:`, `ci:`, `chore:`, `refactor:`.
4. **Tests are the gate**: run the project's test suite before pushing
   (`pytest -q` for Python, `npm test` for Node). Lint is advisory; tests must pass.
5. **One concern per PR**; keep diffs reviewable.

## Workflow

1. Fork, or branch from `main`.
2. Make your change with tests.
3. Open a PR using the template; describe *what*, *why*, and *how tested*.

## AI-assisted contributions

AI-generated code is welcome, but the human author is responsible for
reviewing it: correctness, license compatibility of any adapted snippets
(see clean-room rule: learn ideas, never copy code), and no leaked secrets.
