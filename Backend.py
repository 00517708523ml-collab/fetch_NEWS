import os
import re
import time
from urllib.parse import urljoin, urlparse

from dotenv import load_dotenv
from exa_py import Exa
from firecrawl import Firecrawl
from tavily import TavilyClient

load_dotenv()

EXA_API_KEY = os.getenv("EXA_API_KEY")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

for name, key in (("EXA_API_KEY", EXA_API_KEY),
                  ("FIRECRAWL_API_KEY", FIRECRAWL_API_KEY),
                  ("TAVILY_API_KEY", TAVILY_API_KEY)):
    if not key:
        raise ValueError(f"{name} is missing in .env")

exa = Exa(api_key=EXA_API_KEY)
firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY)

# (name, category, url)
SOURCES = [
    ("OpenAI", "AI Labs", "https://openai.com/news/"),
    ("Google DeepMind", "AI Labs", "https://deepmind.google/discover/blog/"),
    ("Anthropic", "AI Labs", "https://www.anthropic.com/news"),
    ("NVIDIA", "AI Labs", "https://blogs.nvidia.com/blog/category/deep-learning/"),
    ("Meta AI", "AI Labs", "https://ai.meta.com/blog/"),
    ("Microsoft AI", "AI Labs", "https://blogs.microsoft.com/ai/"),
    ("Qwen", "Asia", "https://qwen.ai/"),
    ("DeepSeek", "Asia", "https://www.deepseek.com/"),
    ("Moonshot", "Asia", "https://www.moonshot.cn/"),
    ("MiniMax", "Asia", "https://www.minimaxi.com/"),
    ("Z.ai", "Asia", "https://z.ai/"),
    ("TechCrunch", "News", "https://techcrunch.com/category/artificial-intelligence/"),
    ("The Verge", "News", "https://www.theverge.com/ai-artificial-intelligence"),
    ("VentureBeat", "News", "https://venturebeat.com/category/ai/"),
    ("The Decoder", "News", "https://the-decoder.com/"),
    ("MarkTechPost", "News", "https://www.marktechpost.com/"),
    ("Hugging Face Blog", "Research", "https://huggingface.co/blog"),
    ("Hugging Face Papers", "Research", "https://huggingface.co/papers"),
    ("arXiv cs.AI", "Research", "https://arxiv.org/list/cs.AI/recent"),
    ("arXiv cs.LG", "Research", "https://arxiv.org/list/cs.LG/recent"),
]

MAX_ARTICLES = 6
DELAY = 7  # seconds between scrapes (rate limit)

# ------------------------------------------------------------
# Markdown -> clean articles
# ------------------------------------------------------------
IMG = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")
LINK = re.compile(r"(?<!!)\[((?:[^\[\]]|!\[[^\]]*\]\([^)]*\))*)\]\(\s*<?([^)\s>]+)[^)]*\)")
SKIP = re.compile(
    r"^(read more|learn more|see all|view all|load more|sign in|log in|subscribe|"
    r"contact|about|careers|privacy|terms|skip to|menu|home|search|newsletter|"
    r"advertise|events?|podcasts?|login|cookie)", re.I)


def clean(text):
    text = IMG.sub("", text) if False else re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = LINK.sub(lambda m: m.group(1), text)
    text = re.sub(r"[*_`#>|]+", " ", text)
    text = re.sub(r"\\", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_articles(markdown, base_url):
    lines = markdown.splitlines()
    articles, seen = [], set()
    last_image = ""
    base = base_url.rstrip("/")

    for i, line in enumerate(lines):
        img = IMG.search(line)
        if img and not LINK.search(line):
            last_image = urljoin(base_url, img.group(1))
            continue

        for m in LINK.finditer(line):
            inner, href = m.group(1), m.group(2)
            if href.startswith(("#", "mailto:", "javascript:")):
                continue
            url = urljoin(base_url, href)
            title = clean(inner)
            if (url.rstrip("/") == base or url in seen or title.lower() in seen
                    or len(title) < 25 or len(title.split()) < 4
                    or len(title) > 220 or SKIP.match(title)):
                continue

            inner_img = IMG.search(inner)
            image = urljoin(base_url, inner_img.group(1)) if inner_img else last_image

            snippet = []
            for nxt in lines[i + 1:i + 6]:
                if LINK.search(nxt) or nxt.strip().startswith("!["):
                    if snippet:
                        break
                    continue
                t = clean(nxt)
                if len(t) > 40 and t != title:
                    snippet.append(t)
                if len(" ".join(snippet)) > 160:
                    break

            seen.update({url, title.lower()})
            articles.append({
                "title": title,
                "url": url,
                "image": image,
                "snippet": " ".join(snippet)[:300],
            })
            last_image = ""
            if len(articles) >= MAX_ARTICLES:
                return articles
    return articles


def paragraphs(text, limit=6):
    out = []
    for line in (text or "").splitlines():
        t = clean(line)
        if len(t) >= 50 and t.count(" ") >= 7:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def enrich(articles):
    """Fetch the real article text for each link (one Exa call per site)."""
    if not articles:
        return
    urls = [a["url"] for a in articles]
    try:
        res = exa.get_contents(urls, text={"max_characters": 3000})
    except Exception as error:
        print(f"Exa contents error: {error}")
        return
    results = list(res.results)
    by_url = {r.url.rstrip("/"): r for r in results}
    for n, a in enumerate(articles):
        r = by_url.get(a["url"].rstrip("/")) or (results[n] if len(results) == len(articles) else None)
        if not r:
            continue
        paras = [p for p in paragraphs(getattr(r, "text", ""), 6) if p != a["title"]]
        if paras:
            a["paragraphs"] = paras
            a["snippet"] = paras[0][:320]
        if not a.get("image") and getattr(r, "image", None):
            a["image"] = r.image


# ------------------------------------------------------------
# Scrape stream: yields (items, index, total)
# ------------------------------------------------------------
def dashboard():
    items = []
    total = len(SOURCES)

    for index, (name, category, url) in enumerate(SOURCES, start=1):
        print(f"[{index}/{total}] {name}: {url}")
        try:
            response = firecrawl.scrape(url, formats=["markdown"], only_main_content=True)
            markdown = response.markdown or ""
            meta = getattr(response, "metadata", None)
            og_image = ""
            if meta:
                get = meta.get if isinstance(meta, dict) else lambda k, d="": getattr(meta, k, d)
                og_image = get("og_image", "") or get("ogImage", "") or ""

            if markdown:
                articles = parse_articles(markdown, url)
                enrich(articles)
                items.append({
                    "site": name,
                    "category": category,
                    "source": url,
                    "articles": articles,
                    "image": og_image,
                    "paragraphs": paragraphs(markdown, 8) if not articles else [],
                })
        except Exception as error:
            print(f"ERROR ({name}): {error}")

        yield items, index, total

        if index < total:
            time.sleep(DELAY)


# ------------------------------------------------------------
# Search
# ------------------------------------------------------------
def chat(query):
    exa_results = exa.search(query, type="auto", contents={"highlights": True})
    tavily_results = tavily.search(query=query, max_results=5)
    return exa_results, tavily_results


def ask_query(user_query):
    return chat(user_query)