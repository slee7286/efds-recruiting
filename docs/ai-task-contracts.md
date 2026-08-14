# AI task contracts

Task outputs are Pydantic v2 models with a task ID and schema version. Current contracts cover company synthesis, application analysis, candidate-firm matching, CV tailoring, written answers, cover letters, and interview preparation.

Validation checks JSON shape, task identity, supported schema version, database IDs, company ownership of sources, approved candidate evidence, specificity requirements, and application word/character limits. Invalid output is never imported.

