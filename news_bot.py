import os
import json
import re
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape


# ============================================================
# CONFIG
# ============================================================

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["NEWS_TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["NEWS_TELEGRAM_CHAT_ID"]

GEMINI_MODEL = "gemini-3.6-flash"

MAX_STORIES_PER_FEED = 7
MAX_STORIES_TO_GEMINI = 30

FEEDS = [

    # ========================================================
    # THE HINDU BUSINESSLINE
    # ========================================================

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

    # ========================================================
    # ECONOMIC TIMES
    # ========================================================

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
# TEXT CLEANING
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = unescape(text)

    # Remove HTML
    text = re.sub(r"<[^>]+>", " ", text)

    # Remove excessive whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# FETCH URL
# ============================================================

def fetch_url(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 MorningNewsBot/1.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        return response.read()


# ============================================================
# PARSE DATE
# ============================================================

def parse_date(date_string):

    if not date_string:
        return None

    try:
        return parsedate_to_datetime(date_string)
    except Exception:
        return None


# ============================================================
# FETCH RSS FEED
# ============================================================

def fetch_feed(source, url):

    print(f"\nFetching: {source}")
    print(url)

    try:

        xml_data = fetch_url(url)

        root = ET.fromstring(xml_data)

        stories = []

        for item in root.findall(".//item"):

            title = clean_text(
                item.findtext(
                    "title",
                    default=""
                )
            )

            link = item.findtext(
                "link",
                default=""
            ).strip()

            description = clean_text(
                item.findtext(
                    "description",
                    default=""
                )
            )

            pub_date = item.findtext(
                "pubDate",
                default=""
            )

            published = parse_date(pub_date)

            if not title or not link:
                continue

            stories.append({
                "source": source,
                "title": title,
                "description": description,
                "link": link,
                "published": published
            })

        print(f"Found {len(stories)} stories")

        return stories[:MAX_STORIES_PER_FEED]

    except Exception as e:

        print(f"RSS ERROR: {e}")

        return []


# ============================================================
# COLLECT ALL NEWS
# ============================================================

def collect_news():

    all_stories = []

    for source, url in FEEDS:

        stories = fetch_feed(
            source,
            url
        )

        all_stories.extend(stories)

    print(
        f"\nTotal RSS stories collected: "
        f"{len(all_stories)}"
    )

    # --------------------------------------------------------
    # Remove duplicates
    # --------------------------------------------------------

    unique = {}

    for story in all_stories:

        key = re.sub(
            r"[^a-z0-9]",
            "",
            story["title"].lower()
        )

        if key not in unique:
            unique[key] = story

    stories = list(unique.values())

    # --------------------------------------------------------
    # Sort newest first
    # --------------------------------------------------------

    def sort_key(story):

        published = story["published"]

        if published is None:
            return datetime.min.replace(
                tzinfo=timezone.utc
            )

        if published.tzinfo is None:
            published = published.replace(
                tzinfo=timezone.utc
            )

        return published

    stories.sort(
        key=sort_key,
        reverse=True
    )

    # --------------------------------------------------------
    # Prefer last 30 hours
    # --------------------------------------------------------

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(hours=30)
    )

    recent = []

    for story in stories:

        published = story["published"]

        if published is None:
            continue

        if published.tzinfo is None:
            published = published.replace(
                tzinfo=timezone.utc
            )

        if published >= cutoff:
            recent.append(story)

    # If RSS dates are poor, use latest stories
    if len(recent) < 10:
        recent = stories

    recent = recent[:MAX_STORIES_TO_GEMINI]

    print(
        f"Stories going to Gemini: "
        f"{len(recent)}"
    )

    return recent


# ============================================================
# GEMINI
# ============================================================

def ask_gemini(stories):

    print("\nSending ONE request to Gemini...")

    news_text = ""

    for index, story in enumerate(stories, 1):

        news_text += (
            f"\n--- STORY {index} ---\n"
            f"Source: {story['source']}\n"
            f"Headline: {story['title']}\n"
            f"Details: {story['description'][:600]}\n"
            f"Link: {story['link']}\n"
        )

    today = datetime.now(
        timezone(timedelta(hours=5, minutes=30))
    ).strftime("%d %b %Y")

    prompt = f"""
You are preparing a concise morning current-affairs briefing
for an Indian banking/PO exam aspirant.

Date: {today}

IMPORTANT:

- Use ONLY the supplied news stories.
- Do NOT use outside information.
- Do NOT invent facts.
- Do NOT make up numbers.
- Ignore duplicate stories.
- Select the 8 to 10 most important stories.

PRIORITY:

1. RBI
2. Banking and financial institutions
3. Monetary policy
4. Inflation
5. GDP and economic growth
6. Indian economy
7. Government economic policy
8. Financial markets
9. Major Indian businesses
10. Major global economic developments
11. Important general awareness useful for banking exams

SKIP:

- Sports
- Entertainment
- Celebrity news
- Lifestyle
- Minor local stories
- Unimportant corporate announcements

FORMAT:

🌅 MORNING NEWS — {today}

📰 Headline
What happened: 1-2 simple sentences.
Why it matters: 1 short sentence.
Source: original article link

Repeat for the selected stories.

At the end:

🎯 TODAY'S MUST-KNOW

• Important exam fact
• Important exam fact
• Important exam fact

Keep the complete response below 3500 characters.

Preserve the supplied article links exactly.

SUPPLIED STORIES:

{news_text}
"""

    # Google's documented REST generateContent endpoint.
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
            "x-goog-api-key": GEMINI_API_KEY
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=90
        ) as response:

            response_data = json.loads(
                response.read().decode("utf-8")
            )

        candidates = response_data.get(
            "candidates",
            []
        )

        if not candidates:
            print(
                "Gemini returned no candidates."
            )

            print(
                json.dumps(
                    response_data,
                    indent=2
                )
            )

            return None

        parts = (
            candidates[0]
            .get("content", {})
            .get("parts", [])
        )

        if not parts:
            print(
                "Gemini response contained no text."
            )

            print(
                json.dumps(
                    response_data,
                    indent=2
                )
            )

            return None

        text = parts[0].get(
            "text",
            ""
        ).strip()

        print(
            "Gemini response received successfully."
        )

        return text

    except urllib.error.HTTPError as e:

        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        print(
            f"\nGEMINI HTTP ERROR {e.code}"
        )

        print(error_body)

        return None

    except Exception as e:

        print(
            f"\nGEMINI ERROR: {e}"
        )

        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    print("\nSending Telegram message...")

    # Telegram maximum is 4096 characters.
    if len(message) > 3900:

        message = (
            message[:3890]
            + "\n\n..."
        )

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
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

            print(
                "Telegram message sent successfully."
            )

            return True

        print(
            "Telegram returned an error:"
        )

        print(
            json.dumps(
                result,
                indent=2
            )
        )

        return False

    except urllib.error.HTTPError as e:

        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        print(
            f"\nTELEGRAM HTTP ERROR {e.code}"
        )

        print(error_body)

        return False

    except Exception as e:

        print(
            f"\nTELEGRAM ERROR: {e}"
        )

        return False


# ============================================================
# FALLBACK
# ============================================================

def create_fallback(stories):

    today = datetime.now(
        timezone(timedelta(hours=5, minutes=30))
    ).strftime("%d %b %Y")

    message = (
        f"🌅 MORNING NEWS — {today}\n\n"
        "Gemini summary was unavailable.\n\n"
        "Latest headlines:\n\n"
    )

    for story in stories[:8]:

        message += (
            f"📰 {story['title']}\n"
            f"{story['source']}\n"
            f"{story['link']}\n\n"
        )

    return message


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("🌅 MORNING NEWS BOT")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. Get news
    # --------------------------------------------------------

    stories = collect_news()

    if not stories:

        print(
            "\nNo RSS stories were collected."
        )

        return

    # --------------------------------------------------------
    # 2. ONE Gemini request
    # --------------------------------------------------------

    briefing = ask_gemini(
        stories
    )

    # --------------------------------------------------------
    # 3. Fallback if Gemini fails
    # --------------------------------------------------------

    if not briefing:

        print(
            "\nGemini failed."
        )

        print(
            "Using fallback headlines."
        )

        briefing = create_fallback(
            stories
        )

    # --------------------------------------------------------
    # 4. ONE Telegram message
    # --------------------------------------------------------

    telegram_success = send_telegram(
        briefing
    )

    if not telegram_success:

        raise RuntimeError(
            "Telegram message could not be sent."
        )

    print("\n" + "=" * 60)
    print("✅ MORNING NEWS BOT FINISHED")
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
