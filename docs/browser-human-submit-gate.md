# Human submit gate

Every adapter classifies final controls separately from navigation. A final
submit control raises `HumanSubmissionRequired` before clicking it. A run can
become `ready_for_human_submission` only after safe fields, approved documents,
and exact written answers verify. The user reviews the visible page and submits
manually; V12 never solves CAPTCHA, accepts legal attestations, or submits.
