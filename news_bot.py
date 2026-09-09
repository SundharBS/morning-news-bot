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
MAX_STORIES_TO_GEMINI = 24

TELEGRAM_LIMIT = 4096


# ============================================================
# NEWS SOURCES
# ONLY THE HINDU BUSINESSLINE + ECONOMIC TIMES
# ============================================================

FEEDS = [

    # ---------------- BUSINESSLINE ----------------

    (
        "The Hindu BusinessLine",
        "https://www.thehindubusinessline.com/news/feeder/default.rss"
    ),

    (
        "The Hindu BusinessLine",
        "https://www.thehindubusinessline.com/money-and-banking/feeder/default.rss"
    ),

    (
        "The Hindu BusinessLine",
        "https://www.thehindubusinessline.com/economy/macro-economy/feeder/default.rss"
    ),

    (
        "The Hindu BusinessLine",
        "https://www.thehindubusinessline.com/economy/feeder/default.rss"
    ),

    (
        "The Hindu BusinessLine",
        "https://www.thehindubusinessline.com/markets/feeder/default.rss"
    ),

    # ---------------- ECONOMIC TIMES ----------------

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
# HELPERS
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = unescape(text)

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


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
# RSS FEED
# ============================================================

def fetch_feed(source, url):

    print(f"\nFetching: {source}")

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
        f"\nTotal stories collected: "
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

        date = story["published"]

        if date is None:

            return datetime.min.replace(
                tzinfo=timezone.utc
            )

        if date.tzinfo is None:

            date = date.replace(
                tzinfo=timezone.utc
            )

        return date

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

        date = story["published"]

        if date is None:
            continue

        if date.tzinfo is None:

            date = date.replace(
                tzinfo=timezone.utc
            )

        if date >= cutoff:

            recent.append(
                story
            )

    if len(recent) < 10:

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
            f"Details: {story['description'][:800]}\n"
        )

    # --------------------------------------------------------
    # IST
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
You are my personal morning CURRENT AFFAIRS EDITOR.

I want to be broadly aware of the most important things
happening in India and around the world.

I am also preparing for banking/PO exams, but this is NOT
a banking-only briefing.

Today: {today}

SOURCE LIMIT:

Use ONLY the supplied stories from:

1. The Hindu BusinessLine
2. Economic Times

Do NOT use outside knowledge.

Do NOT invent facts, numbers, dates or statistics.

============================================================
SELECT THE MOST IMPORTANT NEWS
============================================================

Choose 8 to 10 genuinely important stories.

Do NOT force every category to appear.

Consider importance across:

🇮🇳 India
🌍 World / geopolitics
💰 Economy / business / markets
🏦 Banking / RBI / financial policy
🤖 Technology / AI
🚀 Science / space
🏛️ Government / policy / courts
🌱 Environment / climate
🏅 Major sports
📚 Other major general-awareness developments

A major world event is more important than a routine
banking announcement.

A major scientific development is more important than a
minor corporate announcement.

A major Indian government decision is more important than
a small market movement.

Use judgement.

============================================================
NUMBERS AND DATA
============================================================

Numbers are IMPORTANT.

Whenever the supplied article contains meaningful data,
include it in the summary.

Examples:

₹ crore
₹ lakh crore
$ billion
percentages
interest rates
GDP growth
inflation
oil prices
stock-market levels
number of countries
number of people
investment amounts
trade figures
targets
dates
production figures

Preserve important numbers exactly as provided.

NEVER invent or estimate numbers.

============================================================
EXPLAIN THE NEWS
============================================================

The reader should understand the story without opening
the newspaper.

DO NOT merely rewrite the headline.

For each story provide:

What happened:
2-3 clear sentences explaining the actual event.
Include important names, numbers, dates and facts.

Why it matters:
1 clear sentence explaining the significance.

============================================================
OUTPUT FORMAT
============================================================

Start:

🌅 MORNING CURRENT AFFAIRS
{today}

Then:

📰 [Headline]

What happened: [2-3 useful sentences.]

