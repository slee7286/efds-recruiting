# Interactive AI workflow

V5 does not call an LLM and does not automate ChatGPT. It creates a bounded task directory under data/ai_queue/task-id with manifest.json, instructions.md, input/, output/result.json, and validation/validation.json.

Run a preparation command, open the instructions and input files in a human-operated AI session, save JSON to output/result.json, then run recruiting ai validate task-id and recruiting ai import task-id. Imported records remain drafts until a human approves them.

## Task lifecycle

ready becomes completed after valid output, or failed after invalid output. Approval is tracked separately as draft or approved; importing never approves an artifact.

