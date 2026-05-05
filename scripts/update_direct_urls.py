"""
スキャン結果から direct_urls 追加候補を抽出するスクリプト

- scan_results/scan_result_YYYYMMDD_*.txt を読み込む
- 役職情報が取れた URL のうち、orgs.json の direct_urls にまだないものを抽出
- url_candidates/url_candidates_YYYYMMDD.json として保存

使い方:
  python3 scripts/update_direct_urls.py 20260505
"""

import json
import sys
import re
from datetime import date
from pathlib import Path

BASE_DIR   = Path(__file__).parent
ORGS_FILE  = BASE_DIR / "orgs.json"
SCAN_DIR   = BASE_DIR.parent / "scan_results"
OUTPUT_DIR = BASE_DIR.parent / "url_candidates"

ROLE_KEYWORDS = [
    "会長", "副会長", "理事長", "副理事長", "理事", "監事",
    "委員長", "副委員長", "委員", "地区長", "幹事長", "幹事",
    "園長", "所長", "センター長", "施設長",
]

SKIP_DOMAINS = [
    "wikipedia.org", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "youtube.com", "amazon.co.jp",
    "rakuten.co.jp", "indeed.com",
]

MIN_ROLE_LINES = 3  # 役職情報が何行以上あれば候補とするか


def is_skip_domain(url: str) -> bool:
    return any(d in url for d in SKIP_DOMAINS)


def load_existing_direct_urls(orgs: list) -> dict[str, set]:
    """org名 → 既存direct_urlsのset"""
    result = {}
    for org in orgs:
        result[org["name"]] = set(org.get("direct_urls", []))
    return result


def parse_scan_file(fpath: Path) -> list[dict]:
    """スキャン結果ファイルを解析して {org, url, roles, line_count} のリストを返す"""
    lines = fpath.read_text(encoding="utf-8").splitlines()
    results = []
    current_org = ""
    current_url = ""
    current_roles = []
    current_lines = []
    in_extract = False

    for line in lines:
        line_s = line.strip()

        if line_s.startswith("■ "):
            current_org = line_s[2:]
            continue

        if line_s.startswith("[URL] "):
            # 前のURLのデータを保存
            if current_url and len(current_roles) >= MIN_ROLE_LINES:
                results.append({
                    "org": current_org,
                    "url": current_url,
                    "roles": list(dict.fromkeys(current_roles)),
                    "line_count": len(current_lines),
                })
            current_url = line_s[6:]
            current_roles = []
            current_lines = []
            in_extract = False
            continue

        if line_s == "[抽出行]":
            in_extract = True
            continue

        if line_s.startswith("[クエリ]"):
            in_extract = False
            continue

        if in_extract and line_s:
            current_lines.append(line_s)
            for kw in ROLE_KEYWORDS:
                if kw in line_s:
                    current_roles.append(kw)

    # 最後のURL
    if current_url and len(current_roles) >= MIN_ROLE_LINES:
        results.append({
            "org": current_org,
            "url": current_url,
            "roles": list(dict.fromkeys(current_roles)),
            "line_count": len(current_lines),
        })

    return results


def main():
    today = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y%m%d")

    orgs = json.loads(ORGS_FILE.read_text(encoding="utf-8"))
    existing = load_existing_direct_urls(orgs)

    # 3ファイル分を処理
    all_entries = []
    for level in ("national", "prefecture", "city"):
        fpath = SCAN_DIR / f"scan_result_{today}_{level}.txt"
        if fpath.exists():
            all_entries.extend(parse_scan_file(fpath))
            print(f"  {level}: {fpath.name} 読み込み完了")

    # direct_urlsにないURLだけ抽出
    candidates = []
    seen = set()
    for entry in all_entries:
        url = entry["url"]
        org = entry["org"]
        key = f"{org}|{url}"

        if key in seen:
            continue
        seen.add(key)

        if is_skip_domain(url):
            continue

        existing_urls = existing.get(org, set())
        if url not in existing_urls:
            candidates.append(entry)

    # 出力
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_file = OUTPUT_DIR / f"url_candidates_{today}.json"
    out_file.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n✅ URL追加候補: {len(candidates)}件 → {out_file}")
    if candidates:
        print("\n上位10件:")
        for c in sorted(candidates, key=lambda x: -x["line_count"])[:10]:
            print(f"  {c['org']} | {c['url'][:60]} ({c['line_count']}行)")

    return len(candidates)


if __name__ == "__main__":
    count = main()
    sys.exit(0)