Why it matters: [1 useful sentence.]

Source: Economic Times

OR

Source: The Hindu BusinessLine

Then continue with the next story.

At the end:

🎯 TODAY'S MUST-KNOW

• [Important fact]
• [Important fact]
• [Important fact]

============================================================
IMPORTANT
============================================================

DO NOT include article URLs.

DO NOT include hyperlinks.

DO NOT include raw links.

Only write:

Source: Economic Times

or:

Source: The Hindu BusinessLine

The space saved from removing URLs MUST be used for
better explanations and useful data.

Do not waste characters on introductions.

Do not waste characters on conclusions.

Use simple language.

Avoid unnecessary repetition.

============================================================
LENGTH
============================================================

This is VERY IMPORTANT.

Telegram allows approximately 4096 characters.

Aim for approximately 3500-3800 characters.

DO NOT exceed 3800 characters.

Do NOT make the briefing artificially short.

Give the reader useful explanations.

8-10 strong stories are preferred.

============================================================
SUPPLIED STORIES
============================================================

{news_text}
"""

    # --------------------------------------------------------
    # GEMINI API
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
            "maxOutputTokens": 2200
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
# PREPARE TELEGRAM MESSAGE
# ============================================================

def prepare_message(message):

    # --------------------------------------------------------
    # Remove accidental URLs.
    # --------------------------------------------------------

    message = re.sub(
        r"https?://\S+",
        "",
        message
    )

    # --------------------------------------------------------
    # Clean whitespace.
    # --------------------------------------------------------

    message = re.sub(
        r"[ \t]+\n",
        "\n",
        message
    )

    message = message.strip()

    # --------------------------------------------------------
    # If already within limit, send it.
    # --------------------------------------------------------

    if len(message) <= 3900:

        return message

    print(
        f"Message too long: "
        f"{len(message)} characters"
    )

    print(
        "Reducing at complete story boundaries..."
    )

    # --------------------------------------------------------
    # Split at headlines.
    # --------------------------------------------------------

    blocks = re.split(
        r"(?=📰)",
        message
    )

    result = ""

    must_know = ""

    for block in blocks:

        block = block.strip()

        if not block:
            continue

        # Keep Must-Know separately.

        if block.startswith(
            "🎯 TODAY'S MUST-KNOW"
        ):

            must_know = block

            continue

        candidate = (
            result
            + ("\n\n" if result else "")
            + block
        )

        # Keep a safe margin.

        if len(candidate) > 3600:

            break

        result = candidate

    # --------------------------------------------------------
    # Add Must-Know if it fits.
    # --------------------------------------------------------

    if must_know:

        candidate = (
            result
            + "\n\n"
            + must_know
        )

        if len(candidate) <= 3900:

            result = candidate

    return result.strip()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    print(
        "\nSending ONE Telegram message..."
    )

    message = prepare_message(
        message
    )

    print(
        f"Final message length: "
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
        f"🌅 MORNING CURRENT AFFAIRS\n"
        f"{today}\n\n"
        "Gemini summary unavailable.\n\n"
    )

    for story in stories[:8]:

        block = (
            f"📰 {story['title']}\n\n"
            f"What happened: "
            f"{story['description'][:450]}\n\n"
            f"Source: {story['source']}\n\n"
        )

        if len(
            message + block
        ) > 3700:

            break

        message += block

    return message.strip()


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("🌅 MORNING CURRENT AFFAIRS BOT")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. Collect news
    # --------------------------------------------------------

    stories = collect_news()

    if not stories:

        raise RuntimeError(
            "No RSS stories were collected."
        )

    # --------------------------------------------------------
    # 2. ONE Gemini request
    # --------------------------------------------------------

    briefing = ask_gemini(
        stories
    )

    # --------------------------------------------------------
    # 3. Fallback
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

    success = send_telegram(
        briefing
    )

    if not success:

        raise RuntimeError(
            "Telegram message could not be sent."
        )

    print("\n" + "=" * 60)
    print("✅ MORNING CURRENT AFFAIRS BOT FINISHED")
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
