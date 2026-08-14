# Recruiting email classification

Classification is deterministic and records its method, confidence, and reasons.
Supported categories include application confirmation, assessment, HireVue, interview
invitation/confirmation/reschedule, recruiter outreach, information request, rejection,
offer, withdrawal, deadline reminder, and non-recruiting.

Low-confidence classifications are retained as suggestions and do not mutate application
status. High-confidence deterministic templates create local `ApplicationEvent` rows with
the originating local message ID as provenance.
