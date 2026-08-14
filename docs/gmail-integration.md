# Gmail integration

Gmail access must use OAuth and a supported Gmail API client. The application must not
scrape Gmail, request the user's password, or send/modify messages. `GmailProvider` is
an injected service adapter so OAuth credentials can be held by the local secret-store
implementation and tests can use fixtures.

The normal query should be narrow: recent messages from known company/ATS domains or
messages containing recruiting phrases. Full-mailbox ingestion is not the default.

Live Gmail authorization was not available in the development environment; V11 tests
use EML fixtures and the provider protocol.
