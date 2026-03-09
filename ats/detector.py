def detect_ats(url: str) -> str:
    """Identify the ATS platform from the apply URL."""
    url_lower = url.lower()

    patterns = {
        "greenhouse": ["greenhouse.io", "boards.greenhouse.io"],
        "lever": ["lever.co", "jobs.lever.co"],
        "ashby": ["ashbyhq.com"],
        "workday": ["myworkdayjobs.com", "workday.com"],
        "linkedin": ["linkedin.com/jobs"],
    }

    for ats_type, fragments in patterns.items():
        if any(f in url_lower for f in fragments):
            return ats_type

    return "unknown"
