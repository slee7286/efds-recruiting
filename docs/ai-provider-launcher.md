# AI provider launcher

`recruiting ai open <task-id> --provider chatgpt|claude|gemini|custom` validates
the local task bundle, copies `instructions.md` when the platform clipboard is
available, opens a configurable provider URL, and prints the expected
`output/result.json` path. It does not type into, scrape, or automate any AI
website. The user selects the actual model in that provider's UI.
