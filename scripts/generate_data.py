"""
generate_style_data.py — Generate style-labeled parallel sentence pairs using Gemini API.

Uses the google.genai SDK (new, non-deprecated) with paid tier for reliable rate limits.

Usage:
    pip install google-genai tqdm
    python scripts/generate_data.py --api_key YOUR_GEMINI_KEY --lang turkish
    python scripts/generate_data.py --api_key YOUR_GEMINI_KEY --lang russian
    python scripts/generate_data.py --api_key YOUR_GEMINI_KEY --lang german
"""

import argparse
import json
import time
import re
from pathlib import Path
from tqdm import tqdm

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Install the Gemini SDK:  pip install google-genai")
    exit(1)


# ──────────────────────────────────────────────
# 200 seed topics covering diverse language-learning scenarios
# ──────────────────────────────────────────────
SEED_TOPICS = [
    "greeting someone you just met",
    "introducing yourself at a job interview",
    "saying goodbye to a friend",
    "welcoming a guest to your home",
    "thanking someone for a gift",
    "asking someone how their day was",
    "talking about the weather today",
    "describing your morning routine",
    "making plans for the weekend",
    "complaining about being tired",
    "talking about your favorite food",
    "describing what you had for breakfast",
    "asking someone to help you move",
    "telling someone you are running late",
    "asking a neighbor to be quieter",
    "ordering food at a restaurant",
    "asking for the bill at a restaurant",
    "complaining about cold food",
    "asking for a discount at a shop",
    "returning a defective product",
    "recommending a restaurant to someone",
    "asking if an item is in stock",
    "describing what kind of shoes you want",
    "asking for a table for two",
    "tipping the waiter",
    "asking for directions to the train station",
    "booking a hotel room",
    "complaining about a flight delay",
    "asking how much a taxi costs",
    "describing your travel plans",
    "checking in at a hotel",
    "asking about tourist attractions",
    "reporting lost luggage at the airport",
    "asking for a window seat on a plane",
    "describing your favorite vacation",
    "emailing your boss about taking a day off",
    "asking a colleague for help with a task",
    "presenting quarterly results to a team",
    "negotiating a salary raise",
    "writing a follow-up email after a meeting",
    "declining a meeting invitation politely",
    "congratulating a colleague on a promotion",
    "explaining why a project is behind schedule",
    "requesting feedback on your work",
    "scheduling a video call",
    "asking a professor about an assignment deadline",
    "explaining why you missed class",
    "asking a classmate to study together",
    "requesting a letter of recommendation",
    "discussing your thesis topic",
    "asking for an extension on a paper",
    "explaining a concept to a younger student",
    "complaining about a difficult exam",
    "thanking a teacher for their help",
    "asking about course registration",
    "describing symptoms to a doctor",
    "making a doctor's appointment",
    "asking a pharmacist about medication",
    "telling someone you don't feel well",
    "giving advice about staying healthy",
    "asking about visiting hours at a hospital",
    "explaining a food allergy",
    "calling in sick to work",
    "asking about insurance coverage",
    "describing a past injury",
    "asking for help with a computer problem",
    "explaining how to use an app",
    "complaining about slow internet",
    "describing a new phone you bought",
    "asking someone to send you a file",
    "reporting a bug in software",
    "asking for the Wi-Fi password",
    "explaining why you prefer Android or iPhone",
    "describing what a website does",
    "asking someone to fix your printer",
    "expressing excitement about good news",
    "comforting a friend who is sad",
    "expressing disappointment about a result",
    "telling someone you are proud of them",
    "apologizing for a mistake",
    "expressing frustration with a situation",
    "sharing your opinion about a movie",
    "disagreeing with someone politely",
    "expressing surprise about unexpected news",
    "telling someone you miss them",
    "inviting someone to a party",
    "declining an invitation politely",
    "making small talk at a social event",
    "introducing two friends to each other",
    "asking someone on a date",
    "congratulating someone on their wedding",
    "offering condolences",
    "asking someone to keep a secret",
    "resolving a misunderstanding with a friend",
    "asking a roommate to clean up",
    "asking about exchange rates",
    "opening a bank account",
    "reporting a lost credit card",
    "asking about loan options",
    "splitting the bill with friends",
    "negotiating the price of a car",
    "asking about payment methods",
    "discussing monthly expenses",
    "lending money to a friend",
    "asking for a refund",
    "asking about rent for an apartment",
    "complaining to a landlord about repairs",
    "describing your ideal home",
    "asking a neighbor about the area",
    "signing a lease agreement",
    "asking about pet policies in a building",
    "requesting maintenance for a broken heater",
    "describing your room to someone",
    "asking about utilities included in rent",
    "telling your landlord you are moving out",
    "buying a train ticket",
    "asking about bus schedules",
    "reporting an accident to police",
    "asking for car repair estimates",
    "complaining about traffic",
    "asking someone for a ride",
    "describing a road trip",
    "asking about parking options",
    "reporting a problem with public transit",
    "asking how to get to the airport",
    "recommending a book to someone",
    "discussing a TV show you watched",
    "inviting someone to a concert",
    "describing a museum exhibit",
    "talking about your hobbies",
    "asking about local festivals",
    "discussing a sports match",
    "recommending music to a friend",
    "describing a painting you liked",
    "talking about a game you played",
    "sharing a recipe with someone",
    "asking about ingredients in a dish",
    "complimenting someone's cooking",
    "ordering a special dietary meal",
    "describing your country's traditional food",
    "asking someone to teach you how to cook",
    "complaining about a restaurant's service",
    "asking about food delivery options",
    "discussing healthy eating habits",
    "planning a dinner party menu",
    "describing the view from your window",
    "talking about climate change",
    "planning an outdoor activity",
    "describing your favorite season",
    "asking about weather forecast for the week",
    "talking about recycling habits",
    "describing a hike you went on",
    "asking about pet care",
    "discussing pollution in your city",
    "planning a picnic",
    "calling emergency services",
    "reporting a theft to police",
    "asking for help in a dangerous situation",
    "explaining a car breakdown",
    "asking about fire exits in a building",
    "reporting a water leak to maintenance",
    "asking about earthquake safety procedures",
    "describing an emergency to a dispatcher",
    "asking about travel safety warnings",
    "requesting roadside assistance",
    "describing your family members",
    "talking about a family gathering",
    "discussing parenting approaches",
    "telling someone about your childhood",
    "planning a birthday celebration",
    "describing your relationship with siblings",
    "asking about someone's family",
    "talking about family traditions",
    "discussing plans to visit family",
    "sharing news about a family event",
    "writing a product review",
    "asking someone to repeat what they said",
    "giving someone life advice",
    "explaining a cultural tradition",
    "asking about customs regulations",
    "describing your dream job",
    "talking about future goals",
    "explaining why you chose your major",
    "asking about volunteer opportunities",
    "describing a memorable experience",
]


