# Security policy

Please report credential exposure or paid-submission bypasses privately to the
repository owner before opening a public issue.

Never commit API keys, OAuth client secrets, cookies, voice samples, private
source material or release receipts containing account data. Use environment
variables or a secret manager. If a credential is committed, revoke it first;
deleting the file from the latest commit is not sufficient.

The engine treats generation and publication as side-effecting operations.
Install, init, doctor, tests and preflight must never POST, spend credits or
publish. Provider submission must record an intent before the request and must
not retry an ambiguous response automatically.
