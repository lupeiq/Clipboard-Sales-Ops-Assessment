import os
import re
import requests
from bs4 import BeautifulSoup
import json
import time

BASE = "https://analyst-assessment-production.up.railway.app"


def scrape_hub():
    communities = []
    page = 1

    while True:
        resp = requests.get(f"{BASE}/communities", params={"page": page}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # stop once we've paged past the last page (out-of-range pages clamp
        # to the last page instead of returning empty, so we can't rely on
        # "no headings" to detect the end)
        pager_text = soup.select_one(".pager span")
        if pager_text:
            match = re.search(r"(\d+)\s*/\s*(\d+)", pager_text.get_text())
            if match:
                current_page, total_pages = int(match.group(1)), int(match.group(2))
                if page > total_pages:
                    break

        headings = soup.find_all("h3")
        if not headings:
            break

        for h in headings:
            link = h.find("a")
            if not link:
                continue
            name = link.get_text(strip=True)
            detail_url = link["href"]
            if detail_url.startswith("/"):
                detail_url = BASE + detail_url

            # city/state live in the card's <div class="city">, care type in
            # a <span class="badge"> - not <p> tags
            city_div = h.find_next("div", class_="city")
            badge_span = h.find_next("span", class_="badge")

            city, state = None, None
            if city_div:
                parts = [s.strip() for s in city_div.get_text(strip=True).split(",")]
                if len(parts) == 2:
                    city, state = parts

            care_type = badge_span.get_text(strip=True) if badge_span else None

            communities.append({
                "name": name,
                "city": city,
                "state": state,
                "care_type": care_type,
                "detail_url": detail_url,
            })

        page += 1
        time.sleep(0.3)

    return communities


if __name__ == "__main__":
    communities = scrape_hub()
    print(f"Found {len(communities)} communities")

    os.makedirs("data", exist_ok=True)
    with open("data/scraped_locations.json", "w") as f:
        json.dump(communities, f, indent=2)

    print("Saved to data/scraped_locations.json")
