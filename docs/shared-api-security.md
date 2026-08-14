# Shared API security

The API has no candidate, application, CV, answer, conversation, browser, or
sensitive-field routes. OpenAPI privacy tests enforce that boundary. It is a
public-intelligence read surface only; search keys and database credentials
remain server-side.

Allowed origins and hosts are configured explicitly. Public requests are GET
only in the configured CORS policy, responses are bounded, and ETags reduce
unnecessary downloads. Future member/admin authentication must be added at the
API boundary rather than distributing database credentials to clients.
