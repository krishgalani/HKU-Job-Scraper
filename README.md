# HKU Jobs Scraper

*Disclaimer: This project is intended strictly for educational and personal job-search purposes. Please respect the University of Hong Kong's Terms of Use and maintain responsible rate limits when running queries.*

A two-stage, LLM-powered web scraper for the [HKU Jobs Portal](https://jobs.hku.hk/) built with **Crawl4AI**, **Playwright**, **LiteLLM**, and **Pydantic**.

- **Stage 1:** Renders a filtered HKU job search URL and extracts summary listings and normalized job links into `search_summary.json`.
- **Stage 2:** Crawls each job detail page sequentially and extracts structured job data into `job_descriptions.json`.

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
uv run python3 main.py
```

### Run Specific Stages
- **Scrape search listings only (Stage 1):**
  ```bash
  uv run python3 main.py --stage 1
  ```
- **Scrape job details from an existing `search_summary.json` (Stage 2):**
  ```bash
  uv run python3 main.py --stage 2
  ```
- **Test Stage 2 on a limited number of jobs:**
  ```bash
  uv run python3 main.py --stage 2 --limit 3
  ```

### Non-Interactive / CLI Flag Mode
Pass `--url` and `--model` directly to bypass interactive prompts (refer to the [LiteLLM Providers Documentation](https://docs.litellm.ai/docs/providers) for valid model identifiers):
```bash
uv run python3 main.py \
  --url "https://jobs.hku.hk/cw/en/filter/?search-keyword=&brand=faculty%20of%20dentistry" \
  --model "deepseek/deepseek-flash"
```

---

## CLI Options

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--stage` | Pipeline stage to run (`1`, `2`, or `all`) | `all` |
| `--limit` | Maximum number of job detail pages to scrape in Stage 2 | `None` (all) |
| `--url` | HKU filtered search results URL (skips interactive URL prompt) | `None` |
| `--model` | LiteLLM `provider/model` ID, e.g. `deepseek/deepseek-flash` ([supported models](https://docs.litellm.ai/docs/providers)) | `None` |
| `--debug` | Save rendered page Markdown to `debug_stage1.md` and `debug_stage2.md` | `False` |

---

## Output Files

- **`search_summary.json`** — Extracted table rows (`ref`, `posting_title`, `department`, `closing_date`, `url`).
- **`job_descriptions.json`** — Full structured postings (`title`, `ref`, `work_type`, `department`, `categories`, `description`, `advertised_time`, `applications_close_time`, `source_url`).