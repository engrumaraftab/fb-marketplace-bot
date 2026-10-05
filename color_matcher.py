import json
import os
import requests, logging

FB_COLORS = [
    "Black", "Blue", "Brown", "Gold", "Green", "Gray", "Pink",
    "Purple", "Red", "Silver", "Orange", "White", "Yellow",
    "Charcoal", "Off white", "Tan", "Beige", "Burgundy", "Turquoise"
]

SYSTEM_PROMPT = f"""
You map vehicle paint colors to Facebook Marketplace colors.

Available colors:
{", ".join(FB_COLORS)}

Rules:
- Return an exact match if one exists.
- Otherwise return the closest automotive paint color.
- Ignore modifiers like Light, Dark, Pearl, Metallic, Matte, Gloss,
  Bright, Deep, Midnight, Forest, etc.
- Return exactly one color from the available list.
- Do not explain your answer.
""".strip()


class FBMarketplaceColorMatcher:

    def __init__(self, openai_api_key, cache_file="color_cache.json", logger=None):
        self.OPENAI_API_KEY = openai_api_key
        self.cache_file = cache_file
        self.color_cache = self.load_color_cache()
        self.logger = logger or logging.getLogger("automation")

    def load_color_cache(self):
        """Load color mappings from disk."""
        if os.path.exists(self.cache_file):
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_color_cache(self):
        """Persist color mappings to disk."""
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.color_cache, f, indent=4, sort_keys=True)

    def get_matched_color(self, color):
        """
        Returns the closest FB Marketplace color.
        Uses cached value if available, otherwise queries OpenAI
        and updates the cache.
        """
        if not color:
            return "Other"

        key = color.strip().lower()

        # Check cache first
        if key in self.color_cache:
            return self.color_cache[key]

        self.logger.info(f'{color} not found in color_cache. Making an API call to OpenAI...')
        url = "https://api.openai.com/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "gpt-4o-mini",
            "temperature": 0,
            "max_tokens": 5,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": color,
                },
            ],
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()

            matched = response.json()["choices"][0]["message"]["content"].strip()

            if matched not in FB_COLORS:
                matched = "Other"

        except Exception as e:
            self.logger.error(f"Color matching failed for '{color}': {e}")
            matched = "Other"

        # Update cache
        self.color_cache[key] = matched
        self.save_color_cache()

        return matched