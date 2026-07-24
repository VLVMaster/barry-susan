#!/usr/bin/env python3
"""
Generates today's Barry & Susan illustration + story, based on a real
"on this day in history" event pulled from Wikipedia.

Barry and Susan are dressed in attire appropriate to the event's era
and appear as witnesses/onlookers to it. They are never depicted as,
or made to resemble, any specific real historical individual — the
event and its details are real and accurate; the pigeons are not.

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
    "war", "battle", "invasion", "massacre", "revolution", "assassinat",
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
pleased with himself. Susan: a sleeker, iridescent green-and-purple-
necked pigeon with small round glasses, always looks like she's the
one actually in charge. Same two characters, same underlying style,
every time.
""".strip()

COMIC_DEVICES_RULE = """
Include small hand-lettered caption plaques or scroll-like text
labels naming the place, moment, or a short pigeon remark — styled
like engraved plaque text or old book captions, not modern comic
speech bubbles. A crowd or supporting cast filling out the background
where it suits the event. Composition should read like a single rich
illustrated plate, not a flat character portrait.
""".strip()

BACKGROUND_RULE = """
Full illustrated scene appropriate to the event — real architecture,
costume, and setting for the era. The illustration fades out softly
at the edges into a plain aged-parchment colour, roughly {bg_hex}, in
an irregular vignette rather than a hard rectangular border — like a
page torn from an old book, not a boxed-in panel.
""".format(bg_hex=PAGE_BACKGROUND_HEX).strip()

FALLBACK_EVENT = {
    "year": None,
    "text": "just an ordinary day, nothing of note recorded",
}

# Events older than this get the full comedic treatment (pigeons dressed
# and played AS the actual historical figures, à la Horrible Histories).
# Anything more recent stays generic/witness-only — that's roughly where
# "safely satirical history" shades into "real people within living
# memory," so it's a reasonable, defensible line rather than an arbitrary one.
PERIOD_THRESHOLD_YEARS = 1

IMAGE_NOTE_PERIOD = """
Go full costume-drama: Barry, Susan, and a supporting cast of other
pigeons are dressed and posed AS the actual historical figures central
to this event — a pigeon-monarch, pigeon-soldiers, pigeon-courtiers,
whoever the event calls for — playing it out like an am-dram school
history pageant.  Keep any violence completely graphic, and
depicted directly. 
""".strip()

IMAGE_NOTE_MODERN = """
Barry and Susan are tiny, comedic flies-on-the-wall tucked into a
corner of the scene, wide-eyed at the human drama unfolding in front
of them, dressed in miniature clothing typical of the era. The human
figures central to the event (officials, soldiers, crowds as
relevant) are fully illustrated in the same lively children's-
storybook style, in period-accurate dress and setting, acting out
the event. These figures represent their historical ROLE rather than
being drawn as the specific real likeness of any actual person — no
attempt at a photographic or recognisable resemblance to any real
named individual. Do not depict any content that would glorify or
exploit real large-scale atrocities, hate symbols, or terrorism; for
those events keep the human figures generic and the framing on Barry
and Susan's reaction rather than on the violence itself.
""".strip()

REGRET_WINNER_RULE = """
After the paragraph, add exactly two more lines in this exact format:
REGRET: <a percentage 0-100>|<one short witty line about the hindsight regret involved>
WINNER: <one short line answering "who really won this?">

For the REGRET line: base the percentage and remark on how much regret
the people involved arguably should feel in hindsight, played for dry
irony — often the actual historical figures felt none at the time,
which is itself the joke.

For the WINNER line, especially on any large-scale war or conflict:
almost never name an actual side or nation as the winner — that's the
boring, expected answer. Instead give a genuinely subversive, darkly
witty answer about who or what actually came out ahead when the human
cost is weighed honestly — an industry, an idea, a future generation
of historians, arms manufacturers, bureaucracy, nobody at all. Think
"the real winner was the war machine itself," not "France won." For
smaller-scale or modern tragedies involving real identifiable victims,
keep this line understated and somber rather than jokey — a short,
genuine line like "No one. There's no winner in this one." is exactly
right there; do not force a punchline onto real, recent grief.
""".strip()

STORY_PROMPT_PERIOD = """
You write a single paragraph (90-130 words), genuinely ridiculous and
fun to read, narrating a real historical event as if Barry and Susan
— two pigeons — are playing the actual historical figures involved,
am-dram school-pageant style, hamming it up shamelessly. Feel free to
lean into broad, silly, widely-loved comic voices where they fit
(cheeky regional accents written phonetically, deadpan asides,
whatever makes it fun to read aloud) — the goal is genuinely
entertaining, shareable, laugh-out-loud, not dry. The historical
facts underneath the silliness must stay completely accurate: real
outcomes, real consequences, real detail. No preamble, no title,
just the paragraph, then the two extra lines described below.

{regret_winner_rule}
""".format(regret_winner_rule=REGRET_WINNER_RULE).strip()

