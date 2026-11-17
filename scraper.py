"""Core scraping logic and Pydantic schemas for the HKU jobs portal."""

import json
import os
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import litellm
from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    LLMConfig,
)
from crawl4ai.extraction_strategy import LLMExtractionStrategy
from pydantic import BaseModel, Field

litellm.drop_params = True
litellm.suppress_debug_info = True

STAGE1_FILE = "search_summary.json"
STAGE2_FILE = "job_descriptions.json"

class SearchResultsListing(BaseModel):
    """Schema for a single row in the HKU search results table."""

    ref: str = Field(..., description="Reference number of the job posting")
    posting_title: str = Field(..., description="Title of the job posting")
    department: str = Field(..., description="Department or team associated with the job posting")
    closing_date: str = Field(..., description="Closing date for applications")
    url: str = Field(..., description="Link to the individual job details page")


class JobPosting(BaseModel):
    """Schema for the full details extracted from an individual job page."""

    title: str = Field(..., description="Title of the job posting")
    ref: str = Field(..., description="Reference number of the job posting")
    work_type: str = Field(..., description="Type of work (e.g., full-time, part-time, contract)")
    department: str = Field(..., description="Department or team associated with the job posting")
    categories: str = Field(..., description="Job type category")
    description: str = Field(..., description="Detailed description of the job posting")
    advertised_time: str = Field(..., description="Time when the job was advertised")
    applications_close_time: str = Field(..., description="Time when applications close")


def expand_page_items(url: str, page_size: int = 500) -> str:
    """Append or override page-items on PageUp search URLs to load all listings at once."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["page-items"] = [str(page_size)]
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


async def stage_1_scrape_listings(
    search_url: str, llm_cfg: LLMConfig, debug: bool = False
) -> list[dict]:
    """Scrape the search results page and write normalized job URLs to STAGE1_FILE."""
    search_url = expand_page_items(search_url)
    list_strategy = LLMExtractionStrategy(
        llm_config=llm_cfg,
        schema=SearchResultsListing.model_json_schema(),
        extraction_type="schema",
        extra_args={"reasoning_effort": "none"},
        instruction=(
            "Extract all complete job postings from this chunk. "
            "Ignore search filters, category links, and incomplete rows cut off at the start or end."
        ),
        input_format="markdown",
        apply_chunking=True,
        chunk_token_threshold=2000,  # ~25 jobs per LLM call
        overlap_rate=0.1
    )

    run_cfg = CrawlerRunConfig(
        extraction_strategy=list_strategy,
        cache_mode=CacheMode.BYPASS,
        wait_until="networkidle",
        css_selector="#search-results-content",
    )

    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.arun(url=search_url, config=run_cfg)

    if not result.success or not result.extracted_content:
        raise RuntimeError(f"Stage 1 failed: {result.error_message}")

    if debug:
        with open("debug_stage1.md", "w", encoding="utf-8") as f:
            f.write(result.markdown or "")

    raw_data = json.loads(result.extracted_content)
    listings = (
        raw_data
        if isinstance(raw_data, list)
        else raw_data.get("search_results", []) if isinstance(raw_data, dict) else []
    )

    # Deduplicate by job URL in case overlap_rate caught a boundary row twice
    seen_urls = set()
    unique_listings = []
    for item in listings:
        if item.get("url") and item["url"] not in seen_urls:
            item["url"] = urljoin(search_url, item["url"])
            seen_urls.add(item["url"])
            unique_listings.append(item)

    listings = unique_listings

    with open(STAGE1_FILE, "w", encoding="utf-8") as f:
        json.dump(listings, f, indent=2, ensure_ascii=False)

    print(f"[Stage 1] Saved {len(listings)} job listings to {STAGE1_FILE}")
    return listings


async def stage_2_scrape_details(
    llm_cfg: LLMConfig, limit: int | None = None, debug: bool = False
) -> list[dict]:
    """Read URLs from STAGE1_FILE, extract full job details, and save to STAGE2_FILE."""
    if not os.path.exists(STAGE1_FILE):
        raise FileNotFoundError(f"Missing {STAGE1_FILE}. Run --stage 1 first.")

    with open(STAGE1_FILE, "r", encoding="utf-8") as f:
        listings = json.load(f)

    job_urls = [item["url"] for item in listings if item.get("url")]
    if limit:
        job_urls = job_urls[:limit]

    if not job_urls:
        print("[Stage 2] No valid URLs found to scrape.")
        return []

    print(
        f"[Stage 2] Scraping {len(job_urls)} job detail pages "
        "(press Ctrl+C anytime to abort and save partial results)..."
    )

    detail_strategy = LLMExtractionStrategy(
        llm_config=llm_cfg,
        schema=JobPosting.model_json_schema(),
        extraction_type="schema",
        extra_args={"reasoning_effort": "none"},
        instruction="Extract the complete job posting details from this page.",
        input_format="markdown",
        apply_chunking=False,
    )

    detail_cfg = CrawlerRunConfig(
        extraction_strategy=detail_strategy,
        cache_mode=CacheMode.BYPASS,
        wait_until="networkidle",
        css_selector="#job-content",
    )

    all_jobs = []
    try:
        async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
            for idx, url in enumerate(job_urls):
                print(f"[Stage 2] ({idx + 1}/{len(job_urls)}) Scraping {url}")
                res = await crawler.arun(url=url, config=detail_cfg)

                if debug and idx == 0:
                    with open("debug_stage2.md", "w", encoding="utf-8") as f:
                        f.write(res.markdown or "")

                if res.success and res.extracted_content:
                    parsed = json.loads(res.extracted_content)
                    if parsed:
                        job_data = parsed[0] if isinstance(parsed, list) else parsed
                        job_data["source_url"] = res.url
                        all_jobs.append(job_data)
                else:
                    print(f"[Stage 2] Failed on {res.url}: {res.error_message}")
    finally:
        if all_jobs:
            with open(STAGE2_FILE, "w", encoding="utf-8") as f:
                json.dump(all_jobs, f, indent=2, ensure_ascii=False)
            print(f"[Stage 2] Saved {len(all_jobs)} job postings to {STAGE2_FILE}")

    return all_jobs