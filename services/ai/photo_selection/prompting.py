from __future__ import annotations

import html
import re
from typing import Any

from settings import GEMINI_AREA_LABELS
from domain.properties.model import Property


def clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def html_to_text(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li\s*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("Ã¢â€šÂ¬", "â‚¬")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_property_features(raw_features: object) -> list[str]:
    items: list[str] = []
    if not isinstance(raw_features, (list, tuple, set)):
        return items

    for raw_entry in raw_features:
        entry = html_to_text(raw_entry)
        if not entry:
            continue
        for part in entry.split("|"):
            cleaned = clean_whitespace(part)
            if cleaned:
                items.append(cleaned)
    return items


def format_property_features_for_prompt(features: list[str]) -> str:
    if not features:
        return "- None provided"
    return "\n".join(f"- {feature}" for feature in features)


def slugify(value: object, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "")).strip("-_.")
    return text or fallback


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def clamp_int(value: object, default: int = 0) -> int:
    return max(0, min(100, parse_int(value, default)))


def normalize_caption(value: object, fallback: str = "") -> str:
    caption = clean_whitespace(str(value or ""))
    caption = caption.strip("\"'")
    caption = re.sub(
        r"^(?:key\s+features|features)\s*:\s*",
        "",
        caption,
        flags=re.IGNORECASE,
    )
    caption = clean_whitespace(caption)
    if not caption:
        return fallback
    if caption[-1] not in ".!?":
        caption = f"{caption}."
    return caption


def normalize_space_id(value: object, area: str) -> str:
    raw = clean_whitespace(str(value or ""))
    normalized = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    if not normalized:
        normalized = area
    return normalized[:80]


