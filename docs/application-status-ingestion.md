# Application status ingestion

Email-derived status changes are conservative. A qualifying message creates an immutable
local application event with `source_type=email`, the message ID, the previous status,
and the new status. Original message text remains locally available according to the
configured retention mode.

Ambiguous links remain in the local unlinked queue for review. No status, outcome, or
recruiter information is sent to the shared service.
