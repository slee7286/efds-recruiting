# Synthetic review-pack inputs

The focused tests create small saved-pack, verification, and reconciliation
directories under pytest's temporary directory.  They exercise the same
explicit-input contract as the real offline command without copying real
captures, URLs, human decisions, or batch artifacts into the repository.
