import os
import json
import re
import time
import requests
from pathlib import Path

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SEARCHES_FILE = Path("searches.json")
STATE_FILE = Path("data/state.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
    except Exception as e:
        print("Telegram error:", e)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_avito(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            print("Avito status:", r.status_code)
            return None
        return r.text
    except Exception as e:
        print("Avito fetch error:", e)
        return None


def parse_items(html: str):
    items = []

    m = re.search(
        r"window\.__initialData__\s*=\s*(\{.*?\});\s*</script>",
        html,
        re.DOTALL,
    )
    if m:
        try:
            data = json.loads(m.group(1))
            items = extract_from_json(data)
        except Exception as e:
            print("JSON parse error:", e)

    return items


def extract_from_json(data):
    results = []

    def walk(obj):
        if isinstance(obj, dict):
            if "id" in obj and ("title" in obj or "name" in obj):
                item_id = str(obj.get("id"))
                title = obj.get("title") or obj.get("name") or ""
                price = None
                if isinstance(obj.get("price"), dict):
                    price = obj["price"].get("value")
                elif isinstance(obj.get("price"), (int, float, str)):
                    price = obj.get("price")

                url = obj.get("url") or obj.get("uri") or ""
                if url and not url.startswith("http"):
                    url = "https://www.avito.ru" + url

                if title and item_id:
                    results.append(
                        {
                            "id": item_id,
                            "title": str(title)[:200],
                            "price": price,
                            "url": url,
                        }
                    )

            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return results


def main():
    searches = json.loads(SEARCHES_FILE.read_text(encoding="utf-8"))
    state = load_state()

    for search in searches:
        if not search.get("enabled", True):
            continue

        name = search.get("name", "search")
        url = search.get("url")
        if not url:
            continue

        print(f"Checking: {name}")
        html = fetch_avito(url)
        if not html:
            continue

        items = parse_items(html)
        print(f"  found {len(items)} items")

        key = name
        seen = state.get(key, {})
        first_run = len(seen) == 0

        for item in items:
            iid = item["id"]
            title = item["title"]
            price = item["price"]
            link = item["url"]

            if iid not in seen:
                if not first_run:
                    text = f"🆕 <b>{title}</b>\n"
                    if price is not None:
                        text += f"💰 {price} ₽\n"
                    if link:
                        text += f'🔗 <a href="{link}">Открыть</a>'
                    send_telegram(text)
                    time.sleep(1)
                seen[iid] = {"price": price, "title": title}
            else:
                old_price = seen[iid].get("price")
                if (
                    old_price is not None
                    and price is not None
                    and isinstance(old_price, (int, float))
                    and isinstance(price, (int, float))
                    and price < old_price
                ):
                    text = f"📉 <b>Цена снижена</b>\n{title}\n"
                    text += f"Было: {old_price} ₽\nСтало: {price} ₽\n"
                    if link:
                        text += f'🔗 <a href="{link}">Открыть</a>'
                    send_telegram(text)
                    time.sleep(1)
                seen[iid]["price"] = price

        state[key] = seen

    save_state(state)


if __name__ == "__main__":
    main()
