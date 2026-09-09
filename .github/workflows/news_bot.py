import os
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape


# ============================================================
# CONFIG
# ============================================================

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["NEWS_TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["NEWS_TELEGRAM_CHAT_ID"]

GEMINI_MODEL = "gemini-2.5-flash"

MAX_STORIES_PER_FEED = 8
MAX_STORIES_TO_GEMINI = 30

# Only these two publications
FEEDS = [
    # ---------------- BUSINESSLINE ----------------
    (
        "BusinessLine",
        "https://www.thehindubusinessline.com/news/feeder/default.rss",
    ),
    (
        "BusinessLine",
        "https://www.thehindubusinessline.com/money-and-banking/feeder/default.rss",
    ),
    (
        "BusinessLine",
        "https://www.thehindubusinessline.com/economy/macro-economy/feeder/default.rss",
    ),
    (
        "BusinessLine",
        "https://www.thehindubusinessline.com/economy/feeder/default.rss",
    ),
    (
        "BusinessLine",
        "https://www.thehindubusinessline.com/markets/feeder/default.rss",
    ),

    # ---------------- ECONOMIC TIMES ----------------
    (
        "Economic Times",
        "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
    ),
    (
        "Economic Times",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    ),
    (
        "Economic Times",
        "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
    ),
    (
        "Economic Times",
        "https://economictimes.indiatimes.com/industry/banking/finance/rssfeeds/13358259.cms",
    ),
]


# ============================================================
# HELPERS
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = unescape(text)

    # Remove HTML tags
    import re
    text = re.sub(r"<[^>]+>", " ", text)

    # Clean whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def fetch_url(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; MorningNewsBot/1.0)"
            )
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def parse_date(date_string):
    if not date_string:
        return None

    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(date_string)
    except Exception:
        return None


# ============================================================
# RSS READER
# ============================================================

def fetch_feed(source, url):
    print(f"Fetching: {source}")

    try:
        xml_data = fetch_url(url)
        root = ET.fromstring(xml_data)

        stories = []

        # Standard RSS
        for item in root.findall(".//item"):

            title = clean_text(
                item.findtext("title", default="")
            )

            link = item.findtext("link", default="").strip()

            description = clean_text(
                item.findtext("description", default="")
            )

            pub_date = item.findtext(
                "pubDate",
                default=""
            )

            published = parse_date(pub_date)

            if not title or not link:
                continue

            stories.append(
                {
                    "source": source,
                    "title": title,
                    "description": description,
                    "link": link,
                    "published": published,
                }
            )

        print(f"  Found {len(stories)} stories")

        return stories[:MAX_STORIES_PER_FEED]

    except Exception as e:
        print(f"  ERROR: {e}")
        return []


# ============================================================
# COLLECT NEWS
# ============================================================

def collect_news():

    all_stories = []

    for source, url in FEEDS:
        stories = fetch_feed(source, url)
        all_stories.extend(stories)

    # --------------------------------------------------------
    # Remove duplicate headlines
    # --------------------------------------------------------

    unique = {}
    for story in all_stories:

        key = story["title"].lower()

        if key not in unique:
            unique[key] = story

    stories = list(unique.values())

    # --------------------------------------------------------
    # Sort newest first
    # --------------------------------------------------------

    def sort_key(story):
        if story["published"]:
            return story["published"]

        return datetime.min.replace(tzinfo=timezone.utc)

    stories.sort(
        key=sort_key,
        reverse=True
    )

    # --------------------------------------------------------
    # Keep recent stories where possible
    # --------------------------------------------------------

    cutoff = datetime.now(timezone.utc) - timedelta(hours=30)

    recent = []

    for story in stories:

        published = story["published"]

        if published:
            try:
                if published.tzinfo is None:
                    published = published.replace(
                        tzinfo=timezone.utc
                    )

                if published >= cutoff:
                    recent.append(story)

            except Exception:
                pass

    # If RSS dates aren't available, use latest stories
    if len(recent) < 10:
        recent = stories

    return recent[:MAX_STORIES_TO_GEMINI]


# ============================================================
# GEMINI
# ============================================================

def ask_gemini(stories):

    print("\nSending ONE request to Gemini...")

    news_text = ""

    for i, story in enumerate(stories, 1):

        news_text += (
            f"\nSTORY {i}\n"
            f"Source: {story['source']}\n"
            f"Headline: {story['title']}\n"
            f"Details: {story['description'][:500]}\n"
            f"Link: {story['link']}\n"
        )

    prompt = f"""
You are my personal morning current-affairs editor.

I am preparing for Indian banking/PO exams and want a very short
morning briefing.

IMPORTANT RULES:

1. Use ONLY the news stories supplied below.
2. Do NOT use outside knowledge.
3. Do NOT invent facts.
4. Ignore duplicate stories.
5. Select the most important 8-10 stories.
6. Prioritize:
   - RBI and banking
   - Indian economy
   - Monetary policy
   - Inflation
   - GDP
   - Government economic policy
   - Financial markets
   - Business and companies
   - Major global economic developments
   - Important general awareness/current affairs useful for banking exams
7. Avoid sports, entertainment, celebrity news and trivial stories.
8. If a story is not useful or important, skip it.
9. Keep everything concise.
10. Preserve the original article links exactly.

For every selected story use this format:

📰 HEADLINE
What happened: 1-2 simple sentences.
Why it matters: 1 short sentence.
Source: <original link>

At the top write:

🌅 MORNING NEWS — {datetime.now().strftime("%d %b %Y")}

Then finish with:

🎯 TODAY'S MUST-KNOW
Give 3 very short bullet points containing the most exam-relevant facts.

Keep the entire response below 3500 characters so it fits into ONE Telegram message.

Here are today's supplied stories:

{news_text}
"""

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{GEMINI_MODEL}:generateContent"
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1800
        }
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        method="POST",
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=60
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

        text = (
            data["candidates"][0]
            ["content"]["parts"][0]["text"]
        )

        print("Gemini response received.")

        return text.strip()

    except Exception as e:

        print(f"Gemini ERROR: {e}")

        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    print("\nSending Telegram message...")

    # Telegram allows up to 4096 characters.
    # Keep a little safety margin.
    if len(message) > 3900:
        message = message[:3890] + "\n\n…"

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            result = json.loads(
                response.read().decode("utf-8")
            )

        if result.get("ok"):
            print("Telegram message sent successfully.")
        else:
            print("Telegram ERROR:", result)

    except Exception as e:
        print(f"Telegram ERROR: {e}")
        raise


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("🌅 MORNING NEWS BOT")
    print("=" * 60)

    stories = collect_news()

    print(
        f"\nTotal stories selected for Gemini: "
        f"{len(stories)}"
    )

    if not stories:
        print("No news stories found.")
        return

    briefing = ask_gemini(stories)

    if not briefing:
        print("Gemini failed. Sending fallback headlines.")

        briefing = (
            "🌅 MORNING NEWS\n\n"
            "Gemini summary unavailable.\n\n"
        )

        for story in stories[:10]:
            briefing += (
                f"📰 {story['title']}\n"
                f"{story['source']}\n"
                f"{story['link']}\n\n"
            )

    send_telegram(briefing)

    print("\n✅ MORNING NEWS BOT FINISHED")


if __name__ == "__main__":
    main()
