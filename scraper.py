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

    job_no: str = Field(..., description="Reference number of the job posting")
    posting_title: str = Field(..., description="Title of the job posting")
    department: str = Field(..., description="Department or team associated with the job posting")
    applications_close_time: str | None = Field(default=None, description="Time when applications close")
    url: str = Field(..., description="Link to the individual job details page")

class pagesMetadata(BaseModel):
    total_pages: int = Field(..., description="Total number of pages in the search results")

class JobPosting(BaseModel):
    """Schema for the full details extracted from an individual job page."""

    work_type: str = Field(..., description="Type of work (e.g., full-time, part-time, contract)")
    # department: str = Field(..., description="Department or team associated with the job posting")
    # categories: str = Field(..., description="Job type category")
    description: str = Field(..., description="Detailed description of the job posting")
    # advertised_time: str = Field(..., description="Time when the job was advertised")
    
def _build_page_url(base_url: str, page: int, page_param: str = "page") -> str:
    """Return base_url with the pagination query parameter set to page."""
    if page <= 1:
        return base_url
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query)
    query[page_param] = [str(page)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


async def stage_0_get_total_pages(
    search_url: str,
    llm_cfg: LLMConfig,
    crawler: AsyncWebCrawler | None = None,
    debug: bool = False,
) -> int:
    """Scrape the search results page and return the total number of pages."""
    metadata_strategy = LLMExtractionStrategy(
        llm_config=llm_cfg,
        schema=pagesMetadata.model_json_schema(),
        extraction_type="schema",
        extra_args={"reasoning_effort": "none"},
        instruction="Extract the total number of pages from this search results page.",
        input_format="markdown",
        apply_chunking=False,
    )

    run_cfg = CrawlerRunConfig(
        extraction_strategy=metadata_strategy,
        cache_mode=CacheMode.BYPASS,
        wait_until="networkidle",
        css_selector="[data-jobs--search-target='jobsSearchResults'] .bottom-pagination",
    )

    if crawler is not None:
        result = await crawler.arun(url=search_url, config=run_cfg)
    else:
        async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as local_crawler:
            result = await local_crawler.arun(url=search_url, config=run_cfg)

    if not result.success or not result.extracted_content:
        raise RuntimeError(f"Stage 0 failed: {result.error_message}")

    if debug:
        with open("debug_stage0.md", "w", encoding="utf-8") as f:
            f.write(result.markdown or "")

    raw_data = json.loads(result.extracted_content)
    # LLMExtractionStrategy typically returns a list of dicts
    if isinstance(raw_data, list):
        metadata = raw_data[0] if raw_data and isinstance(raw_data[0], dict) else {}
    elif isinstance(raw_data, dict):
        metadata = raw_data
    else:
        metadata = {}

    return max(1, int(metadata.get("total_pages") or 1))


async def stage_1_scrape_listings(
    search_url: str,
    llm_cfg: LLMConfig,
    page_param: str = "page",
    max_pages: int | None = None,
    debug: bool = False,
) -> list[dict]:
    """Discover total pages via Stage 0, scrape all search pages, and write normalized job URLs to STAGE1_FILE."""
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
        overlap_rate=0.1,
    )

    run_cfg = CrawlerRunConfig(
        extraction_strategy=list_strategy,
        cache_mode=CacheMode.BYPASS,
        wait_until="networkidle",
        css_selector="[data-jobs--search-target='jobsSearchResults'] .job-search-results-card-row",
    )

    seen_urls: set[str] = set()
    unique_listings: list[dict] = []

    try:
        async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
            total_pages = await stage_0_get_total_pages(
                search_url=search_url,
                llm_cfg=llm_cfg,
                crawler=crawler,
                debug=debug,
            )
            if max_pages:
                total_pages = min(total_pages, max_pages)

            print(f"[Stage 1] Found {total_pages} page(s) to scrape.")

            for page in range(1, total_pages + 1):
                page_url = _build_page_url(search_url, page, page_param=page_param)
                print(f"[Stage 1] ({page}/{total_pages}) Scraping {page_url}")

                result = await crawler.arun(url=page_url, config=run_cfg)

                if debug:
                    with open(f"debug_stage1_p{page}.md", "w", encoding="utf-8") as f:
                        f.write(result.markdown or "")

                if not result.success or not result.extracted_content:
                    print(f"[Stage 1] Failed on page {page}: {result.error_message}")
                    continue

                raw_data = json.loads(result.extracted_content)
                page_listings = (
                    raw_data
                    if isinstance(raw_data, list)
                    else raw_data.get("search_results", [])
                    if isinstance(raw_data, dict)
                    else []
                )

                for item in page_listings:
                    raw_url = item.get("url")
                    if not raw_url:
                        continue
                    abs_url = urljoin(page_url, raw_url)
                    if abs_url not in seen_urls:
                        item["url"] = abs_url
                        seen_urls.add(abs_url)
                        unique_listings.append(item)
    finally:
        if unique_listings:
            with open(STAGE1_FILE, "w", encoding="utf-8") as f:
                json.dump(unique_listings, f, indent=2, ensure_ascii=False)
            print(f"[Stage 1] Saved {len(unique_listings)} unique job listings to {STAGE1_FILE}")

    return unique_listings
