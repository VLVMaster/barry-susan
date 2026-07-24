#!/usr/bin/env python3
"""
Generates today's Barry & Susan illustration + story, based on a real
"on this day in history" event pulled from Wikipedia.

Run daily by the GitHub Action in .github/workflows/daily-image.yml

- Image: Pollinations.ai (free, no key)
- Story: Groq (free tier, no credit card, needs GROQ_API_KEY)
- History: Wikimedia on-this-day feed (free, no key)
"""
import json
import os
import random
import sys
import time
import urllib.parse
from datetime import date, datetime, timezone

import requests

# gen.pollinations.ai requires an API key now (confirmed 401 on image
# requests, not just text) — image.pollinations.ai/prompt is the actual
# documented anonymous, no-key path. It 404'd earlier in this build with
# a much longer/more complex prompt; now that the prompt is shorter and
# length-capped below, worth trying again rather than assuming it's dead.
IMAGE_BASE_URL = "https://image.pollinations.ai/prompt"
ONTHISDAY_URL = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{month}/{day}"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Page background colour — the image is generated on this exact colour so it
# sits on the page with no visible edge/box around the characters.
PAGE_BACKGROUND_HEX = "#F5EFE1"

# Bias event selection toward war/conflict when possible, per preference —
# falls back to any event on days where nothing matches.
CONFLICT_KEYWORDS = [
    "invasion", "massacre", "revolution", "assassinat",
    "coup", "siege", "bombing", "genocide", "uprising", "rebellion",
    "military", "army", "troops", "conquest", "occupation", "riot",
]

# Fixed character description — repeated every single call.
# Consistency comes from restating this every time, not from the model remembering.
CHARACTER_BASE = """
Detailed hand-drawn illustration style — fine pencil and ink linework,
soft cross-hatching and shading, muted sepia-and-watercolour palette
on aged parchment, like a vintage engraved storybook illustration or
an old natural-history print, NOT flat cartoon colour, NOT comic
linework. Expressive, characterful faces despite the fine detail.
Barry: a slightly round, scruffy grey pigeon, always looks a bit
pleased with himself, wears red adidas tracksuit bottoms. Susan: a
sleeker, iridescent green-and-purple-necked pigeon with ginger hair,
always looks like she's the one actually in charge. Same two
characters, same underlying style, every time.
""".strip()

BACKGROUND_RULE = """
No scenery beyond what's specified below, no extra props. The area
behind the characters is a single flat, completely uniform, unbroken
solid colour, exactly {bg_hex}, filling the whole frame edge to edge,
no gradient, no texture.
""".format(bg_hex=PAGE_BACKGROUND_HEX).strip()

IMAGE_SYSTEM_NOTE = """
Go full costume-drama: Barry, Susan, and a supporting cast of other
pigeons are dressed and posed AS the actual historical figures central
to this event — a pigeon-monarch, pigeon-soldiers, pigeon-courtiers,
whoever the event calls for — playing it out like an am-dram school
history pageant. Exaggerated, silly, larger-than-life expressions and
poses, in the same lively children's-storybook illustration style.
Costume and setting should be recognisably of the era. If possible,
dress them up as the individuals involved.
""".strip()

FALLBACK_EVENT = {
    "year": None,
    "text": "just an ordinary day, nothing of note recorded",
}

STORY_SYSTEM_PROMPT = """
You write a single paragraph (90-130 words), genuinely ridiculous and
fun to read, narrating a real historical event as if Barry and Susan
— two pigeons — are playing the actual historical figures involved,
am-dram school-pageant style, hamming it up shamelessly. Feel free to
lean into broad, silly, widely-loved comic voices where they fit
(cheeky regional accents written phonetically, deadpan asides,
whatever makes it fun to read aloud) — the goal is genuinely
entertaining, shareable, laugh-out-loud. The historical facts
underneath the silliness must stay completely accurate: real
outcomes, real consequences, real detail. No preamble, no title,
just the paragraph. Make it dark.
""".strip()


def fetch_todays_event() -> dict:
    """Pull today's on-this-day events from Wikimedia, prefer a
    war/conflict-related one, fall back to any event, then to a
    generic placeholder if the feed is unreachable."""
    today = date.today()
    url = ONTHISDAY_URL.format(month=f"{today.month:02d}", day=f"{today.day:02d}")
    try:
        resp = requests.get(url, headers={"User-Agent": "barry-and-susan/1.0"}, timeout=30)
        resp.raise_for_status()
        events = resp.json().get("events", [])
    except Exception as e:
        print(f"Could not fetch on-this-day events, using fallback: {e}")
        return FALLBACK_EVENT

    if not events:
        return FALLBACK_EVENT

    conflict_events = [
        e for e in events
        if any(kw in e.get("text", "").lower() for kw in CONFLICT_KEYWORDS)
    ]
    pool = conflict_events if conflict_events else events
    return random.choice(pool)


