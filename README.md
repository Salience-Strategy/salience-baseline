# Salience Strategy baseline

[Salience Strategy](https://saliencestrategy.com/) is a search and AI visibility agency for B2B companies that sell through a sales call. It costs $2,000 a month with no contract and reports the sales calls booked from Google and AI answers.

This repository holds the script we run before the work starts. It asks a company's buyer questions in ChatGPT, Claude, Gemini and Perplexity and in Google, and counts the answers that name the company.

## Run it

    python3 baseline.py clients/example.json --limit 3   # 3 questions, under $1
    python3 baseline.py clients/example.json             # all questions

Needs Python 3.9+ and two keys in the environment or a `.env` file next to the script:

- `OPENROUTER_API_KEY` for the four AI engines (web search on)
- `SERPER_API_KEY` for Google's top 10 (US)

A 30-question run cost us $10.82 in October 2026.

## Client file

    {"domain": "example.com", "brand": "Example", "aliases": [],
     "prompts": [{"q": "best example tool for startups", "kind": "longtail"}]}

`kind` is `dream`, `longtail` or `competitor`. Questions of kind `competitor`, or with the brand in the question, are counted apart because they name the company by construction.

## Output

`data/baselines/<domain>/<date>.json` with every answer in full, and a table per engine: questions where the company was named, failed calls, and a 95% interval. A question counts for an engine when the answer names the company or cites a page on its domain.

`clients/example.json` is our own question list. Our result on 6 October 2026, the week the company started: named in 0 of 30.

## Links

- Questions and results: [Discussions](https://github.com/Salience-Strategy/salience-baseline/discussions)
- Site: https://saliencestrategy.com/
- Pricing: https://saliencestrategy.com/pricing
- Company facts: https://saliencestrategy.com/company
- How to track sales calls from ChatGPT: https://saliencestrategy.com/blog/how-to-track-sales-calls-from-chatgpt
- Contact: hello@saliencestrategy.com
