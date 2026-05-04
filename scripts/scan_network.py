"""
園関係ネットワーク 情報収集スクリプト（GitHub Actions用）
- orgs.json の団体ごとにDuckDuckGo検索
- ページを取得して役職キーワード行を抽出
- 結果を scan_results/scan_result_YYYYMMDD.txt に保存
"""

import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

BASE_DIR    = Path(__file__).parent
OUTPUT_DIR  = BASE_DIR.parent / "scan_results"
ORGS_FILE   = BASE_DIR / "orgs.json"

def get_output_file(level_filter=None):
    OUTPUT_DIR.mkdir(exist_ok=True)
    suffix = f"_{level_filter}" if level_filter else ""
    return OUTPUT_DIR / f"scan_result_{date.today().strftime('%Y%m%d')}{suffix}.txt"

ROLE_KEYWORDS = [
    "会長", "副会長", "理事長", "副理事長", "理事", "監事",
    "委員長", "副委員長", "委員", "地区長", "幹事長", "幹事",
    "園長", "所長", "センター長", "施設長",
]

SKIP_DOMAINS = [
    "wikipedia.org", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "youtube.com", "amazon.co.jp",
    "rakuten.co.jp", "indeed.com", "workable.com",
]

MAX_PAGES_PER_QUERY = 3
REQUEST_TIMEOUT     = 8
SEARCH_SLEEP        = 3
PAGE_SLEEP          = 1


def load_orgs() -> list[dict]:
    return json.loads(ORGS_FILE.read_text(encoding="utf-8"))


def role_regex() -> re.Pattern:
    keywords = "|".join(re.escape(k) for k in ROLE_KEYWORDS)
    return re.compile(rf"({keywords})")


def is_skip_domain(url: str) -> bool:
    try:
        host = urlparse(url).netloc
        if any(d in host for d in SKIP_DOMAINS):
            return True
        non_jp = [".cn", ".tw", ".kr", ".de", ".fr", ".ru", "bbc.com",
                  "babyhome", "docsplayer", "docdroid"]
        if any(d in host for d in non_jp):
            return True
        return False
    except Exception:
        return False


def fetch_text(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers, allow_redirects=True)
        if resp.encoding and resp.encoding.lower() in ("iso-8859-1", "ascii"):
            resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding=resp.encoding or "utf-8")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n")
    except Exception:
        return ""


def extract_relevant_lines(text: str, org_name: str, pat: re.Pattern) -> list[str]:
    lines = text.splitlines()
    hit_indices = set()
    for i, line in enumerate(lines):
        line_clean = line.strip()
        if len(line_clean) < 2 or len(line_clean) > 200:
            continue
        if pat.search(line_clean):
            for j in range(max(0, i-1), min(len(lines), i+2)):
                hit_indices.add(j)

    result = []
    prev = -2
    for i in sorted(hit_indices):
        if i != prev + 1 and result:
            result.append("---")
        line = lines[i].strip()
        if line:
            result.append(line)
        prev = i
    return result


def search_org(org: dict, dry_run: bool = False) -> list[dict]:
    results = []
    pat = role_regex()
    seen_urls: set[str] = set()

    print(f"\n🔍 {org['name']}")

    for url in org.get("direct_urls", []):
        if dry_run:
            print(f"   直接取得(dry): {url}")
            continue
        seen_urls.add(url)
        print(f"   直接: {url[:70]}")
        text = fetch_text(url)
        time.sleep(PAGE_SLEEP)
        if text:
            lines = extract_relevant_lines(text, org["name"], pat)
            if lines:
                results.append({"org": org["name"], "url": url, "query": "direct", "lines": lines[:60]})
                print(f"   ✅ {len(lines)}行抽出")
            else:
                print(f"   ─ 役職情報なし（直接URL）")

    for query_base in org["search_queries"]:
        query = query_base
        print(f"   検索: {query}")

        if dry_run:
            continue

        try:
            hits = list(DDGS().text(query, region="jp-jp", max_results=MAX_PAGES_PER_QUERY + 2))
        except Exception as e:
            print(f"   ⚠ 検索エラー: {e}")
            hits = []

        time.sleep(SEARCH_SLEEP)

        for hit in hits:
            url = hit.get("href", "")
            if not url or url in seen_urls or is_skip_domain(url):
                continue
            seen_urls.add(url)

            print(f"   取得: {url[:70]}...")
            text = fetch_text(url)
            time.sleep(PAGE_SLEEP)

            if not text:
                continue

            lines = extract_relevant_lines(text, org["name"], pat)
            if lines:
                results.append({
                    "org":   org["name"],
                    "url":   url,
                    "query": query,
                    "lines": lines[:60],
                })
                print(f"   ✅ {len(lines)}行抽出")
            else:
                print(f"   ─ 役職情報なし")

            if len(results) >= MAX_PAGES_PER_QUERY:
                break

    return results


def format_output(all_results: list[dict]) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append(f"園関係ネットワーク スキャン結果")
    lines.append(f"実行日: {date.today()}")
    lines.append(f"団体数: {len(set(r['org'] for r in all_results))}")
    lines.append(f"ページ数: {len(all_results)}")
    lines.append("=" * 70)
    lines.append("")
    lines.append("【使い方】")
    lines.append("このファイルを Claude Code に渡して:")
    lines.append("  「scan_result_YYYYMMDD.txt を読んで既存mdファイルと照合し、")
    lines.append("   新規追加・情報更新の候補を提案してください」")
    lines.append("")

    current_org = None
    for r in all_results:
        if r["org"] != current_org:
            lines.append("")
            lines.append("━" * 50)
            lines.append(f"■ {r['org']}")
            lines.append("━" * 50)
            current_org = r["org"]

        lines.append(f"\n[URL] {r['url']}")
        lines.append(f"[クエリ] {r['query']}")
        lines.append("[抽出行]")
        lines.extend(r["lines"])
        lines.append("")

    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    dry_run      = "--dry-run" in args
    org_filter   = None
    level_filter = None

    if "--org" in args:
        idx = args.index("--org")
        if idx + 1 < len(args):
            org_filter = args[idx + 1]

    if "--level" in args:
        idx = args.index("--level")
        if idx + 1 < len(args):
            level_filter = args[idx + 1]

    orgs = load_orgs()
    if org_filter:
        orgs = [o for o in orgs if org_filter in o["name"] or org_filter == o.get("abbr")]
        if not orgs:
            print(f"団体が見つかりません: {org_filter}")
            sys.exit(1)
    if level_filter:
        orgs = [o for o in orgs if o.get("level") == level_filter]
        if not orgs:
            print(f"レベルが見つかりません: {level_filter}")
            sys.exit(1)

    print(f"スキャン対象: {len(orgs)}団体")
    if dry_run:
        print("（dry-run: 検索クエリの確認のみ）")

    all_results = []
    for org in orgs:
        results = search_org(org, dry_run=dry_run)
        all_results.extend(results)

    if not dry_run:
        output_file = get_output_file(level_filter)
        output = format_output(all_results)
        output_file.write_text(output, encoding="utf-8")
        print(f"\n✅ 保存: {output_file}")
        print(f"   {len(all_results)}ページから情報を抽出しました")


if __name__ == "__main__":
    main()
