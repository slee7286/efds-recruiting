# Sensitive browser fields

Work authorization, sponsorship, citizenship, demographic information, salary,
criminal history, conflicts, relocation, and similar fields are never inferred.
Without an explicitly entered and approved local value they become
`needs_input`. Sensitive values are never included in shared API requests or
shared logs.
