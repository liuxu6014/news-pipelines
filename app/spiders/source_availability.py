"""Sources excluded from active crawling with retained evidence."""


BLOCKED_BY_ANTI_BOT = "blocked_by_anti_bot"
NO_PUBLIC_NEWS_FEED = "no_public_news_feed"
ROBOTS_FORBIDDEN = "robots_forbidden"


BLOCKED_SOURCES = {
    "DNV": {
        "disposition": BLOCKED_BY_ANTI_BOT,
        "reason": "Homepage, news pages, robots, and sitemap returned 403 across repeated and proxy attempts.",
    },
    "Colonial Pipeline": {
        "disposition": BLOCKED_BY_ANTI_BOT,
        "reason": "Homepage, newsroom, robots, and sitemap returned 403 in repeated environment probes.",
    },
    "Energy Transfer": {
        "disposition": BLOCKED_BY_ANTI_BOT,
        "reason": "Homepage, news, robots, and sitemap returned 403 or TLS failures in repeated probes.",
    },
    "National Grid Gas plc": {
        "disposition": BLOCKED_BY_ANTI_BOT,
        "reason": "Homepage, news, robots, and sitemap returned 403 in repeated probes.",
    },
    "Endress+Hauser": {
        "disposition": BLOCKED_BY_ANTI_BOT,
        "reason": (
            "Homepage, newsroom, robots, and sitemap-index all returned the same "
            "JavaScript Challenge Validation page; no static RSS, sitemap, or API "
            "response exposed article URLs."
        ),
    },
    "Mears Group, Inc.": {
        "disposition": BLOCKED_BY_ANTI_BOT,
        "reason": (
            "Official sitemap exposes blog article URLs, but every article response "
            "is a Cloudflare 403 challenge; repeated direct requests and sitemap "
            "discovery did not return article HTML."
        ),
    },
    "GAIL (India) - Gas Transmission": {
        "disposition": NO_PUBLIC_NEWS_FEED,
        "reason": (
            "The official site is an Angular shell with no server-rendered articles. "
            "Its sitemap contains six corporate pages and no news or press-release "
            "entry, and no public RSS or JSON feed was found."
        ),
    },
    "江苏省国有资产监督管理委员会": {
        "disposition": BLOCKED_BY_ANTI_BOT,
        "reason": (
            "Homepage and every configured 2026 news column are intercepted by "
            "Knownsec CloudWAF with HTTP 403 in repeated direct requests."
        ),
    },
    "海南省国有资产监督管理委员会": {
        "disposition": ROBOTS_FORBIDDEN,
        "reason": (
            "The site's current newsroom entries point to public mp.weixin.qq.com "
            "articles whose robots.txt forbids crawler access; no same-site article "
            "URL is exposed by the configured news columns."
        ),
    },
    "公安部": {
        "disposition": BLOCKED_BY_ANTI_BOT,
        "reason": "Homepage, configured section URLs, robots, and sitemap returned 521 across repeated and proxy attempts.",
    },
}


def is_source_blocked(name):
    return str(name or "").strip() in BLOCKED_SOURCES


def blocked_source_rows():
    return [
        {"name": name, **details}
        for name, details in sorted(BLOCKED_SOURCES.items())
    ]
