# Search providers

V4 executes search only through configured legitimate providers. The initial
adapter is Brave Web Search API, configured with `SEARCH_PROVIDER=brave` and
`SEARCH_API_KEY`; the endpoint is configurable for compatible environments.
The adapter sends API requests, normalizes ranked results, records provider
metadata, and never scrapes search-result HTML. See the [Brave Web Search API
reference](https://api-dashboard.search.brave.com/api-reference/web/search/get).

Without configuration, `recruiting research search` fails clearly. Query
generation remains available offline. Search usage is recorded per provider and
company, with a configurable daily budget and deterministic dry-run mode.
