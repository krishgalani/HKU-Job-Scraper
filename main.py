"""CLI entrypoint and interactive configuration for the HKU job scraper."""

import argparse
import asyncio
import os

import questionary
from crawl4ai import LLMConfig
from dotenv import load_dotenv

from scraper import stage_1_scrape_listings, stage_2_scrape_details

load_dotenv()

QUIT_KEYWORDS = {"q", "quit", "exit"}

SUPPORTED_PROVIDERS = {
    "DeepSeek (deepseek/...)": {
        "prefix": "deepseek",
        "env_var": "DEEPSEEK_API_KEY",
        "example": "deepseek-flash",
    },
    "OpenAI (openai/...)": {
        "prefix": "openai",
        "env_var": "OPENAI_API_KEY",
        "example": "gpt-4o-mini",
    },
    "Anthropic (anthropic/...)": {
        "prefix": "anthropic",
        "env_var": "ANTHROPIC_API_KEY",
        "example": "claude-3-5-haiku-latest",
    },
    "Google Gemini (gemini/...)": {
        "prefix": "gemini",
        "env_var": "GEMINI_API_KEY",
        "example": "gemini-2.5-flash",
    },
    "Ollama Local (ollama/...)": {
        "prefix": "ollama",
        "env_var": None,
        "example": "deepseek-r1:8b",
    },
}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Two-stage HKU job scraper")
    parser.add_argument("--stage", choices=["1", "2", "all"], default="all", help="Pipeline stage(s) to run")
    parser.add_argument("--limit", type=int, default=None, help="Max job detail pages to scrape in Stage 2")
    parser.add_argument("--url", type=str, default=None, help="HKU search URL (skips URL prompt)")
    parser.add_argument("--model", type=str, default=None, help="Provider/model ID (skips model prompt)")
    parser.add_argument("--debug", action="store_true", help="Dump rendered Markdown to debug_stage*.md")
    return parser.parse_args()


def prompt_user_config(args: argparse.Namespace) -> tuple[str | None, LLMConfig]:
    """Resolve the target search URL and LLM configuration via CLI flags or interactive prompts."""
    search_url = args.url
    if args.stage in ("1", "all") and not search_url:
        search_url = questionary.text(
            "Enter the HKU search results URL (or 'q' to quit):",
            validate=lambda text: (
                True
                if text.strip().lower() in QUIT_KEYWORDS or text.startswith("http")
                else "Please enter a valid http/https URL (or 'q' to quit)"
            ),
        ).ask()
        if not search_url or search_url.strip().lower() in QUIT_KEYWORDS:
            raise SystemExit("Exited by user.")

    if args.model:
        provider_string = args.model
        prefix = provider_string.split("/")[0]
        env_var = next(
            (cfg["env_var"] for cfg in SUPPORTED_PROVIDERS.values() if cfg["prefix"] == prefix),
            "DEEPSEEK_API_KEY",
        )
    else:
        choice = questionary.select(
            "Select your LLM provider:",
            choices=[*SUPPORTED_PROVIDERS.keys(), "Exit"],
        ).ask()
        if not choice or choice == "Exit":
            raise SystemExit("Exited by user.")

        provider_cfg = SUPPORTED_PROVIDERS[choice]
        prefix = provider_cfg["prefix"]
        env_var = provider_cfg["env_var"]

        model_name = questionary.text(
            f"Enter the specific {prefix} model name (e.g., {provider_cfg['example']}, or 'q' to quit):",
            validate=lambda text: True if text.strip() else "Model name cannot be empty",
        ).ask()
        if not model_name or model_name.strip().lower() in QUIT_KEYWORDS:
            raise SystemExit("Exited by user.")

        clean_model = model_name.strip()
        provider_string = clean_model if clean_model.startswith(f"{prefix}/") else f"{prefix}/{clean_model}"

    api_key = os.getenv(env_var) if env_var else "ollama"
    if env_var and not api_key:
        raise RuntimeError(f"Missing {env_var} in your .env file.")

    llm_cfg = (
        LLMConfig(provider=provider_string, base_url="http://localhost:11434")
        if prefix == "ollama"
        else LLMConfig(provider=provider_string, api_token=api_key)
    )

    print(f"\nUsing model: {provider_string}\n")
    return search_url, llm_cfg


async def run_pipeline(args: argparse.Namespace, search_url: str | None, llm_cfg: LLMConfig) -> None:
    """Execute requested scraper stages."""
    if args.stage in ("1", "all"):
        if not search_url:
            raise ValueError("Search URL is required for Stage 1.")
        await stage_1_scrape_listings(search_url=search_url, llm_cfg=llm_cfg, debug=args.debug)
    if args.stage in ("2", "all"):
        await stage_2_scrape_details(llm_cfg=llm_cfg, limit=args.limit, debug=args.debug)


def main() -> None:
    """Entrypoint for the CLI."""
    args = parse_args()
    search_url, llm_cfg = prompt_user_config(args)

    try:
        asyncio.run(run_pipeline(args, search_url, llm_cfg))
    except KeyboardInterrupt:
        print("\n[Aborted] Scraper stopped by user.")


if __name__ == "__main__":
    main()