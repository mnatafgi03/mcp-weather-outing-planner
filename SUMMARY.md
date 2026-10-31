# Part 1: Reading Summary (MCP and the Fetch Server)

## The article

The Hugging Face / Turing Post piece "What Is MCP, and Why Is Everyone Suddenly Talking About It?" starts from a practical problem: language models are capable but isolated from the data and tools they need, and connecting each model to each source used to mean custom, brittle glue code. Anthropic introduced the Model Context Protocol in November 2024 as an open standard for plugging many sources of context into AI assistants. Reaction was muted at first, but adoption has surged. The core idea is that tool access becomes a shared protocol: write a tool once as a server and any compliant application can use it, turning an N×M integration problem into N+M.

MCP defines three roles. The **Host** is the AI application the user interacts with (a chat app, an IDE, a custom agent); it owns the model and decides what context the model sees. Inside it lives one **Client per server**, a connector that keeps the session, negotiates capabilities, discovers tools and relays calls. The **Server** is a separate program that exposes tools, read-only resources and prompt templates, and knows nothing about the model. Messages travel as JSON-RPC over stdio or HTTP. Here, the OpenAI Agents SDK program is host and client, and FastMCP provides the server.

## The server I explored: Fetch

The reference Fetch server retrieves a URL and returns it as markdown. It exposes one `fetch` tool with typed arguments (`url`, `max_length`, `start_index`, `raw`), each documented with a default, plus a `fetch` prompt for user-initiated use.

Against the class principles, the **interface is well defined and behaviour is predictable**: output is truncated at a known length, the response tells the model to call again with a new `start_index`, and robots.txt is respected for model-initiated requests. **Isolation is good but not perfect.** The tool has no side effects, yet it quietly bundles downloading, HTML-to-markdown conversion and pagination, and the `raw` flag switches it between two output modes. A stricter design would split these, for example `fetch_markdown` and `fetch_raw_html`. It also returns plain text with no output schema, and its README warns it can reach internal addresses, so the safety boundary lives outside the tool.

Overall, it is a good single-purpose tool whose few extra parameters earn their place.
