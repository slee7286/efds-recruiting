# AI context retrieval

Conversation messages are indexed locally with SQLite FTS5. Use
`recruiting ai conversations list`, `search`, `show`, and `link`. Links can
associate a conversation with a company, application, task, or artifact.

Prior conversation context must be bounded and labeled `AI_CONTEXT`; it cannot
become a research claim or candidate evidence without a separate reviewed
workflow. Future task manifests should record selected conversation/message IDs
and selection reasons.