async def stage_2_scrape_details(
    llm_cfg: LLMConfig, limit: int | None = None, debug: bool = False
) -> list[dict]:
    """Read listings from STAGE1_FILE, extract detail fields, merge them, and save to STAGE2_FILE."""
    if not os.path.exists(STAGE1_FILE):
        raise FileNotFoundError(f"Missing {STAGE1_FILE}. Run --stage 1 first.")

    with open(STAGE1_FILE, "r", encoding="utf-8") as f:
        listings = json.load(f)

    valid_listings = [item for item in listings if isinstance(item, dict) and item.get("url")]
    if limit:
        valid_listings = valid_listings[:limit]

    if not valid_listings:
        print("[Stage 2] No valid listings found to scrape.")
        return []

    print(
        f"[Stage 2] Scraping {len(valid_listings)} job detail pages "
        "(press Ctrl+C anytime to abort and save partial results)..."
    )

    detail_strategy = LLMExtractionStrategy(
        llm_config=llm_cfg,
        schema=JobPosting.model_json_schema(),
        extraction_type="schema",
        extra_args={"reasoning_effort": "none"},
        instruction="Extract the work type and complete job description from this page.",
        input_format="markdown",
        apply_chunking=False,
    )

    detail_cfg = CrawlerRunConfig(
        extraction_strategy=detail_strategy,
        cache_mode=CacheMode.BYPASS,
        wait_until="networkidle",
        css_selector=".block-job-description",
    )

    all_jobs: list[dict] = []
    try:
        async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
            for idx, listing in enumerate(valid_listings):
                url = listing["url"]
                print(f"[Stage 2] ({idx + 1}/{len(valid_listings)}) Scraping {url}")
                res = await crawler.arun(url=url, config=detail_cfg)

                if debug and idx == 0:
                    with open("debug_stage2.md", "w", encoding="utf-8") as f:
                        f.write(res.markdown or "")

                if res.success and res.extracted_content:
                    parsed = json.loads(res.extracted_content)
                    if parsed:
                        job_data = parsed[0] if isinstance(parsed, list) else parsed
                        if isinstance(job_data, dict) and not job_data.get("error"):
                            job_data.pop("error", None)
                            all_jobs.append({**listing, **job_data})
                else:
                    print(f"[Stage 2] Failed on {res.url}: {res.error_message}")
    finally:
        if all_jobs:
            with open(STAGE2_FILE, "w", encoding="utf-8") as f:
                json.dump(all_jobs, f, indent=2, ensure_ascii=False)
            print(f"[Stage 2] Saved {len(all_jobs)} job postings to {STAGE2_FILE}")

    return all_jobs