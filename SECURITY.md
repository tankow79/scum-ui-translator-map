# Security policy

## Scope

The application only reads the game's text log (`SCUM.log`) and draws an external overlay. It does **not**
inject code, read game memory or hook game APIs.

## Updates

Updates are downloaded over HTTPS from this repository's GitHub Releases, validated (size, executable header and
SHA-256 digest when available) and installed by swapping the application's own `.exe`. The previous build is kept
as `<name>.exe.old` until the next start.

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/tankow79/scum-ui-translator-map/security/advisories/new).
You will get a response as soon as possible.
