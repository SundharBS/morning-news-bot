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

MAX_STORIES_PER_FEED = 6
MAX_STORIES_TO_GEMINI = 20
TELEGRAM_LIMIT = 3900


# ============================================================
# NEWS SOURCES
# ONLY THE HINDU BUSINESSLINE + ECONOMIC TIMES
# ============================================================

FEEDS = [

    # --------------------------------------------------------
    # THE HINDU BUSINESSLINE
    # --------------------------------------------------------

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
# HELPERS
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

    # Remove excessive spaces
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
# RSS READER
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
    # Prefer news from the last 30 hours
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

    # If too few recent stories,
    # use the latest available stories.

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
            f"Article details: "
            f"{story['description'][:750]}\n"
        )

    # --------------------------------------------------------
    # Indian Standard Time
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
You are my personal DAILY CURRENT AFFAIRS EDITOR.

I want to become broadly aware of important current affairs.

I am also preparing for Indian banking/PO exams, but this is
NOT a banking-only briefing.

Today is {today}.

You have news from ONLY:
- The Hindu BusinessLine
- Economic Times

Use ONLY the supplied news items.

DO NOT:
- use outside information
- invent facts
- invent numbers
- invent statistics
- invent dates
- repeat the same event
- include a story that was not supplied

============================================================
WHAT TO SELECT
============================================================

Select the 6-8 MOST IMPORTANT developments of the day.

Do NOT force every category into the briefing.

Choose stories based on actual importance.

Consider ALL of these areas:

🇮🇳 India
🌍 World / geopolitics
💰 Economy / business / markets
🏦 Banking / RBI / financial policy
🤖 Technology / AI
🚀 Science / space
🏛️ Government / policy / courts
🌱 Environment / climate
🏅 Major sports and major international events
📚 Other important general-awareness developments

A major geopolitical event is more important than a minor
banking announcement.

A major scientific breakthrough is more important than a
routine corporate announcement.

A major Indian government decision is more important than
a minor market movement.

Use your judgement.

============================================================
NUMBERS ARE IMPORTANT
============================================================

Whenever the supplied article contains meaningful numbers,
PRESERVE THEM.

Examples:

- ₹ crore / ₹ lakh crore
- $ billion / $ million
- percentages
- interest rates
- GDP growth
- inflation
- unemployment
- oil prices
- market levels
- number of countries
- number of people affected
- dates
- targets
- election numbers
- production figures
- investment amounts
- trade figures

Include important numbers in the "What happened" section.

DO NOT invent or estimate numbers.

Do not overload a story with unnecessary figures.

============================================================
EXPLANATION IS THE MAIN PURPOSE
============================================================

For every selected story, explain:

1. WHAT HAPPENED
2. WHY IT MATTERS

The reader should understand the event without opening
the newspaper.

Do NOT merely rewrite the headline.

============================================================
OUTPUT FORMAT
============================================================

Start with:

🌅 MORNING CURRENT AFFAIRS
{today}

Then use:

📰 [Headline]

What happened: [2 clear sentences explaining the event.
Include important numbers/names/dates when relevant.]

Why it matters: [1 clear sentence explaining significance.]

Source: Economic Times

OR

Source: The Hindu BusinessLine

Then the next story.

At the end:

🎯 TODAY'S MUST-KNOW

• [Important fact]
• [Important fact]
• [Important fact]

============================================================
IMPORTANT OUTPUT RULES
============================================================

- DO NOT include article URLs.
- DO NOT include hyperlinks.
- DO NOT write any URL.
- Only write the publication name as the source.
- The summary is more important than the headline.
- Use simple language.
- Explain acronyms when necessary.
- Keep important numbers.
- Do not make every story about banking.
- Do not force categories.
- No introduction before the first story.
- No conclusion after Must-Know.

============================================================
LENGTH
============================================================

Keep the complete response between approximately
2400 and 3000 characters.

NEVER exceed 3200 characters.

Aim for 6-8 strong stories rather than many weak stories.

============================================================
SUPPLIED NEWS
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
            "maxOutputTokens": 1800
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
# TELEGRAM MESSAGE PREPARATION
# ============================================================

def prepare_message(message):

    # Remove URLs if Gemini accidentally includes them.

    message = re.sub(
        r"https?://\S+",
        "",
        message
    )

    # Clean spaces before line breaks.

    message = re.sub(
        r"[ \t]+\n",
        "\n",
        message
    )

    message = message.strip()

    # --------------------------------------------------------
    # Keep message below Telegram's limit.
    # Cut only at story boundaries.
    # --------------------------------------------------------

    if len(message) <= TELEGRAM_LIMIT:

        return message

    print(
        f"Message too long: "
        f"{len(message)} characters"
    )

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

        if len(candidate) > 3300:

            break

        result = candidate

    if must_know:

        candidate = (
            result
            + "\n\n"
            + must_know
        )

        if len(candidate) <= 3800:

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
            "Telegram error:"
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

    for story in stories[:6]:

        block = (
            f"📰 {story['title']}\n\n"
            f"What happened: "
            f"{story['description'][:350]}\n\n"
            f"Source: {story['source']}\n\n"
        )

        if len(
            message + block
        ) > 3600:

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