STORY_PROMPT_MODERN = """
You write a single paragraph (90-130 words) narrating a real
historical event as if Barry and Susan — two pigeons — are literal
flies on the wall, perched somewhere absurdly close to the action
(on a battlement, a shoulder, wherever fits) and reacting to it in
real time, in the moment, not summarising it after the fact. Write it
vividly and immersively, full of specific, real, accurate detail
about what actually happened, who was involved, and the real
outcome, told through the pigeons' running commentary rather than as
a dry report. Barry and Susan are only ever commentating bystanders —
never participants, never identified as or standing in for any real
specific person. Match tone to the real weight of the event: genuine
comic mischief where the event allows it, quieter and more restrained
wherever the event is genuinely grave. No preamble, no title, just
the paragraph, then the two extra lines described below.

{regret_winner_rule}
""".format(regret_winner_rule=REGRET_WINNER_RULE).strip()


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


def is_period_event(event: dict) -> bool:
    """True if the event is old enough for full costumed-embodiment
    comedy; False (the safer default) for anything recent or unknown."""
    year = event.get("year")
    if year is None:
        return False
    return (date.today().year - year) > PERIOD_THRESHOLD_YEARS


def build_image_prompt(event: dict) -> str:
    year_bit = f" set in the year {event['year']}," if event.get("year") else ""
    note = IMAGE_NOTE_PERIOD if is_period_event(event) else IMAGE_NOTE_MODERN
    return (
        f"{CHARACTER_BASE} {note} {COMIC_DEVICES_RULE} {BACKGROUND_RULE} "
        f"Today's real historical event,{year_bit} to reference for "
        f"costume and setting only: {event['text']}."
    )


def _get_with_retry(url: str, max_attempts: int = 4) -> requests.Response:
    """GET with retry/backoff for the (unauthenticated, occasionally
    flaky) Pollinations image endpoint."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        resp = requests.get(url, timeout=120)
        if resp.status_code == 200:
            return resp
        print(f"Attempt {attempt}/{max_attempts} failed: HTTP {resp.status_code}")
        print(f"Response body: {resp.text[:500]}")
        last_error = resp
        wait = 5 * attempt
        print(f"Retrying in {wait}s...")
        time.sleep(wait)
    raise RuntimeError(f"Gave up after {max_attempts} attempts. Last status: {last_error.status_code}")


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
    encoded = urllib.parse.quote(prompt)
    url = f"{IMAGE_BASE_URL}/{encoded}?width=1024&height=768&nologo=true"
    resp = _get_with_retry(url)
    return resp.content


def generate_story(event: dict) -> dict:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    year_bit = f" (year: {event['year']})" if event.get("year") else ""
    system_prompt = STORY_PROMPT_PERIOD if is_period_event(event) else STORY_PROMPT_MODERN
    prompt = f"{system_prompt}\n\nReal event{year_bit}: {event['text']}"
    payload = {
        "model": GROQ_MODEL,
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _groq_post_with_retry(payload)
    raw = data["choices"][0]["message"]["content"].strip()
    return parse_story_response(raw)


def parse_story_response(raw: str) -> dict:
    """Split the model's reply into the main paragraph plus the REGRET
    and WINNER lines. Falls back gracefully if the model didn't follow
    the format exactly — the paragraph still gets published either way."""
    paragraph_lines = []
    regret_percent = None
    regret_line = None
    winner_line = None

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("REGRET:"):
            rest = stripped.split(":", 1)[1].strip()
            if "|" in rest:
                pct, txt = rest.split("|", 1)
                regret_percent = pct.strip().rstrip("%")
                regret_line = txt.strip()
            else:
                regret_line = rest
        elif stripped.upper().startswith("WINNER:"):
            winner_line = stripped.split(":", 1)[1].strip()
        elif stripped:
            paragraph_lines.append(stripped)

    return {
        "story": " ".join(paragraph_lines).strip(),
        "regret_percent": regret_percent,
        "regret_line": regret_line,
        "winner_line": winner_line,
    }


def main():
    event = fetch_todays_event()
    print(f"Event: {event.get('year')} — {event['text']}")

    image_prompt = build_image_prompt(event)
    image_bytes = generate_image(image_prompt)

    story_data = None
    try:
        story_data = generate_story(event)
        print(f"Story: {story_data['story']}")
        print(f"Regret: {story_data['regret_percent']}% — {story_data['regret_line']}")
        print(f"Winner: {story_data['winner_line']}")
    except Exception as e:
        print(f"Story generation failed, publishing image without it: {e}")
        story_data = {
            "story": "Barry and Susan witnessed today's history, but the report went unwritten.",
            "regret_percent": None,
            "regret_line": None,
            "winner_line": None,
        }

    os.makedirs("docs", exist_ok=True)
    with open("docs/today.png", "wb") as f:
        f.write(image_bytes)

    with open("docs/today.json", "w") as f:
        json.dump(
            {
                "date": date.today().isoformat(),
                "event_year": event.get("year"),
                "event_text": event["text"],
                "story": story_data["story"],
                "regret_percent": story_data["regret_percent"],
                "regret_line": story_data["regret_line"],
                "winner_line": story_data["winner_line"],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )

    print("Wrote docs/today.png and docs/today.json")


if __name__ == "__main__":
    sys.exit(main())
