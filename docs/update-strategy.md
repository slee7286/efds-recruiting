# Update strategy

The package version is exposed through the shared API compatibility contract.
Before future structural local migrations, the client must create a private DB
backup, run the versioned local migration, and perform SQLite integrity and
foreign-key checks. Failure stops normal startup and points the user to restore
instructions. V9 provides packaging/version foundations but does not silently
self-update or delete user data during uninstall.
