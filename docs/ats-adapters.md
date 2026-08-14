# Public ATS adapters

V3 supports unauthenticated public board data through adapters for Greenhouse,
Lever, and Ashby. Detection is based on a verified public board URL; sync then
lists postings, preserves the raw payload in job metadata/observations, and
uses the existing job identity and history rules.

The implementations follow the vendors' public interfaces: [Greenhouse Job
Board API](https://developers.greenhouse.io/job-board.html), [Lever public
Postings API](https://hire.lever.co/developer/support), and [Ashby public Job
Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api).

ATS data is not proof of company ownership until the board is associated with a
company through evidence. No authenticated ATS APIs, candidate endpoints, or
anti-bot workarounds are used.
