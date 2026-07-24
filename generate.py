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
Photorealistic photograph, not an illustration or painting — real
pigeons, real feather detail, real photographic lighting and depth
of field, shot like genuine street/documentary photography. Two
real pigeons, each wearing a small handwritten paper or fabric tag
on a loop of string around its neck: one reads "BARRY", the other
reads "SUSAN" — this tag is how they're identified, since real
pigeons otherwise look similar. Same two pigeons, same tags, every
time.
""".strip()

PHOTO_ERA_PRE_PHOTOGRAPHY = """
Photography did not exist yet in this era — lean into that as part
of the joke. Style the image as an aged, damaged sepia photographic
print or tintype, complete with period-wrong anachronism (a pigeon
wearing tiny era-accurate costume pieces, "impossibly" captured on
film centuries early). Scratches, foxing, and photo-paper texture
typical of a found antique photograph.
""".strip()

PHOTO_ERA_EARLY_PHOTO = """
Style as a genuine black-and-white or sepia-toned photograph typical
of early photography (glass-plate/large-format look) — soft focus,
period-correct tonal range, grain and paper texture consistent with
a real surviving photograph from this era.
""".strip()

PHOTO_ERA_MODERN = """
Style as a real modern photograph appropriate to the decade — for
mid-20th-century events, black-and-white or faded period colour
film grain; for recent decades, natural full-colour digital/film
photography, candid and documentary in feel.
""".strip()


def photo_era_note(event: dict) -> str:
    """Picks a photographic treatment matching the real history of
    photography — the joke does double duty as a consistency device."""
    year = event.get("year")
    if year is None:
        return PHOTO_ERA_MODERN
    if year < 1850:
        return PHOTO_ERA_PRE_PHOTOGRAPHY
    if year < 1950:
        return PHOTO_ERA_EARLY_PHOTO
    return PHOTO_ERA_MODERN


COMIC_DEVICES_RULE = """
No cartoon speech bubbles or illustrated captions — this is a
photograph, not a comic. Any text should only appear where it would
plausibly exist in the real photographed scene (a sign, a museum
placard, a newspaper) or on the pigeons' own name tags. Include real
supporting people/crowd/setting details appropriate to the event
where relevant, shot in the same photographic style.
""".strip()

BACKGROUND_RULE = """
Full, real, physically plausible setting appropriate to the event —
real architecture, real costume/props, real depth of field with the
background naturally soft-focused behind the pigeons in the way a
genuine photograph would render it.
""".strip()

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
Barry and Susan (identifiable by their name tags) wear small, real,
physically plausible props/costume pieces evoking the actual
historical figures central to this event — a tiny crown or hat, a
scrap of period-accurate fabric, a small prop — as if a real pigeon
had been dressed up for the shot, playful and slightly absurd rather
than a full costume transformation. Other real pigeons can appear as
a supporting "cast" similarly dressed if it suits the scene. 
""".strip()

IMAGE_NOTE_MODERN = """
Barry and Susan (identifiable by their name tags) are small real
pigeons tucked into a corner of a real, physically plausible scene
appropriate to the event, wearing at most a tiny, subtle accessory
rather than a full costume. Real human figures relevant to the event
(officials, soldiers, crowds as relevant) appear in the background,
photographed naturally — do not attempt a specific real named
individual's actual likeness.
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
right there; do not force a punchline onto real, recent grief. Focus on british humour
""".strip()

HEADLINE_RULE = """
Start your reply with one line in this exact format:
HEADLINE: <a short, punchy, real headline for this specific event —
think proper newspaper or documentary title, evocative and specific
to what actually happened, not generic and not mentioning pigeons>
""".strip()

