import requests
from bs4 import BeautifulSoup
import time

BASE = "https://analyst-assessment-production.up.railway.app"

def scrape_hub():
    communities = []
    page = 1
    while True:
        resp = requests.get(f"{BASE}/communities", params={"page": page}, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        # each community is an <h3> (or similar) with a link, followed by city/state and care type text
        # inspect the actual markup to get the right selector — likely something like:
        cards = soup.select("article")  # placeholder — check real tag/class in DevTools
        if not cards:
            break

        for card in cards:
            link = card.find("a")
            name = link.get_text(strip=True)
            detail_url = link["href"]
            if detail_url.startswith("/"):
                detail_url = BASE + detail_url

            # city/state line, e.g. "Maplewood, OH"
            city_state_text = card.find_all("p")[0].get_text(strip=True)  # adjust index
            city, state = [s.strip() for s in city_state_text.split(",")]

            care_type = card.find_all("p")[1].get_text(strip=True)  # adjust index

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

def scrape_detail(detail_url):
    resp = requests.get(detail_url, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    # look for a street address element — check the real page for this
    address = soup.select_one(".address")  # placeholder
    return address.get_text(strip=True) if address else None