# ──────────────────────────────────────────────
# Prompt template
# ──────────────────────────────────────────────
def build_prompt(topic: str, target_lang: str) -> str:
    return f"""You are a multilingual language expert. Generate sentence pairs for a language-learning translation dataset.

Topic: "{topic}"

For this topic, generate **5 different sentences** that someone might say in this situation.
For EACH sentence, provide it in **3 styles** in **both English and {target_lang}**.

The 3 styles are:
- **formal**: Polite, proper grammar, suitable for business/academic contexts. Uses respectful address forms.
- **casual**: Relaxed, uses contractions, slang, colloquial expressions. How friends talk to each other.
- **neutral**: Standard everyday language. Not overly polite or overly relaxed. Clear and straightforward.

IMPORTANT RULES:
- Each style version must convey the SAME core meaning, just with different tone/register.
- The {target_lang} versions must sound natural to a native speaker (not literal translations).
- Use culturally appropriate expressions for {target_lang} (e.g., proper honorifics, colloquialisms).
- Vary sentence length and complexity across the 5 sentences.

Respond ONLY with valid JSON — no markdown, no explanation. Use this exact format:
[
  {{
    "topic": "{topic}",
    "en_formal": "...",
    "en_casual": "...",
    "en_neutral": "...",
    "{target_lang.lower()}_formal": "...",
    "{target_lang.lower()}_casual": "...",
    "{target_lang.lower()}_neutral": "..."
  }},
  ...
]

Generate exactly 5 JSON objects in the array."""


