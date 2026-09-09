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
# CONFIGURATION
# ============================================================

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["NEWS_TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["NEWS_TELEGRAM_CHAT_ID"]

GEMINI_MODEL = "gemini-3.6-flash"

MAX_STORIES_PER_FEED = 6
MAX_STORIES_TO_GEMINI = 20

TELEGRAM_MAX_LENGTH = 3900


# ============================================================
# NEWS SOURCES
# ONLY BUSINESSLINE + ECONOMIC TIMES
# ============================================================

FEEDS = [

    # --------------------------------------------------------
    # THE HINDU BUSINESSLINE
    # --------------------------------------------------------

    (
        "BusinessLine",
        "https://www.thehindubusinessline.com/news/feeder/default.rss"
    ),

    (
        "BusinessLine",
        "https://www.thehindubusinessline.com/money-and-banking/feeder/default.rss"
    ),

    (
        "BusinessLine",
        "https://www.thehindubusinessline.com/economy/macro-economy/feeder/default.rss"
    ),

    (
        "BusinessLine",
        "https://www.thehindubusinessline.com/economy/feeder/default.rss"
    ),

    (
        "BusinessLine",
        "https://www.thehindubusinessline.com/markets/feeder/default.rss"
    ),

    # --------------------------------------------------------
    # ECONOMIC TIMES
    # --------------------------------------------------------

    (
        "Economic Times",
        "https://economictimes.indiatimes.com/rssfeedstopstories.cms"
    ),

    (
        "Economic Times",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
    ),

    (
        "Economic Times",
        "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms"
    ),

    (
        "Economic Times",
        "https://economictimes.indiatimes.com/industry/banking/finance/rssfeeds/13358259.cms"
    ),
]


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = unescape(text)

    # Remove HTML tags
    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    # Remove excessive whitespace
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# FETCH URL
# ============================================================

def fetch_url(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
            "Mozilla/5.0 MorningNewsBot/1.0"
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

        return parsedate_to_datetime(
            date_string
        )

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

        root = ET.fromstring(
            xml_data
        )

        stories = []

        for item in root.findall(
            ".//item"
        ):

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

            published = parse_date(
                pub_date
            )

            if not title or not link:
                continue

            stories.append({
                "source": source,
                "title": title,
                "description": description,
                "link": link,
                "published": published
            })

        print(
            f"Found {len(stories)} stories"
        )

        return stories[
            :MAX_STORIES_PER_FEED
        ]

    except Exception as e:

        print(
            f"RSS ERROR: {e}"
        )

        return []


# ============================================================
# COLLECT NEWS
# ============================================================

def collect_news():

    all_stories = []

    for source, url in FEEDS:

        stories = fetch_feed(
            source,
            url
        )

        all_stories.extend(
            stories
        )

    print(
        f"\nTotal RSS stories collected: "
        f"{len(all_stories)}"
    )

    # --------------------------------------------------------
    # Remove duplicate headlines
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

    stories = list(
        unique.values()
    )

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
    # Prefer news from the last 30 hours
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

            recent.append(
                story
            )

    # If dates aren't useful,
    # use the newest available stories.

    if len(recent) < 8:

        recent = stories

    recent = recent[
        :MAX_STORIES_TO_GEMINI
    ]

    print(
        f"Stories going to Gemini: "
        f"{len(recent)}"
    )

    return recent


# ============================================================
# GEMINI
# ============================================================

def ask_gemini(stories):

    print(
        "\nSending ONE request to Gemini..."
    )

    news_text = ""

    for index, story in enumerate(
        stories,
        1
    ):

        news_text += (
            f"\n--- STORY {index} ---\n"
            f"Source: {story['source']}\n"
            f"Headline: {story['title']}\n"
            f"Details: "
            f"{story['description'][:450]}\n"
            f"Link: {story['link']}\n"
        )

    # --------------------------------------------------------
    # Current date in IST
    # --------------------------------------------------------

    ist = timezone(
        timedelta(
            hours=5,
            minutes=30
        )
    )

    today = datetime.now(
        ist
    ).strftime(
        "%d %b %Y"
    )

    # --------------------------------------------------------
    # PROMPT
    # --------------------------------------------------------

    prompt = f"""
You are my personal morning current-affairs editor.

I am preparing for Indian banking and PO exams.

Today is {today}.

Use ONLY the supplied news stories.

DO NOT:
- use outside information
- invent facts
- invent numbers
- add stories not supplied
- repeat duplicate stories

SELECT ONLY 6 TO 8 IMPORTANT STORIES.

PRIORITY:
1. RBI
2. Banking
3. Monetary policy
4. Inflation
5. GDP
6. Indian economy
7. Government economic policy
8. Financial markets
9. Important Indian businesses
10. Major global economic developments
11. Important banking-exam current affairs

SKIP:
- sports
- entertainment
- celebrities
- lifestyle
- trivial stories
- minor local news

FORMAT EXACTLY LIKE THIS:

🌅 MORNING NEWS — {today}

📰 Headline
What happened: ONE short sentence.
Why it matters: ONE short sentence.
Source: original article link

Repeat for 6 to 8 stories.

Then:

🎯 TODAY'S MUST-KNOW
• One important exam fact
• One important exam fact
• One important exam fact

VERY IMPORTANT LENGTH RULE:

The COMPLETE response MUST be below 2500 characters.

Aim for approximately 2000-2300 characters.

Do NOT exceed 2500 characters.

Keep sentences extremely short.

Do not add an introduction or conclusion.

Keep the original article links exactly as supplied.

SUPPLIED NEWS:

{news_text}
"""

    # --------------------------------------------------------
    # Gemini API
    # --------------------------------------------------------

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
            "maxOutputTokens": 1400
        }
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(
            payload
        ).encode("utf-8"),
        headers={
            "Content-Type":
            "application/json",

            "x-goog-api-key":
            GEMINI_API_KEY
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=90
        ) as response:

            data = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

        candidates = data.get(
            "candidates",
            []
        )

        if not candidates:

            print(
                "Gemini returned no candidates."
            )

            print(
                json.dumps(
                    data,
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
                "Gemini returned no text."
            )

            return None

        text = parts[0].get(
            "text",
            ""
        ).strip()

        print(
            "Gemini response received."
        )

        print(
            f"Gemini response length: "
            f"{len(text)} characters"
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
# SAFELY SHORTEN A LONG GEMINI RESPONSE
# ============================================================

def fit_message(message):

    if len(message) <= TELEGRAM_MAX_LENGTH:

        return message

    print(
        f"Gemini response is too long: "
        f"{len(message)} characters"
    )

    print(
        "Shortening at story boundaries..."
    )

    # Split into blocks beginning with 📰
    blocks = re.split(
        r"(?=📰)",
        message
    )

    result = ""

    for block in blocks:

        if not block.strip():
            continue

        candidate = (
            result
            + ("\n" if result else "")
            + block.strip()
        )

        if len(candidate) > 3800:

            break

        result = candidate

    # If the must-know section exists,
    # try to preserve it.

    must_know = ""

    marker = "🎯 TODAY'S MUST-KNOW"

    if marker in message:

        must_know = message[
            message.index(marker):
        ].strip()

    if must_know:

        candidate = (
            result
            + "\n\n"
            + must_know
        )

        if len(candidate) <= 3900:

            result = candidate

    # Final safety check.
    # This should almost never be needed.

    if len(result) > 3900:

        result = result[:3900]

        # Remove incomplete final line.
        if "\n" in result:

            result = result[
                :result.rfind("\n")
            ]

    return result.strip()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    print(
        "\nSending ONE Telegram message..."
    )

    message = fit_message(
        message
    )

    print(
        f"Final Telegram length: "
        f"{len(message)} characters"
    )

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(
            payload
        ).encode("utf-8"),
        headers={
            "Content-Type":
            "application/json"
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            result = json.loads(
                response.read().decode(
                    "utf-8"
                )
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

    ist = timezone(
        timedelta(
            hours=5,
            minutes=30
        )
    )

    today = datetime.now(
        ist
    ).strftime(
        "%d %b %Y"
    )

    message = (
        f"🌅 MORNING NEWS — {today}\n\n"
        "Gemini summary unavailable.\n\n"
    )

    for story in stories[:7]:

        block = (
            f"📰 {story['title']}\n"
            f"Source: {story['source']}\n"
            f"{story['link']}\n\n"
        )

        if len(message + block) > 3800:
            break

        message += block

    return message.strip()


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("🌅 MORNING NEWS BOT")
    print("=" * 60)

    # --------------------------------------------------------
    # STEP 1 — Collect news
    # --------------------------------------------------------

    stories = collect_news()

    if not stories:

        raise RuntimeError(
            "No RSS stories were collected."
        )

    # --------------------------------------------------------
    # STEP 2 — ONE Gemini request
    # --------------------------------------------------------

    briefing = ask_gemini(
        stories
    )

    # --------------------------------------------------------
    # STEP 3 — Fallback if Gemini fails
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
    # STEP 4 — ONE Telegram message
    # --------------------------------------------------------

    success = send_telegram(
        briefing
    )

    if not success:

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
