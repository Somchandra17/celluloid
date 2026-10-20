# Security

Do not post pairing tokens, credentials or private footage in public issues.
Use the repository's private vulnerability reporting facility when enabled.
If it is unavailable, ask the maintainer for a private reporting channel without
publishing exploit details or sensitive data in that request.

The companion is a loopback service, not a public office automation endpoint.
Keep its HTTP and UNO ports on localhost. Its token authorizes document creation
and cell updates; restarting invalidates a generated token. A user's explicitly
configured fixed token must be protected like a local credential.

The optional FFmpeg API is a local prototype. Its resource limits are not a
substitute for authentication, tenant isolation, quotas and sandboxed workers
on an Internet-facing service. Browser cancellation may leave a bounded backend
conversion finishing until its timeout.

ODS exports contain inspectable Basic macros. Permit only documents you trust
under your own macro policy. CLI `--save` snapshots contain no animation code.
The application does not bundle LibreOffice or FFmpeg binaries; keep installed
decoders and office software updated.
