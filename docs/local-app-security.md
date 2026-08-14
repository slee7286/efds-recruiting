# Local app security

The companion binds to `127.0.0.1` by default, validates loopback hosts, and
uses a per-process CSRF token for state-changing form posts. Logs remain local
and do not contain CVs, answers, conversation text, cookies, or tokens. The
local directory is private and should be protected by OS permissions.
