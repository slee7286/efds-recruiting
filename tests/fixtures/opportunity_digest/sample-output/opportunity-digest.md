# EFDS opportunity digest

- Digest: `431e11d7d6f693355ac19c5d96e2c1e506e9e362a88971eb48dc70f8e11c6ef2`
- Status: `incomplete`
- Review status: `pending`
- Sources: 1/2 complete

## Opportunities

### `["synthetic","example-board","external","role-001"]`

- Provider/board: `synthetic` / `example-board`
- External ID: `role-001`
- firm: Example Quant Labs
  - evidence: `fixture-primary/accepted-001#/firm`
  - evidence: `fixture-primary/accepted-duplicate#/firm`
- role: Research Intern
  - evidence: `fixture-primary/accepted-001#/role`
  - evidence: `fixture-primary/accepted-duplicate#/role`
- location: London
  - evidence: `fixture-primary/accepted-001#/location`
  - evidence: `fixture-primary/accepted-duplicate#/location`
- deadline: 2026-10-01
  - evidence: `fixture-primary/accepted-001#/deadline`
  - evidence: `fixture-primary/accepted-duplicate#/deadline`
- eligibility: unknown (not_reported)
- job_url: https://jobs.example.invalid/example-board/role-001
  - evidence: `fixture-primary/accepted-001#/job_url`
  - evidence: `fixture-primary/accepted-duplicate#/job_url`
- application_url: https://apply.example.invalid/example-board/role-001
  - evidence: `fixture-primary/accepted-001#/application_url`
  - evidence: `fixture-primary/accepted-duplicate#/application_url`
- Source references:
  - `fixture-primary/accepted-duplicate` raw `9edbff51e0801dc811a1841fcb4b230204d4448bda63d487de4d4caebb9ccdf7` normalized `43caffb15572651fe5cd7333cd5ff6bf7e9c1f6a159e625b06a74871bbd9efb1`
  - `fixture-primary/accepted-001` raw `0e7ce556f6b863a49b3d7ab407f32ad18c6d07524d3fb5bde9fc1fa2b12d8f57` normalized `492a2c89f031ebe782dbd2e5fdf2948165fb1a16862d98ba5ea0b493b21d8720`

### `["synthetic","example-board","external","role-002"]`

- Provider/board: `synthetic` / `example-board`
- External ID: `role-002`
- firm: Example Quant Labs
  - evidence: `fixture-primary/conflict-001#/firm`
- role: Quantitative Developer
  - evidence: `fixture-primary/conflict-001#/role`
- location: Cambridge
  - evidence: `fixture-primary/conflict-001#/location`
- deadline: conflict (2026-10-15; 2026-11-01)
  - conflict evidence: `fixture-primary/conflict-001#/deadline_claims/0`
  - conflict evidence: `fixture-primary/conflict-001#/deadline_claims/1`
- eligibility: unknown (not_reported)
- job_url: https://jobs.example.invalid/example-board/role-002
  - evidence: `fixture-primary/conflict-001#/job_url`
- application_url: unknown (not_reported)
- Source references:
  - `fixture-primary/conflict-001` raw `1288e7bb0604aac4fe0c1a2895099c77532642b0185e7a6dad16a396942fb8b7` normalized `2fb4dd92e72d5f2df041a776ef4254655c7768f5a3d1f5805473a52014fb0fa4`

## Exclusions

- `fixture-primary/irrelevant-001`: `outside_target_role`

## Source errors

- `fixture-failed` `capture_failed`: synthetic source timeout recorded without retry

## Advisory ranking

Facts and evidence above are source-derived; this section is advisory only.

- `["synthetic","example-board","external","role-001"]` score 5: firm:known, role:known, location:known, deadline:known, application_url:known
- `["synthetic","example-board","external","role-002"]` score 3: firm:known, role:known, location:known, deadline:conflict, application_url:unknown
