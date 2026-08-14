# Future EFDS integration

This database remains private and separate from the EFDS website/database.

EFDS may eventually receive only a curated and sanitized shared subset, such as approved firm summaries or public recruiting resources. Personal applications, CV versions, candidate evidence, application outcomes, contacts, and private preparation history must never be directly exposed.

Any future integration should use a publishing/sync layer or a controlled backend API with explicit field-level policy, review, audit logging, and one-way publication semantics. It must not use direct unrestricted cross-database access or share this system's private database credentials.
