# AI conversation import

The local archive accepts supplied ChatGPT `conversations.json`, generic Claude
or Gemini JSON exports, Markdown conversations, and generic JSON/Markdown.
Raw supplied files remain referenced, normalized messages preserve order and
roles, Markdown archives use frontmatter, and content hashes prevent duplicate
imports.

Use `recruiting ai import-conversations chatgpt <path> --dry-run` before import.
Conversation text is highly private and never syncs to the shared service.
