# Security Policy

## Secrets

Do not commit:

- `.env`
- API keys
- private keys
- wallet seed phrases
- `.pem` files
- local SQLite databases
- generated logs or reports

Use `.env.example` as the public template and keep real credentials local.

## Live Trading

The public configuration is intended for paper trading and local experimentation.

Before enabling any live execution path, review:

- provider permissions
- withdrawal/trading scopes
- position sizing
- kill switches
- fee and slippage assumptions
- local machine security

## Reporting Issues

If you notice a security issue in this experimental project, open a private channel with the repository owner instead of publishing secrets or exploit details in an issue.
