# Security Policy

## Supported versions

Only the latest release receives fixes. Please update to the current
[release](https://github.com/dibi73/ha-bookstack-sync/releases) before
reporting.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report them privately via GitHub's
[private vulnerability reporting](https://github.com/dibi73/ha-bookstack-sync/security/advisories/new)
(repository → **Security** → **Report a vulnerability**). Only the
maintainer can see the report.

Useful details: the affected version, what an attacker could do, and
steps to reproduce. Leave out real tokens, URLs and personal data;
the integration's diagnostics dump already redacts them.

You will get an answer as soon as possible. Once a fix is released,
the advisory is published and credits you, unless you prefer to stay
anonymous.

## Scope

In scope: the code in this repository, in particular how it handles
the BookStack API token, the BookStack URL and the data it writes into
BookStack or the Markdown export.

Out of scope: vulnerabilities in BookStack or Home Assistant
themselves; please report those to the respective projects.
