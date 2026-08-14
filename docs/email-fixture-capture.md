# Recruiting-email fixture capture

Use `recruiting email capture-fixture <local-message-id>` to create an explicit,
local-only `.eml` fixture and metadata file. Addresses, phone numbers, URLs and
message IDs are replaced with safe placeholders. Captured files are written
under the private data directory and are not automatically committed or
uploaded.

Only manually reviewed sanitized derivatives should be copied into tests. Keep
the original message in local storage and do not put real recruiting email in
the repository.
