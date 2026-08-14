# Refresh strategy

`refresh_targets` records an entity, cadence, last attempt, last success,
next due time, failure count, and last error. The implementation is an explicit
single-process foundation, not a distributed scheduler. It supports different
cadences for ATS boards, active jobs, careers pages, news, and historical
research.

Successful refreshes schedule the normal cadence. Failures use bounded
exponential backoff. `recruiting refresh run --dry-run` reports due work without
performing network operations; future runners can dispatch the same target
through the existing discovery/fetching interfaces.