# ──────────────────────────────────────────────
# API call with retry logic
# ──────────────────────────────────────────────
def call_gemini(client, model_name: str, prompt: str, max_retries: int = 3) -> list[dict] | None:
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.9,
                    max_output_tokens=4096,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )

            text = response.text.strip()

            # Strip markdown fences if present
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

            data = json.loads(text)

            if isinstance(data, list) and len(data) > 0:
                return data
            else:
                print(f"  [!] Unexpected format on attempt {attempt+1}")

        except json.JSONDecodeError as e:
            print(f"  [!] JSON parse error on attempt {attempt+1}: {e}")
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "RESOURCE_EXHAUSTED" in err_str:
                wait = 15 * (attempt + 1)
                print(f"  [!] Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  [!] API error on attempt {attempt+1}: {e}")

        time.sleep(2)

    return None


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Generate style-labeled sentence pairs using Gemini")
    parser.add_argument("--api_key", type=str, required=True, help="Your Gemini API key")
    parser.add_argument("--lang", type=str, required=True, choices=["turkish", "russian", "german"],
                        help="Target language")
    parser.add_argument("--model_name", type=str, default="gemini-2.0-flash",
                        help="Gemini model to use (default: gemini-2.0-flash)")
    parser.add_argument("--start_from", type=int, default=0,
                        help="Topic index to resume from (if script was interrupted)")
    parser.add_argument("--delay", type=float, default=3.0,
                        help="Seconds between API calls (default: 3.0)")
    args = parser.parse_args()

    # Setup
    client = genai.Client(api_key=args.api_key)

    # Quick test
    print("Testing API connection...")
    try:
        test_response = client.models.generate_content(
            model=args.model_name,
            contents="Say hello in one word.",
            config=types.GenerateContentConfig(max_output_tokens=200),
        )
        print(f"  API working! Response: {(test_response.text or 'OK').strip()}")
    except Exception as e:
        print(f"  ERROR: API connection failed: {e}")
        print(f"  Check your API key and billing status.")
        exit(1)

    output_dir = Path("data/raw")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"style_pairs_{args.lang}.jsonl"

    # If resuming, count existing records
    existing = 0
    if args.start_from > 0 and output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            existing = sum(1 for _ in f)
        print(f"Resuming from topic {args.start_from} ({existing} records already saved)")

    topics = SEED_TOPICS[args.start_from:]
    total_generated = existing

    print(f"\n{'='*60}")
    print(f"  Generating {args.lang.upper()} style pairs")
    print(f"  Model: {args.model_name}")
    print(f"  Topics: {len(topics)} (starting from index {args.start_from})")
    print(f"  Output: {output_file}")
    print(f"  Estimated time: ~{len(topics) * (args.delay + 1.5) / 60:.0f} minutes")
    print(f"{'='*60}\n")

    mode = "a" if args.start_from > 0 else "w"
    with open(output_file, mode, encoding="utf-8") as f:
        for i, topic in enumerate(tqdm(topics, desc=f"Generating {args.lang}")):
            prompt = build_prompt(topic, args.lang.capitalize())
            results = call_gemini(client, args.model_name, prompt)

            if results:
                for item in results:
                    item["source_topic"] = topic
                    item["target_language"] = args.lang
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                total_generated += len(results)
            else:
                print(f"  [SKIP] Failed after retries: '{topic}'")
                with open(output_dir / f"failed_topics_{args.lang}.txt", "a") as fail_f:
                    fail_f.write(f"{args.start_from + i}\t{topic}\n")

            time.sleep(args.delay)

            # Checkpoint every 25 topics
            if (i + 1) % 25 == 0:
                f.flush()
                print(f"\n  [checkpoint] {total_generated} total records saved\n")

    print(f"\n{'='*60}")
    print(f"  DONE! Generated {total_generated} records for {args.lang}")
    print(f"  Saved to: {output_file}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
