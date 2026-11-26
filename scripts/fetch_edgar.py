"""Download real credit agreements from SEC EDGAR to run the pipeline on (unlabeled).

Credit agreements are usually filed as Exhibit 10.x to 8-K, 10-Q or 10-K filings. Find the exhibit URLs with
EDGAR full-text search in your browser, put one URL per line in a file, then:

    python scripts/fetch_edgar.py urls.txt --user-agent "Your Name your.email@example.com"

SEC fair-access rules: declare who you are in the User-Agent and stay under 10 requests/second.
This script waits 0.25 s between requests (4/s) to stay well under that limit.
Outputs go to data/edgar/ (git-ignored). They are unlabeled: use them to find failure modes, then label a sample.
"""
from __future__ import annotations

import argparse
import html
import re
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "edgar"


def to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url_file")
    ap.add_argument("--user-agent", required=True, help='e.g. "Jane Doe jane@example.com"')
    args = ap.parse_args()
    if "@" not in args.user_agent:
        raise SystemExit("SEC asks for contact details in the User-Agent: include an email address.")
    OUT.mkdir(parents=True, exist_ok=True)
    urls = [u.strip() for u in Path(args.url_file).read_text().splitlines() if u.strip() and not u.startswith("#")]
    for i, url in enumerate(urls, 1):
        if not url.startswith("https://www.sec.gov/"):
            print(f"skip (not sec.gov): {url}")
            continue
        req = urllib.request.Request(url, headers={"User-Agent": args.user_agent, "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = to_text(resp.read().decode("utf-8", errors="replace"))
        name = f"EDGAR-{i:03d}_{re.sub(r'[^A-Za-z0-9]+', '-', url.rsplit('/', 1)[-1])[:60]}.txt"
        (OUT / name).write_text(text)
        print(f"saved {name} ({len(text):,} chars)")
        time.sleep(0.25)
    print(f"\nRun:  python -c \"from creditont.pipeline import *; from pathlib import Path; "
          f"exs, ont = run(make_extractor('llm'), load_docs(Path('{OUT}'))); print(len(ont.review), 'fields to review')\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
