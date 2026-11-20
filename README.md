# HKU Jobs Scraper

*Disclaimer: This project is intended strictly for educational and personal job-search purposes. Please respect the University of Hong Kong's Terms of Use and maintain responsible rate limits when running queries.*

A two-stage, LLM-powered web scraper for the [HKU Jobs Portal](https://jobs.hku.hk/) built with **Crawl4AI**, **Playwright**, **LiteLLM**, and **Pydantic**.

- **Stage 1:** Automatically detects total result pages, paginates through your filtered HKU job search URL in a single browser session, and extracts deduplicated listing summaries into `search_summary.json`.
- **Stage 2:** Crawls each job detail page sequentially, extracts the work type and full description, merges them with the Stage 1 metadata, and saves the combined records to `job_descriptions.json` (saving partial results on `Ctrl+C`).

---

## Setup

1. **Clone the repository and install dependencies with `uv`:**
   ```bash
   uv sync
   ```

2. **Install Playwright's headless Chromium browser:**
   ```bash
   uv run crawl4ai-setup
   ```

3. **Configure your API key:**
   Create a `.env` file in the project root and add the API key for your chosen LLM provider. Lightweight, non-reasoning models (e.g., `deepseek-flash`, `gpt-4o-mini`, `gemini-2.5-flash`) are recommended for faster, lower-cost extraction.

   ```env
   DEEPSEEK_API_KEY=your_api_key_here
   # Optional alternatives:
   # OPENAI_API_KEY=your_api_key_here
   # ANTHROPIC_API_KEY=your_api_key_here
   # GEMINI_API_KEY=your_api_key_here
   ```
   - *No API key is required when using a local Ollama model (requires Ollama running at `http://localhost:11434`).*
   - *See the [LiteLLM Providers Documentation](https://docs.litellm.ai/docs/providers) for all supported providers, required environment variables, and valid `provider/model` string formats.*

---

## Usage

### Interactive Mode (Recommended)
Run the scraper and follow the prompts to enter your HKU search URL and select your LLM provider/model:
```bash
uv run main.py
```

### Run Specific Stages
- **Scrape search listings only (Stage 1):**
  ```bash
  uv run main.py --stage 1
  ```
- **Test Stage 1 pagination on the first 2 pages:**
  ```bash
  uv run main.py --stage 1 --max-pages 2
  ```
- **Scrape job details from an existing `search_summary.json` (Stage 2):**
  ```bash
  uv run main.py --stage 2
  ```
- **Test Stage 2 on a limited number of jobs:**
  ```bash
  uv run main.py --stage 2 --limit 3
  ```

### Non-Interactive / CLI Flag Mode
Pass `--url` and `--model` directly to bypass interactive prompts (refer to the [LiteLLM Providers Documentation](https://docs.litellm.ai/docs/providers) for valid model identifiers):
```bash
uv run main.py \
  --url "https://jobs.hku.hk/jobs/search?page=1&dropdown_field_1_uids%5B%5D=9841a70f496f8ea53b678b0976c80486" \
  --model "deepseek/deepseek-flash"
```

---

## CLI Options

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--stage` | Pipeline stage to run (`1`, `2`, or `all`) | `all` |
| `--max-pages` | Maximum number of search result pages to scrape in Stage 1 | `None` (all) |
| `--page-param` | Query parameter name used for pagination URLs | `page` |
| `--limit` | Maximum number of job detail pages to scrape in Stage 2 | `None` (all) |
| `--url` | HKU filtered search results URL (skips interactive URL prompt) | `None` |
| `--model` | LiteLLM `provider/model` ID, e.g. `deepseek/deepseek-flash` ([supported models](https://docs.litellm.ai/docs/providers)) | `None` |
| `--debug` | Save rendered Markdown to `debug_stage0.md`, `debug_stage1_p*.md`, and `debug_stage2.md` | `False` |

---

## Output Files

- **`search_summary.json`** — Deduplicated search listing rows (`job_no`, `posting_title`, `department`, `applications_close_time`, `url`). Note: `applications_close_time` may be `null` for postings without a listed deadline.
- **`job_descriptions.json`** — Merged full postings combining Stage 1 metadata with Stage 2 details (`job_no`, `posting_title`, `department`, `applications_close_time`, `url`, `work_type`, `description`).