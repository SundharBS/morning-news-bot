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

# Keep the input small to save tokens.
MAX_STORIES_PER_FEED = 5
MAX_STORIES_TO_GEMINI = 18

# Telegram maximum is 4096 characters.
# We deliberately stay below it.
TARGET_MESSAGE_LENGTH = 3700


# ============================================================
# RSS SOURCES
# ONLY BUSINESSLINE + ECONOMIC TIMES
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
# TEXT CLEANING
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = unescape(text)

    # Remove HTML.
    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    # Remove URLs from article excerpts.
    text = re.sub(
        r"https?://\S+",
        "",
        text
    )

    # Normalize whitespace.
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
            "Mozilla/5.0 MorningCurrentAffairsBot/1.0"
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

def parse_date(value):

    if not value:
        return None

    try:

        return parsedate_to_datetime(
            value
        )

    except Exception:

        return None


# ============================================================
# FETCH ONE RSS FEED
# ============================================================

def fetch_feed(source, url):

    print(
        f"Fetching: {source}"
    )

    try:

        xml_data = fetch_url(
            url
        )

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

            if not title:
                continue

            stories.append({

                "source":
                source,

                "title":
                title,

                # Important:
                # Only send a short excerpt to Gemini.
                # This saves input tokens.
                "description":
                description[:650],

                "published":
                published

            })

        print(
            f"  {len(stories)} stories found"
        )

        return stories[
            :MAX_STORIES_PER_FEED
        ]

    except Exception as e:

        print(
            f"  RSS ERROR: {e}"
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
        f"\nTotal RSS stories: "
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

    def date_key(story):

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
        key=date_key,
        reverse=True
    )

    # --------------------------------------------------------
    # Prefer recent stories
    # --------------------------------------------------------

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(hours=36)
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

    # If RSS dates are poor, use newest stories anyway.
    if len(recent) < 10:

        recent = stories

    # --------------------------------------------------------
    # Limit input
    # --------------------------------------------------------

    recent = recent[
        :MAX_STORIES_TO_GEMINI
    ]

    print(
        f"Stories sent to Gemini: "
        f"{len(recent)}"
    )

    return recent


# ============================================================
# GEMINI
# ============================================================

def ask_gemini(stories):

    print(
        "\nPreparing ONE Gemini request..."
    )

    # --------------------------------------------------------
    # Build compact input
    # --------------------------------------------------------

    news_text = ""

    for i, story in enumerate(
        stories,
        1
    ):

        news_text += (
            f"\nSTORY {i}\n"
            f"Source: {story['source']}\n"
            f"Headline: {story['title']}\n"
            f"Excerpt: {story['description']}\n"
        )

    # --------------------------------------------------------
    # Indian date
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
        "%d %B %Y"
    )

    # --------------------------------------------------------
    # TOKEN-EFFICIENT PROMPT
    # --------------------------------------------------------

    prompt = f"""
Create my morning current-affairs briefing for {today}.

Use ONLY the supplied stories from:
- The Hindu BusinessLine
- Economic Times

Do NOT use outside knowledge.
Do NOT invent facts, numbers, dates or context.

PURPOSE:
Broad general awareness + banking/PO exam preparation.

Choose the 8 most important developments.
Do not force categories.

Prioritise genuinely significant:
- India
- world/geopolitics
- government/policy
- economy/business
- markets
- banking/RBI
- technology/AI
- science/space
- environment/climate
- major sports/events

DEPTH:
Do NOT give one-line summaries.

For every story write:

📰 HEADLINE

What happened:
2-3 informative sentences explaining the actual development,
including important people, organisations, decisions and context
available in the supplied excerpt.

Why it matters:
1 sentence explaining significance.

Source: Economic Times

OR

Source: The Hindu BusinessLine

IMPORTANT NUMBERS:
Preserve useful numbers from the supplied material:
₹ crore, ₹ lakh crore, $, %, GDP, inflation, rates, market levels,
investment amounts, dates, targets, country counts, etc.

Never invent numbers.

OUTPUT:
Start with:

🌅 MORNING CURRENT AFFAIRS
{today}

End with:

🎯 TODAY'S MUST-KNOW

• 4-5 important facts from the briefing

NO URLs.
NO hyperlinks.
NO "read more".
NO article links.

LENGTH:
Aim for 3400-3700 characters.

Make the briefing genuinely informative.
Do not pad it with generic statements.
Use the available space for facts and explanations.

NEWS:
{news_text}
"""

    # --------------------------------------------------------
    # API
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

            # Enough room for a long briefing,
            # but the prompt asks for only ~3500 chars.
            "maxOutputTokens": 3000,

            # Lower reasoning overhead.
            "thinking_level": "low",

            "temperature": 0.25
        }
    }

    request = urllib.request.Request(

        url,

        data=json.dumps(
            payload
        ).encode(
            "utf-8"
        ),

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
                "\nGemini returned no candidates."
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

        text = ""

        for part in parts:

            text += part.get(
                "text",
                ""
            )

        text = text.strip()

        print(
            f"\nGemini output: "
            f"{len(text)} characters"
        )

        return text

    except urllib.error.HTTPError as e:

        error = e.read().decode(
            "utf-8",
            errors="replace"
        )

        print(
            f"\nGEMINI HTTP ERROR {e.code}"
        )

        print(error)

        return None

    except Exception as e:

        print(
            f"\nGEMINI ERROR: {e}"
        )

        return None


# ============================================================
# CLEAN GEMINI OUTPUT
# ============================================================

def clean_output(text):

    # Remove URLs if Gemini accidentally produces one.
    text = re.sub(
        r"https?://\S+",
        "",
        text
    )

    text = re.sub(
        r"www\.\S+",
        "",
        text
    )

    # Remove markdown hyperlinks.
    text = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        text
    )

    # Remove excessive blank lines.
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


