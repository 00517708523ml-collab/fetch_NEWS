import html
import os
import threading
import time
from urllib.parse import urlparse

import gradio as gr

from Backend import dashboard, ask_query

CACHE_TTL = 30 * 60
cache = {"items": [], "ts": 0.0}
lock = threading.Lock()
CATS = ["All", "AI Labs", "News", "Research", "Asia"]

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&family=Hanken+Grotesk:wght@400;500;600&display=swap');
.ain{--bg:#EEF1F4;--card:#fff;--ink:#14202B;--mut:#5E6B78;--line:#D5DCE3;--acc:#0B6E75;
 font-family:'Hanken Grotesk',system-ui,sans-serif;color:var(--ink);background:var(--bg);
 padding:26px clamp(14px,3vw,34px) 40px;border-radius:14px;color-scheme:light}
.ain *{box-sizing:border-box}
.ain h1,.ain h2,.ain h3,.ain .card h3,.ain .lead h3,.ain .sh h2{color:#14202B!important;opacity:1!important;text-shadow:none!important;background:none!important}
.ain .card,.ain .lead{color:#14202B!important}
.ain .card p,.ain .lead p,.ain .full{color:#33424F!important}
.ain .sub,.ain .status,.ain .dom,.ain .src,.ain .sh span{color:#5E6B78!important}
.ain .tag,.ain details summary,.ain .sh a{color:#0B6E75!important}
.ain h1,.ain h2,.ain h3{margin:0!important}
.ain h1,.ain h2,.ain h3{font-family:'Source Serif 4',Georgia,serif;margin:0}
.ain h1{font-size:clamp(30px,5vw,46px);line-height:1.05}
.ain .sub{color:var(--mut);margin:8px 0 0;font-size:14px}
.ain .bar{height:4px;background:var(--line);border-radius:4px;margin:16px 0 4px;overflow:hidden}
.ain .bar i{display:block;height:100%;background:var(--acc);transition:width .4s}
.ain .status{font-size:13px;color:var(--mut);min-height:18px}
.ain section{margin-top:30px}
.ain .sh{display:flex;align-items:center;justify-content:space-between;gap:10px;
 border-bottom:1px solid var(--line);padding-bottom:8px;margin-bottom:14px}
.ain .sh h2{font-size:21px}
.ain .sh span{font-size:12px;color:var(--mut);margin-left:8px;font-family:'Hanken Grotesk'}
.ain .sh a{font-size:13px;color:var(--acc);font-weight:600;text-decoration:none}
.ain .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}
.ain .card{display:flex;flex-direction:column;background:var(--card);border:1px solid var(--line);
 border-radius:8px;overflow:hidden;color:inherit}
.ain .card:hover,.ain .card:focus-visible{border-color:var(--acc);outline:none;box-shadow:0 0 0 3px rgba(11,110,117,.15)}
.ain .im{aspect-ratio:16/9;background:#DDE3E9;overflow:hidden}
.ain .im img{width:100%;height:100%;object-fit:cover;display:block}
.ain .im.noimg{aspect-ratio:auto;height:4px;background:var(--acc)}
.ain .body{padding:14px 16px 16px;display:flex;flex-direction:column;gap:8px;flex:1}
.ain .card h3{font-size:18px;line-height:1.28}
.ain .card p{margin:0;font-size:14.5px;line-height:1.6;color:#33424F}
.ain details summary{cursor:pointer;color:var(--acc);font-weight:600;font-size:13px;margin-top:2px}
.ain details .full{margin-top:10px}
.ain .src{margin-top:auto;font-size:12px;color:var(--mut);text-decoration:none}
.ain .src:hover{color:var(--acc);text-decoration:underline}
.ain .dom{margin-top:auto;font-size:12px;color:var(--mut)}
.ain .lead{display:grid;grid-template-columns:1.3fr 1fr;gap:0;background:var(--card);border:1px solid var(--line);
 border-radius:10px;overflow:hidden;text-decoration:none;color:inherit;margin-top:22px}
.ain .lead:hover{border-color:var(--acc)}
.ain .lead .im{aspect-ratio:auto;min-height:240px;height:100%}
.ain .lead .body{padding:24px;justify-content:center}
.ain .lead h3{font-size:clamp(22px,3vw,30px);line-height:1.2}
.ain .lead p{font-size:16px}
.ain .tag{font-size:12px;font-weight:600;color:var(--acc)}
.ain .wide{grid-column:1/-1}
.ain .empty{margin-top:26px;padding:26px;border:1px dashed var(--line);border-radius:10px;text-align:center;color:var(--mut)}
.ain .err{padding:16px;border-radius:10px;background:#FEF3F2;color:#B42318;border:1px solid #FECDCA}
@media (max-width:700px){.ain .lead{grid-template-columns:1fr}.ain .lead .im{min-height:180px}}
@media (prefers-reduced-motion:reduce){.ain *{transition:none!important}}
</style>
"""

esc = lambda s: html.escape(str(s or ""), quote=True)
domain = lambda u: urlparse(u).netloc.replace("www.", "")


def card(a, footer="", cls="card"):
    img = a.get("image")
    im = (f'<div class="im"><img src="{esc(img)}" alt="" loading="lazy" referrerpolicy="no-referrer" '
          f"onerror=\"this.parentNode.className='im noimg';this.remove()\"></div>") if img \
        else '<div class="im noimg"></div>'
    paras = a.get("paragraphs") or []
    snippet = a.get("snippet") or (paras[0] if paras else "")
    tag = f'<span class="tag">{esc(footer)}</span>' if footer else ""
    p = f"<p>{esc(snippet)}</p>" if snippet else ""
    rest = paras[1:] if paras and snippet == paras[0][:320] else paras
    more = ('<details><summary>Read more</summary>'
            + "".join(f'<p class="full">{esc(x)}</p>' for x in rest) + "</details>") if rest else ""
    link = (f'<a class="src" href="{esc(a["url"])}" target="_blank" rel="noopener noreferrer">'
            f'Original article on {esc(domain(a["url"]))}</a>') if a.get("url") else ""
    return f'<article class="{cls}">{im}<div class="body">{tag}<h3>{esc(a["title"])}</h3>{p}{more}{link}</div></article>'


def render_news(items, progress=None, ts=None, category="All", q=""):
    q = (q or "").strip().lower()
    status, bar = "", ""
    if progress:
        i, total = progress
        bar = f'<div class="bar"><i style="width:{int(i / max(total, 1) * 100)}%"></i></div>'
        status = f"Loading source {i} of {total}"
    elif ts:
        status = f"Updated {time.strftime('%H:%M', time.localtime(ts))}"

    shown = []
    for it in items:
        if category not in ("All", None) and it.get("category") != category:
            continue
        arts = [a for a in it.get("articles", [])
                if not q or q in (a["title"] + " " + a.get("snippet", "")).lower()]
        if arts or (not q and it.get("paragraphs")):
            shown.append((it, arts))

    out = [CSS, '<div class="ain"><h1>AI News</h1>',
           '<p class="sub">Headlines and summaries from AI labs, news sites and research blogs.</p>',
           bar, f'<div class="status">{esc(status)}</div>']

    if not shown:
        out.append('<div class="empty">No stories to show yet. Press <b>Refresh news</b>, or clear your filters.</div>')

    # Lead story: first article that has an image
    lead = next(((it, a) for it, arts in shown for a in arts if a.get("image")), None)
    if lead:
        it, a = lead
        out.append(card(a, footer=it["site"], cls="lead"))

    for it, arts in shown:
        out.append(f'<section><div class="sh"><h2>{esc(it["site"])}<span>{esc(it.get("category"))}</span></h2>'
                   f'<a href="{esc(it["source"])}" target="_blank" rel="noopener noreferrer">Visit site</a></div><div class="grid">')
        if arts:
            out += [card(a) for a in arts]
        else:
            out.append('<div class="wide">' + card({"title": it["site"], "url": it["source"],
                       "image": it.get("image"), "paragraphs": it.get("paragraphs")}) + "</div>")
        out.append("</div></section>")
    out.append("</div>")
    return "".join(out)


def load_news(force=False):
    if cache["items"] and time.time() - cache["ts"] < CACHE_TTL and not force:
        yield render_news(cache["items"], ts=cache["ts"])
        return
    if not lock.acquire(blocking=False):
        yield render_news(cache["items"], ts=cache["ts"])
        return
    try:
        items = []
        yield render_news(items, progress=(0, 1))
        for items, i, total in dashboard():
            yield render_news(items, progress=(i, total))
        if items:
            cache.update(items=items, ts=time.time())
        yield render_news(items, ts=time.time())
    except Exception as e:
        yield f'{CSS}<div class="ain"><div class="err"><b>Could not load news.</b><br>{esc(e)}</div></div>'
    finally:
        lock.release()


def refresh_news():
    yield from load_news(force=True)


def filter_news(category, q):
    return render_news(cache["items"], ts=cache["ts"], category=category, q=q)


def search(query):
    if not query or not query.strip():
        return f'{CSS}<div class="ain"><div class="empty">Type a topic, for example "new open-source LLM".</div></div>'
    try:
        exa_r, tav_r = ask_query(query)
    except Exception as e:
        return f'{CSS}<div class="ain"><div class="err"><b>Search failed.</b><br>{esc(e)}</div></div>'

    exa_c = []
    for r in getattr(exa_r, "results", None) or []:
        hl = getattr(r, "highlights", None)
        text = " ".join(hl) if isinstance(hl, list) else (hl or getattr(r, "text", "") or "")
        exa_c.append(card({"title": r.title or "Untitled", "url": r.url or "", "snippet": text[:260]}))
    tav_c = [card({"title": r.get("title", "Untitled"), "url": r.get("url", ""),
                   "snippet": (r.get("content") or "")[:260]}) for r in (tav_r or {}).get("results", [])]

    out = [CSS, f'<div class="ain"><h1 style="font-size:30px">Results for {esc(query)}</h1>']
    for name, cs in (("Exa", exa_c), ("Tavily", tav_c)):
        out.append(f'<section><div class="sh"><h2>{name}</h2></div><div class="grid">'
                   + ("".join(cs) or '<div class="empty wide">No results found.</div>') + "</div></section>")
    return "".join(out) + "</div>"


with gr.Blocks(title="AI News Dashboard") as app:
    with gr.Tab("Latest news"):
        with gr.Row():
            cat = gr.Radio(CATS, value="All", label="Category", scale=3)
            kw = gr.Textbox(label="Filter stories", placeholder="e.g. Gemini, agents", scale=2)
            refresh_btn = gr.Button("Refresh news", variant="primary", scale=1)
        news_output = gr.HTML(render_news([]))
        refresh_btn.click(refresh_news, outputs=news_output)
        cat.change(filter_news, [cat, kw], news_output)
        kw.change(filter_news, [cat, kw], news_output)
        app.load(load_news, outputs=news_output)

    with gr.Tab("Search"):
        query = gr.Textbox(label="Search AI news", placeholder="e.g. new open-source LLM")
        search_btn = gr.Button("Search", variant="primary")
        search_output = gr.HTML()
        search_btn.click(search, query, search_output)
        query.submit(search, query, search_output)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.launch(
        server_name="0.0.0.0",
        server_port=port
    )