def build_image_prompt(event: dict) -> str:
    year_bit = f" set in the year {event['year']}," if event.get("year") else ""
    return (
        f"{CHARACTER_BASE} {IMAGE_SYSTEM_NOTE} {BACKGROUND_RULE} "
        f"Today's real historical event,{year_bit} to reference for "
        f"costume and setting only: {event['text']}."
    )


def _get_image_with_retry(url: str, max_attempts: int = 4) -> bytes:
    """GET the image, retrying not just on bad HTTP status but also when
    what comes back doesn't actually look like a real photo — a 200
    response with an HTML/JSON error body, or a suspiciously tiny file,
    would otherwise get silently written to disk as if it were fine."""
    MIN_IMAGE_BYTES = 15_000
    last_reason = None
    for attempt in range(1, max_attempts + 1):
        resp = requests.get(url, timeout=120)
        content_type = resp.headers.get("Content-Type", "")

        if resp.status_code != 200:
            last_reason = f"HTTP {resp.status_code}"
            print(f"Attempt {attempt}/{max_attempts} failed: {last_reason}")
            print(f"Response body: {resp.text[:500]}")
        elif not content_type.startswith("image/"):
            last_reason = f"non-image response (Content-Type: {content_type})"
            print(f"Attempt {attempt}/{max_attempts} failed: {last_reason}")
            print(f"Response body: {resp.text[:500]}")
        elif len(resp.content) < MIN_IMAGE_BYTES:
            last_reason = f"suspiciously small image ({len(resp.content)} bytes) — likely a placeholder/blocked-content response"
            print(f"Attempt {attempt}/{max_attempts} failed: {last_reason}")
        else:
            print(f"Got a valid image: {content_type}, {len(resp.content)} bytes")
            return resp.content

        wait = 5 * attempt
        print(f"Retrying in {wait}s...")
        time.sleep(wait)

    raise RuntimeError(f"Gave up after {max_attempts} attempts. Last reason: {last_reason}")


def _groq_post_with_retry(payload: dict, max_attempts: int = 4) -> dict:
    """POST to Groq's OpenAI-compatible chat completions endpoint,
    retrying on 429/5xx with backoff, surfacing the actual error body
    on failure rather than a bare status code."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    last_error = None
    for attempt in range(1, max_attempts + 1):
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=120)
        if resp.status_code == 200:
            return resp.json()

        print(f"Attempt {attempt}/{max_attempts} failed: HTTP {resp.status_code}")
        print(f"Response body: {resp.text[:500]}")

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = resp
            wait = 2 ** attempt
            print(f"Retrying in {wait}s...")
            time.sleep(wait)
            continue

        resp.raise_for_status()  # non-retryable — fail immediately

    raise RuntimeError(f"Gave up after {max_attempts} attempts. Last status: {last_error.status_code}")


def generate_image(prompt: str) -> bytes:
    MAX_PROMPT_CHARS = 1500
    if len(prompt) > MAX_PROMPT_CHARS:
        print(f"Prompt is {len(prompt)} chars, trimming to {MAX_PROMPT_CHARS}")
        prompt = prompt[:MAX_PROMPT_CHARS]
    encoded = urllib.parse.quote(prompt)
    url = f"{IMAGE_BASE_URL}/{encoded}?width=1024&height=768&nologo=true"
    return _get_image_with_retry(url)


def generate_story(event: dict) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    year_bit = f" (year: {event['year']})" if event.get("year") else ""
    prompt = f"{STORY_SYSTEM_PROMPT}\n\nReal event{year_bit}: {event['text']}"
    payload = {
        "model": GROQ_MODEL,
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _groq_post_with_retry(payload)
    return data["choices"][0]["message"]["content"].strip()


def main():
    event = fetch_todays_event()
    print(f"Event: {event.get('year')} — {event['text']}")

    image_prompt = build_image_prompt(event)
    image_bytes = generate_image(image_prompt)

    story = None
    try:
        story = generate_story(event)
        print(f"Story: {story}")
    except Exception as e:
        print(f"Story generation failed, publishing image without it: {e}")
        story = "Barry and Susan witnessed today's history, but the report went unwritten."

    os.makedirs("docs", exist_ok=True)
    with open("docs/today.png", "wb") as f:
        f.write(image_bytes)

    with open("docs/today.json", "w") as f:
        json.dump(
            {
                "date": date.today().isoformat(),
                "event_year": event.get("year"),
                "event_text": event["text"],
                "story": story,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )

    print("Wrote docs/today.png and docs/today.json")


if __name__ == "__main__":
    sys.exit(main())