STORY_PROMPT_PERIOD = """
You write a paragraph (180-260 words) narrating a real historical
event as a dry, witty exchange between Barry and Susan — two pigeons
perched somewhere absurd and close to the action — who are playing
the actual historical figures involved, or narrating what those
figures are doing, whichever reads better. Model your voice on this
example, which is the target quality bar: dialogue-driven, genuinely
funny through specific and surprising real detail rather than
slapstick or forced accents, dry asides, and enough actual
substance that a reader comes away understanding exactly what
happened and why it mattered — nothing vague, nothing hand-wavy.

{headline_rule}

EXAMPLE (match this style, not this event):
"Barry eyed the man below with the mirrored sunglasses and
ceremonial dagger. 'That's Colonel Gaddafi, Susan. 1977. Just
invented a whole system of government called the Jamahiriya —
Arabic, roughly, for "nobody's technically in charge, wink wink."
No president, no parliament, no parties. Just "the people," directly
ruling themselves. And who's stood at the podium in the safari suit
explaining how the people rule themselves? Him. Constantly. Even
written a little book about it — The Green Book — required reading,
rather like a cult pamphlet with better production values. Calls
himself "Brotherly Leader," no official title, purely coincidental
he controls the army, the oil money, and everyone's postbox.'
Susan ruffled her feathers. 'Builds a hospital with one hand,
disappears a critic with the other. Funds revolutionaries abroad
like it's a hobby. Frightfully generous with other people's
countries.' Barry took off. 'Man commits to a costume change,
though. Give him that.'"

Only use a regional voice or accent where it genuinely fits and
adds something — never force a phonetic accent as decoration, it
should read as clean, sharp prose above all else. The historical
facts must be completely accurate and specific: real names, real
terms, real numbers, real outcomes. No preamble beyond the headline
line, then the paragraph, then the two extra lines described below. 

{regret_winner_rule}
""".format(regret_winner_rule=REGRET_WINNER_RULE, headline_rule=HEADLINE_RULE).strip()

STORY_PROMPT_MODERN = """
You write a paragraph (180-260 words) narrating a real historical
event as if Barry and Susan — two pigeons — are literal flies on the
wall, perched somewhere close to the action, reacting to it in real
time. Model your voice on this example, which is the target quality
bar: dialogue-driven, genuinely witty through specific and surprising
real detail, dry rather than slapstick, and substantive enough that a
reader comes away understanding exactly what happened and why —
nothing vague, nothing hand-wavy:

{headline_rule}

EXAMPLE (match this style, not this event or tone — that example is
for a lighter period event; for a grave modern event, keep the same
dialogue-driven clarity but pull the humour right back and let the
facts carry the weight instead):
"Barry eyed the man below with the mirrored sunglasses and
ceremonial dagger. 'That's Colonel Gaddafi, Susan. 1977. Just
invented a whole system of government called the Jamahiriya —
Arabic, roughly, for "nobody's technically in charge, wink wink." No
president, no parliament, no parties.' Susan ruffled her feathers.
'Builds a hospital with one hand, disappears a critic with the
other.' Barry took off. 'Man commits to a costume change, though.'"

Barry and Susan are only ever commentating bystanders — never
participants, never identified as or standing in for any real
specific person. The historical facts must be completely accurate
and specific: real names, real terms, real numbers, real outcomes.
No preamble beyond the headline line, then the paragraph, then the
two extra lines described below.

{regret_winner_rule}
""".format(regret_winner_rule=REGRET_WINNER_RULE, headline_rule=HEADLINE_RULE).strip()


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
    era_note = photo_era_note(event)
    return (
        f"{CHARACTER_BASE} {note} {era_note} {COMIC_DEVICES_RULE} {BACKGROUND_RULE} "
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
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _groq_post_with_retry(payload)
    raw = data["choices"][0]["message"]["content"].strip()
    return parse_story_response(raw)


def parse_story_response(raw: str) -> dict:
    """Split the model's reply into headline, main paragraph, REGRET,
    and WINNER lines. Falls back gracefully if the model didn't follow
    the format exactly — the paragraph still gets published either way."""
    headline = None
    paragraph_lines = []
    regret_percent = None
    regret_line = None
    winner_line = None

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("HEADLINE:"):
            headline = stripped.split(":", 1)[1].strip().strip('"')
        elif stripped.upper().startswith("REGRET:"):
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
        "headline": headline,
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
        print(f"Headline: {story_data['headline']}")
        print(f"Story: {story_data['story']}")
        print(f"Regret: {story_data['regret_percent']}% — {story_data['regret_line']}")
        print(f"Winner: {story_data['winner_line']}")
    except Exception as e:
        print(f"Story generation failed, publishing image without it: {e}")
        story_data = {
            "headline": event.get("text", "History, unwritten today")[:80],
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
                "headline": story_data["headline"],
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