# ============================================================
# FIT TELEGRAM LIMIT
# ============================================================

def fit_message(text):

    text = clean_output(
        text
    )

    print(
        f"Gemini output before trimming: "
        f"{len(text)} characters"
    )

    # Ideal case.
    if len(text) <= 3800:

        return text

    print(
        "Output is long; trimming only at story boundaries."
    )

    # --------------------------------------------------------
    # Separate MUST-KNOW
    # --------------------------------------------------------

    must_know = ""

    match = re.search(
        r"🎯 TODAY'S MUST-KNOW[\s\S]*$",
        text
    )

    if match:

        must_know = match.group(
            0
        ).strip()

        main = text[
            :match.start()
        ].strip()

    else:

        main = text

    # --------------------------------------------------------
    # Separate individual stories
    # --------------------------------------------------------

    stories = re.split(
        r"(?=📰 )",
        main
    )

    stories = [
        s.strip()
        for s in stories
        if s.strip()
    ]

    # --------------------------------------------------------
    # Keep as many COMPLETE stories as possible
    # --------------------------------------------------------

    result = ""

    for story in stories:

        candidate = (
            result
            + ("\n\n" if result else "")
            + story
        )

        if len(candidate) > 3650:

            break

        result = candidate

    # --------------------------------------------------------
    # Add MUST-KNOW if possible
    # --------------------------------------------------------

    if must_know:

        candidate = (
            result
            + "\n\n"
            + must_know
        )

        if len(candidate) <= 3800:

            result = candidate

    # --------------------------------------------------------
    # Absolute safety
    # --------------------------------------------------------

    if len(result) > 4090:

        result = result[
            :4085
        ].rstrip()

    print(
        f"Final Telegram message: "
        f"{len(result)} characters"
    )

    return result


# ============================================================
# FALLBACK
# ============================================================

def fallback_briefing(stories):

    ist = timezone(
        timedelta(
            hours=5,
            minutes=30
        )
    )

    today = datetime.now(
        ist
    ).strftime(
        "%d %B %Y"
    )

    message = (
        f"🌅 MORNING CURRENT AFFAIRS\n"
        f"{today}\n\n"
    )

    for story in stories:

        block = (
            f"📰 {story['title']}\n\n"
            f"What happened:\n"
            f"{story['description']}\n\n"
            f"Source: {story['source']}\n\n"
        )

        if len(
            message + block
        ) > 3700:

            break

        message += block

    return message.strip()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    message = fit_message(
        message
    )

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    payload = {

        "chat_id":
        TELEGRAM_CHAT_ID,

        "text":
        message,

        "disable_web_page_preview":
        True
    }

    request = urllib.request.Request(

        url,

        data=json.dumps(
            payload
        ).encode(
            "utf-8"
        ),

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
                "\n✅ Telegram message sent."
            )

            return True

        print(
            "\nTelegram error:"
        )

        print(
            json.dumps(
                result,
                indent=2
            )
        )

        return False

    except urllib.error.HTTPError as e:

        error = e.read().decode(
            "utf-8",
            errors="replace"
        )

        print(
            f"\nTELEGRAM HTTP ERROR {e.code}"
        )

        print(error)

        return False

    except Exception as e:

        print(
            f"\nTELEGRAM ERROR: {e}"
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print(
        "🌅 MORNING CURRENT AFFAIRS BOT"
    )
    print("=" * 60)

    # 1. Collect news.
    stories = collect_news()

    if not stories:

        raise RuntimeError(
            "No RSS stories found."
        )

    # 2. ONE Gemini request.
    briefing = ask_gemini(
        stories
    )

    # 3. Fallback if Gemini fails.
    if not briefing:

        print(
            "\nGemini failed. "
            "Using RSS fallback."
        )

        briefing = fallback_briefing(
            stories
        )

    # 4. ONE Telegram message.
    if not send_telegram(
        briefing
    ):

        raise RuntimeError(
            "Telegram delivery failed."
        )

    print("=" * 60)
    print(
        "✅ BOT FINISHED"
    )
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