def normalize_highlights(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    highlights: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = clean_whitespace(str(item or ""))
        text = text.strip("\"'.,;:-")
        if not text:
            continue
        if len(text) > 1 and any(character.islower() for character in text[1:]):
            text = text[0].lower() + text[1:]
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        highlights.append(text)
        if len(highlights) >= 4:
            break
    return highlights


def normalize_reject_reason(value: object) -> str | None:
    text = clean_whitespace(str(value or "")).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or None


def build_property_context(property_item: Property) -> dict[str, Any]:
    title = html_to_text(property_item.title)
    excerpt = html_to_text(property_item.excerpt_html)
    description = html_to_text(property_item.content_html)
    property_features = split_property_features(property_item.property_features)
    bedrooms = str(property_item.bedrooms or "").strip()
    bathrooms = str(property_item.bathrooms or "").strip()
    ber_rating = str(property_item.ber_rating or "").strip()
    property_type = clean_whitespace(str(property_item.property_type_label or ""))
    status = clean_whitespace(str(property_item.property_status or ""))
    address = clean_whitespace(
        ", ".join(
            part
            for part in [
                html_to_text(property_item.title),
                clean_whitespace(str(property_item.eircode or "")),
            ]
            if part
        )
    )

    context_lines = []
    if title:
        context_lines.append(f"Title: {title}")
    if address:
        context_lines.append(f"Address: {address}")
    if property_type:
        context_lines.append(f"Property type: {property_type}")
    if status:
        context_lines.append(f"Status: {status}")
    if bedrooms:
        context_lines.append(f"Bedrooms: {bedrooms}")
    if bathrooms:
        context_lines.append(f"Bathrooms: {bathrooms}")
    if ber_rating:
        context_lines.append(f"BER rating: {ber_rating}")
    if excerpt:
        context_lines.append(f"Excerpt: {excerpt}")
    if description:
        context_lines.append(f"Description: {description}")
    if property_features:
        context_lines.append("Property features:")
        context_lines.extend(f"- {feature}" for feature in property_features)

    summary_parts = []
    if property_type:
        summary_parts.append(property_type)
    if status:
        summary_parts.append(status)
    if bedrooms:
        summary_parts.append(f"{bedrooms} bedrooms")
    if bathrooms:
        summary_parts.append(f"{bathrooms} bathroom")
    if ber_rating:
        summary_parts.append(f"BER {ber_rating}")

    property_features_text = format_property_features_for_prompt(property_features)

    return {
        "id": property_item.id,
        "title": title,
        "address": address,
        "excerpt": excerpt,
        "description": description,
        "property_features": property_features,
        "property_type": property_type,
        "status": status,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "ber_rating": ber_rating,
        "summary": ", ".join(summary_parts),
        "context_text": "\n".join(context_lines).strip(),
        "property_features_text": property_features_text,
        "importer_id": str(property_item.importer_id or property_item.id or "property"),
    }


def build_prompt(property_context: dict[str, Any]) -> str:
    labels = "\n".join(f"- {label}" for label in GEMINI_AREA_LABELS)
    json_shape = """{
  "area": "one_label_from_the_list",
  "confidence": 0,
  "showcase_score": 0,
  "space_id": "short_snake_case_space_identifier",
  "highlights": ["short factual fragments"],
  "caption": "short estate-agent style fragment",
  "reject_asset": false,
  "reject_reason": null
}"""
    return f"""
You are selecting photos for a real-estate sales presentation and generating short slide copy for each selected image.

Use the property context below as factual background. Never invent details. Only mention:
- what is clearly visible in the image
- exact global facts from the property context

Property context:
{property_context["context_text"]}

Main features provided by the agent or listing:
{property_context["property_features_text"]}

Classify the image and score how suitable it is for a sales deck.

Choose exactly one label from this list:
{labels}

Reply ONLY with valid JSON in this exact shape:
{json_shape}

Rules:
- "confidence" must be an integer between 0 and 100.
- "showcase_score" must be an integer between 0 and 100.
- "space_id" must identify the exact physical space shown. Photos of the same room or same outdoor area must use the same space_id.
- Different bedrooms must use different space_id values. Different bathrooms must use different space_id values.
- Never select a floor plan, house plan, site plan, location map, aerial/satellite image, sky view, brochure graphic, or any other non-photo property asset.
- Do not confuse an open-plan living/kitchen space with a floor plan drawing.
- If the image is any rejected non-photo asset, set:
  - "area" to "other"
  - "showcase_score" to 0
  - "space_id" to "discarded_non_photo_asset"
  - "highlights" to []
  - "caption" to "Discarded non-photo asset"
  - "reject_asset" to true
  - "reject_reason" to a short snake_case reason such as "floorplan", "map", or "aerial_view"
- If the image is a normal saleable property photo, set "reject_asset" to false and "reject_reason" to null.
- If the image shows an open-plan kitchen, dining, and living area, use one shared space_id for that whole space.
- "highlights" must contain 2 to 4 short factual fragments, not full sentences.
- Prefer highlights that help distinguish this space from other photos of the same property.
- "caption" must be a single short line in Irish English, suitable for a slide voiceover.
- The caption must read like concise estate-agent feature copy, not like descriptive prose.
- Do not start the caption with labels such as "Key features", "Features", or similar.
- Use concise feature-style wording, for example:
  - "Fully fitted bathroom"
  - "Bright open-plan kitchen/dining area"
  - "Private rear garden"
- Do not write full descriptive sentences such as:
  - "This bathroom is fully equipped..."
  - "This lovely room offers..."
  - "You are welcomed into..."
- Keep the caption positive, factual, and compact.
- Do not invent finishes, light quality, room size, views, layout, condition, amenities, or selling points that are not clearly visible or explicitly stated in the property context.
- Do not mention movable furniture or furnishings, as these are generally not included in the sale.
- The only exception is fixed or fitted kitchen equipment/appliances, and only if clearly visible or explicitly supported by the property context.
- Avoid redundant captions. If the image already clearly shows the room type, do not waste the caption on obvious wording like "Bathroom" or "Bedroom". Prefer the distinguishing feature instead.
- Reuse the wording and terminology found in the property context and main features wherever possible.
- Do not invent marketing phrases or unusual wording. Prefer standard estate-agent language that matches the source material.
- You may use exact global facts like number of bedrooms, number of bathrooms, BER rating, own-door access, excellent condition, or private outdoor space only if they are true in the property context.
- If the image is the neighbourhood / location overview / first slide image, the caption must summarise the property in this format:
  "[house/apartment type if known] in [area], [X] bedrooms, [Y] bathrooms, BER [rating]"
- For the neighbourhood / first slide caption, only include the property type, area, bedroom count, bathroom count, and BER if each item is explicitly available in the property context.
- If any of those first-slide facts are missing, omit only the missing item and keep the rest factual.
- Prefer describing the most relevant selling feature of the specific space shown.
- Do not include markdown or extra text.
- "caption" must be a single short line in Irish English, suitable for a slide voiceover.
- The caption must be short enough to be spoken comfortably in about 4 seconds.
- Aim for approximately 6 to 10 words in total.
- Prefer one concise feature phrase rather than multiple clauses.
- Avoid long sentences, stacked adjectives, or lists of several features in one caption.
"""


__all__ = [
    "build_prompt",
    "build_property_context",
    "clamp_int",
    "clean_whitespace",
    "format_property_features_for_prompt",
    "html_to_text",
    "normalize_caption",
    "normalize_highlights",
    "normalize_reject_reason",
    "normalize_space_id",
    "parse_int",
    "slugify",
    "split_property_features",
]
