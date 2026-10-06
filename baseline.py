#!/usr/bin/env python3
"""Count how often a client is named in answers to its buyers' questions.

    python3 baseline.py clients/<domain>.json [--runs 1] [--limit N]

Client file: {"domain", "brand", "aliases": [...], "prompts": [{"q", "kind"}]}.
Each prompt is asked `--runs` times in GPT, Claude, Gemini and Perplexity
(OpenRouter, web search on) and once in Google (Serper, US, top 10).

A prompt counts for an engine when at least one of its runs names the client
in the prose or cites a page on its domain. The output file keeps the two apart
(named in the answer vs. cited as a source only).
Prompts of kind "competitor" or with the brand in the question are branded
and reported apart, because they name the client by construction.

Output: data/baselines/<domain>/<date>.json with every answer in full, and a
summary table on stdout. Failed calls are excluded from the denominator and
counted in the `failed` column.
"""
import argparse
import datetime
import json
import math
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
SERPER = "https://google.serper.dev/search"
# The four engines.
ENGINES = {
    "gpt": {"model": "openai/gpt-chat-latest", "web": True},
    "claude": {"model": "anthropic/claude-fable-5.1", "web": True},
    "gemini": {"model": "google/gemini-3.7-flash", "web": True},
    "perplexity": {"model": "perplexity/sonar", "web": False},
}


def conf(name):
    if os.environ.get(name):
        return os.environ[name]
    for rel in (".env",):
        try:
            for line in open(os.path.join(ROOT, rel)):
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
    return ""


def host(url):
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def matcher(client):
    names = [client["brand"], client["domain"]] + client.get("aliases", [])
    pats = [r"(?<![\w.-])%s(?![\w-]|\.[a-z])" % re.escape(n) for n in names if n]
    rx = re.compile("|".join(pats), re.I)
    dom = client["domain"].lower()

    def named(text, urls):
        return status(text, urls) != ""

    def status(text, urls):
        """"named": the brand is in the prose. "cited": only a link to the
        client's site, as a source. "": neither."""
        text = text or ""
        links = re.findall(r"\]\((https?://[^)\s]+)\)", text) + re.findall(r"https?://[^\s)\]]+", text)
        prose = re.sub(r"\[[^\]]*\]\(https?://[^)\s]+\)", " ", text)
        prose = re.sub(r"https?://[^\s)\]]+", " ", prose)
        if rx.search(prose):
            return "named"
        if any(host(u) == dom or host(u).endswith("." + dom) for u in list(urls) + links):
            return "cited"
        return ""
    named.status = status
    return rx, named


def ask(key, engine, prompt):
    body = {"model": engine["model"], "messages": [{"role": "user", "content": prompt}]}
    if engine["web"]:
        body["plugins"] = [{"id": "web"}]
    req = urllib.request.Request(OPENROUTER, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=240))
    m = d["choices"][0]["message"]
    urls = [a["url_citation"]["url"] for a in (m.get("annotations") or [])
            if a.get("type") == "url_citation"]
    urls += d.get("citations") or []
    return m.get("content") or "", urls, (d.get("usage") or {}).get("cost")


def google(key, prompt):
    req = urllib.request.Request(SERPER, data=json.dumps({"q": prompt, "gl": "us", "num": 10}).encode(),
                                 method="POST", headers={"X-API-KEY": key,
                                                         "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    return [r["link"] for r in d.get("organic", [])]


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("client")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    client = json.load(open(a.client))
    okey, skey = conf("OPENROUTER_API_KEY"), conf("SERPER_API_KEY")
    if not okey or not skey:
        sys.exit("OPENROUTER_API_KEY and SERPER_API_KEY are required.")
    rx, named = matcher(client)
    prompts = client["prompts"][: a.limit or None]

    def one(p):
        q = p["q"]
        row = {"q": q, "kind": p.get("kind", ""),
               "branded": p.get("kind") == "competitor" or bool(rx.search(q)), "engines": {}}
        for name, eng in ENGINES.items():
            runs = []
            for _ in range(a.runs):
                try:
                    text, urls, cost = ask(okey, eng, q)
                    runs.append({"ok": True, "named": named(text, urls), "text": text,
                                 "urls": urls, "cost": cost})
                except Exception as ex:
                    runs.append({"ok": False, "err": str(ex)[:200]})
            row["engines"][name] = runs
        try:
            links = google(skey, q)
            pos = next((i + 1 for i, u in enumerate(links) if named("", [u])), None)
            row["google"] = {"ok": True, "position": pos, "links": links}
        except Exception as ex:
            row["google"] = {"ok": False, "err": str(ex)[:200]}
        print(".", end="", flush=True, file=sys.stderr)
        return row

    with ThreadPoolExecutor(6) as ex:
        rows = list(ex.map(one, prompts))
    print(file=sys.stderr)

    today = datetime.date.today().isoformat()
    out_dir = os.path.join(ROOT, "data", "baselines", client["domain"])
    os.makedirs(out_dir, exist_ok=True)
    suffix = "" if not a.limit else "-sample%d" % a.limit
    path = os.path.join(out_dir, "%s%s.json" % (today, suffix))
    cost = sum(r.get("cost") or 0 for row in rows for runs in row["engines"].values() for r in runs)
    json.dump({"client": client["domain"], "date": today, "runs": a.runs, "models": ENGINES,
               "openrouter_cost_usd": round(cost, 4), "rows": rows}, open(path, "w"), indent=1)

    def table(label, sel):
        print("\n%s (%d prompts)" % (label, len(sel)))
        print("%-11s %8s %7s %14s" % ("engine", "named", "failed", "95% interval"))
        for name in ENGINES:
            ok = [r for r in sel if any(x["ok"] for x in r["engines"][name])]
            k = sum(1 for r in ok if any(x.get("named") for x in r["engines"][name]))
            lo, hi = wilson(k, len(ok))
            print("%-11s %4d/%-3d %7d %6.0f%%-%.0f%%" % (name, k, len(ok), len(sel) - len(ok),
                                                       lo * 100, hi * 100))
        ok = [r for r in sel if r["google"]["ok"]]
        k = sum(1 for r in ok if r["google"]["position"])
        lo, hi = wilson(k, len(ok))
        print("%-11s %4d/%-3d %7d %6.0f%%-%.0f%%" % ("google top10", k, len(ok), len(sel) - len(ok),
                                                   lo * 100, hi * 100))

    table("Unbranded", [r for r in rows if not r["branded"]])
    branded = [r for r in rows if r["branded"]]
    if branded:
        table("Branded", branded)
    print("\nOpenRouter cost: $%.2f   saved: %s" % (cost, os.path.relpath(path, ROOT)))


if __name__ == "__main__":
    main()
