from datetime import datetime, timedelta


def passes_include_keywords(job: dict, include_keywords: list[str]) -> bool:
    if not include_keywords:
        return True
    title = job.get("title", "").lower()
    return any(kw.lower() in title for kw in include_keywords)


def passes_exclude_keywords(job: dict, exclude_keywords: list[str]) -> bool:
    if not exclude_keywords:
        return True
    title = job.get("title", "").lower()
    return not any(kw.lower() in title for kw in exclude_keywords)


def passes_date_cutoff(job: dict, cutoff_days: int) -> bool:
    date_str = job.get("date_posted")
    if not date_str:
        return True
    try:
        posted = datetime.fromisoformat(date_str)
        cutoff = datetime.now() - timedelta(days=cutoff_days)
        return posted >= cutoff
    except (ValueError, TypeError):
        return True


def passes_skip_list(job: dict, skip_companies: list[str]) -> bool:
    if not skip_companies:
        return True
    company = job.get("company", "").lower()
    return company not in [c.lower() for c in skip_companies]


def apply_all_filters(job: dict, config: dict) -> bool:
    kw = config.get("keywords", {})
    return (
        passes_include_keywords(job, kw.get("include", []))
        and passes_exclude_keywords(job, kw.get("exclude", []))
        and passes_date_cutoff(job, config.get("date_cutoff_days", 7))
        and passes_skip_list(job, config.get("skip_companies", []))
    )
