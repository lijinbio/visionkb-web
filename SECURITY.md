# Security policy

## Reporting

Please report vulnerabilities privately through
[GitHub security advisories](https://github.com/lijinbio/visionkb-web/security/advisories/new), not in public
issues. Include the version (image digest), what you observed and how to reproduce it. You should get an answer
within a few working days.

## Scope

Of particular interest: any path by which a user's Claude API key is logged, stored, echoed, sent anywhere but
Anthropic, or exposed to the MCP child; access-code or session bypass; reaching visionkb-api paths outside the
allowlist (for example `/proposals`) or with methods other than GET; script execution from model output, entity
data or URLs despite the CSP and sanitiser.

## Supported versions

Only the latest release receives fixes.

## Operators

- Serve over HTTPS in any shared deployment (the cookie is then `Secure` and HSTS is sent).
- Keep `web_secret`, `web_access_codes` and the API token in files with mode 600; rotate access codes by editing the
  file and restarting.
- The access log records client address, request line and status only. Do not add header logging in front of the app
  (reverse proxies): `X-Anthropic-Key` must not be logged.
