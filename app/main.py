#!/usr/bin/env python3
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import traceback
import uuid
from urllib.error import HTTPError, URLError
from html import unescape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent.parent
BUNDLED_SKILLS_DIR = BASE_DIR / "skills"
HOST = os.environ.get("WEBSITE_REDESIGN_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEBSITE_REDESIGN_PORT", "4321"))
MODEL = os.environ.get("WEBSITE_REDESIGN_MODEL", "deepseek/deepseek-v4-flash")
ROOT = Path(os.environ.get("WEBSITE_REDESIGN_ROOT", "/data"))
SKILLS_DIR = Path(os.environ.get("WEBSITE_REDESIGN_SKILLS_DIR", str(ROOT / "skills")))
DEFAULT_INDUSTRY = os.environ.get("WEBSITE_REDESIGN_DEFAULT_INDUSTRY", "general")
FIRECRAWL_URL = os.environ.get("WEBSITE_REDESIGN_FIRECRAWL_URL", "http://127.0.0.1:3092").rstrip("/")
FIRECRAWL_SCRAPE_TIMEOUT = int(os.environ.get("WEBSITE_REDESIGN_FIRECRAWL_TIMEOUT", "90"))
SEO_AUDIT_TIMEOUT = int(os.environ.get("WEBSITE_REDESIGN_SEO_AUDIT_TIMEOUT", "120"))
IMPECCABLE_TIMEOUT = int(os.environ.get("WEBSITE_REDESIGN_IMPECCABLE_TIMEOUT", "180"))
LIGHTHOUSE_TIMEOUT = int(os.environ.get("WEBSITE_REDESIGN_LIGHTHOUSE_TIMEOUT", "180"))
AXE_TIMEOUT = int(os.environ.get("WEBSITE_REDESIGN_AXE_TIMEOUT", "180"))
VISUAL_AUDIT_TIMEOUT = int(os.environ.get("WEBSITE_REDESIGN_VISUAL_AUDIT_TIMEOUT", "120"))
DEFAULT_CONTENT_CRITIQUE = os.environ.get("WEBSITE_REDESIGN_CONTENT_CRITIQUE", "true")
DEFAULT_CONTENT_AUTOFIX = os.environ.get("WEBSITE_REDESIGN_CONTENT_AUTOFIX", "true")
DEFAULT_SEO_CRITIQUE = os.environ.get("WEBSITE_REDESIGN_SEO_CRITIQUE", "true")
DEFAULT_SEO_AUTOFIX = os.environ.get("WEBSITE_REDESIGN_SEO_AUTOFIX", "true")
DEFAULT_IMPECCABLE_CRITIQUE = os.environ.get("WEBSITE_REDESIGN_IMPECCABLE_CRITIQUE", "true")
DEFAULT_IMPECCABLE_AUTOFIX = os.environ.get("WEBSITE_REDESIGN_IMPECCABLE_AUTOFIX", "true")
DEFAULT_LIGHTHOUSE_CRITIQUE = os.environ.get("WEBSITE_REDESIGN_LIGHTHOUSE_CRITIQUE", "true")
DEFAULT_LIGHTHOUSE_AUTOFIX = os.environ.get("WEBSITE_REDESIGN_LIGHTHOUSE_AUTOFIX", "true")
DEFAULT_AXE_CRITIQUE = os.environ.get("WEBSITE_REDESIGN_AXE_CRITIQUE", "true")
DEFAULT_AXE_AUTOFIX = os.environ.get("WEBSITE_REDESIGN_AXE_AUTOFIX", "true")
IMPECCABLE_MAX_FINDINGS = int(os.environ.get("WEBSITE_REDESIGN_IMPECCABLE_MAX_FINDINGS", "8"))
IMPECCABLE_MAX_REFINEMENT_PASSES = int(os.environ.get("WEBSITE_REDESIGN_IMPECCABLE_MAX_REFINEMENT_PASSES", "2"))
SEO_MAX_REFINEMENT_PASSES = int(os.environ.get("WEBSITE_REDESIGN_SEO_MAX_REFINEMENT_PASSES", "1"))
CONTENT_MAX_REFINEMENT_PASSES = int(os.environ.get("WEBSITE_REDESIGN_CONTENT_MAX_REFINEMENT_PASSES", "1"))
LIGHTHOUSE_MAX_REFINEMENT_PASSES = int(os.environ.get("WEBSITE_REDESIGN_LIGHTHOUSE_MAX_REFINEMENT_PASSES", "1"))
AXE_MAX_REFINEMENT_PASSES = int(os.environ.get("WEBSITE_REDESIGN_AXE_MAX_REFINEMENT_PASSES", "1"))
ALLOWED_GENERATOR_PROFILES = {"lean", "balanced", "quality"}
ALLOWED_IMAGE_STRATEGIES = {"source-only", "source-first", "hybrid", "stock-first"}
ALLOWED_SOURCE_EXPANSION_MODES = {"strict", "balanced", "aggressive"}
ALLOWED_RUN_MODES = {"prospect", "refined"}
DEFAULT_SKILLS = [
    item.strip()
    for item in os.environ.get(
        "WEBSITE_REDESIGN_DEFAULT_SKILLS",
        "website-audit,design-direction,layout-composer,frontend-art-direction,design-critic",
    ).split(",")
    if item.strip()
]

RUN_MODE_DEFAULTS = {
    "prospect": {
        "generator_profile": "lean",
        "source_expansion_mode": "strict",
        "search_enrichment": True,
        "search_budget": 2,
        "content_critique": True,
        "content_autofix": False,
        "seo_critique": True,
        "seo_autofix": False,
        "impeccable_critique": False,
        "impeccable_autofix": False,
        "lighthouse_critique": False,
        "lighthouse_autofix": False,
        "axe_critique": False,
        "axe_autofix": False,
    },
    "refined": {
        "generator_profile": "balanced",
        "source_expansion_mode": "balanced",
        "search_enrichment": True,
        "search_budget": 4,
        "content_critique": True,
        "content_autofix": True,
        "seo_critique": True,
        "seo_autofix": True,
        "impeccable_critique": True,
        "impeccable_autofix": True,
        "lighthouse_critique": True,
        "lighthouse_autofix": False,
        "axe_critique": True,
        "axe_autofix": False,
    },
}

DESIGN_FAMILY_LIBRARY = {
    "editorial-luxury": {
        "summary": "High-contrast editorial hospitality direction with dramatic type, cinematic imagery, and restrained premium surfaces.",
        "ideal_for": ["restaurant", "hotel", "bar", "salon", "boutique"],
        "typography": "Expressive serif display paired with clean sans-serif body copy.",
        "palette": "Cream, ink, oxblood, brass, and smoked neutrals.",
        "layout": "Large image-led hero, alternating narrative bands, generous whitespace, and gallery interludes.",
        "components": "Understated navigation, elegant reservation CTA, image-framed testimonials, and editorial menu/story sections.",
        "motion": "Slow fades, soft reveal transitions, and no flashy motion.",
        "anti_patterns": "Do not use startup-style feature grids, tiny type, or neon accents.",
    },
    "warm-hospitality": {
        "summary": "Tactile, welcoming, and polished neighborhood-premium direction for food, beverage, and service brands.",
        "ideal_for": ["restaurant", "cafe", "bakery", "spa", "general"],
        "typography": "Soft serif or humanist display with warm sans-serif support.",
        "palette": "Stone, parchment, terracotta, deep espresso, and muted olive accents.",
        "layout": "Story-led hero, cozy content width, layered imagery, and rhythm built around atmosphere and trust.",
        "components": "Rounded CTA pills, proof strips, gallery clusters, and service cards with subtle warmth.",
        "motion": "Minimal parallax feel through composition only; motion stays subtle.",
        "anti_patterns": "Avoid harsh black-on-white tech aesthetics and sterile card walls.",
    },
    "cinematic-bold": {
        "summary": "Big, dramatic, high-impact direction for brands that need to feel aspirational, visual, and memorable fast.",
        "ideal_for": ["restaurant", "event", "fitness", "entertainment", "general"],
        "typography": "Bold display typography with sharp supporting sans.",
        "palette": "Dark base with one strong accent and bright text contrast.",
        "layout": "Immersive hero, oversized sections, assertive CTA moments, and bold image framing.",
        "components": "Statement hero, punchy offer bands, oversized testimonials, and dramatic stat/proof modules.",
        "motion": "Confident but restrained motion using opacity and transform only.",
        "anti_patterns": "Do not introduce gradients, glassmorphism, or trendy AI hero effects.",
    },
    "crisp-trust": {
        "summary": "Clean, premium trust-first direction for professional local businesses that must feel capable and expensive.",
        "ideal_for": ["dentist", "legal", "medical", "accounting", "consulting"],
        "typography": "Structured sans-serif hierarchy with occasional refined serif accenting.",
        "palette": "Soft neutrals, deep slate, muted blue/green trust accents, and clean whitespace.",
        "layout": "Clear problem-solution flow, strong proof modules, and service sections with excellent readability.",
        "components": "Sticky CTA, comparison/proof bands, clean cards, trust badges, and FAQ/support sections.",
        "motion": "Almost static; use only subtle polish.",
        "anti_patterns": "Avoid generic SaaS icon grids and weak low-contrast gray body text.",
    },
    "craftsman-premium": {
        "summary": "Solid, tactile, high-trust direction for trades and local services that need to feel skilled rather than templated.",
        "ideal_for": ["plumber", "contractor", "electrician", "hvac", "landscaping"],
        "typography": "Confident sans-serif hierarchy with selective slab or serif emphasis.",
        "palette": "Bone, charcoal, metal, copper, rust, or deep service-color accents.",
        "layout": "Strong hero promise, service proof blocks, before/after or process rhythm, and practical CTAs.",
        "components": "Large CTA bars, service cards, testimonial slabs, process timeline, and coverage area sections.",
        "motion": "Minimal and utility-focused.",
        "anti_patterns": "Avoid cute startup illustrations, generic dashboard motifs, and tiny centered text blocks.",
    },
    "modern-approachable": {
        "summary": "Fresh, airy, contemporary direction for small businesses that need clarity without feeling cold or templated.",
        "ideal_for": ["general", "retail", "studio", "wellness", "service"],
        "typography": "Readable modern sans with one distinctive accent face or typographic treatment.",
        "palette": "Clean light base, controlled accent color, and soft contrast surfaces.",
        "layout": "Balanced hero, modular content rhythm, friendly proof sections, and sharp CTA moments.",
        "components": "Simple cards, image-text alternation, FAQ modules, and approachable callouts.",
        "motion": "Light stagger and reveal only.",
        "anti_patterns": "Avoid flat default Tailwind landing-page layouts and interchangeable hero copy.",
    },
}

MAGICUI_COMPONENT_LIBRARY = {
    "editorial-luxury": {
        "hero_pattern": "full-bleed image hero with dark overlay, restrained top nav, oversized serif headline, and one primary reservation CTA",
        "nav_pattern": "minimal transparent nav that resolves into a solid dark bar on scroll with one standout CTA button",
        "cta_pattern": "pill or soft-rectangle CTA with premium contrast, subtle shadow, and understated hover lift",
        "surface_pattern": "layered warm surfaces with framed imagery, thin borders, and glass-free depth",
        "gallery_pattern": "editorial staggered image grid with asymmetric crops and occasional full-width image breaks",
        "proof_pattern": "compact proof strip and quote cards rather than generic testimonial sliders",
        "menu_pattern": "curated menu spotlight cards with daypart grouping, featured dish callouts, and premium framing",
        "footer_pattern": "dark closing section with location, hours, contact CTA, and embedded map/directions block",
        "motion_pattern": "subtle reveal, opacity, and translate-only transitions; no parallax gimmicks",
        "decor_pattern": "soft accent glows, ruled dividers, and tasteful badge chips instead of startup icon walls",
    },
    "warm-hospitality": {
        "hero_pattern": "welcoming split or layered hero with food-led photography, short appetite-first headline, and immediate visit/order CTA",
        "nav_pattern": "friendly compact nav with rounded CTA and clear menu/location anchors",
        "cta_pattern": "rounded warm CTA buttons with strong text contrast and obvious tap targets",
        "surface_pattern": "soft elevated cards, warm background bands, and cozy content containers with visible breathing room",
        "gallery_pattern": "collage-style gallery clusters with varied image sizes and appetite-first crops",
        "proof_pattern": "trust strip, family story block, and short review-style proof only when evidence exists",
        "menu_pattern": "visual menu highlight modules organized by breakfast/lunch/dinner or signature specialties, built into the page",
        "footer_pattern": "high-trust footer with address, phone, hours, map embed or directions link, and quick visit CTA",
        "motion_pattern": "gentle reveal and hover polish only; no distracting scene changes",
        "decor_pattern": "warm chips, badges, dividers, and subtle grain/texture cues without fake retro clutter",
    },
    "cinematic-bold": {
        "hero_pattern": "immersive dark hero with dramatic crop, bold headline, and one dominant CTA with one secondary text action",
        "nav_pattern": "thin high-contrast nav with compact menu and strong CTA emphasis",
        "cta_pattern": "high-contrast button pair with assertive hover polish and strong spacing",
        "surface_pattern": "dark layered panels with heavy contrast and oversized section framing",
        "gallery_pattern": "large cinematic tiles and alternating panorama breaks",
        "proof_pattern": "oversized trust metrics and bold quote band instead of small cards",
        "menu_pattern": "statement feature blocks and signature items with dramatic imagery and concise copy",
        "footer_pattern": "bold closing block with direct contact, venue info, and location utility",
        "motion_pattern": "cinematic fade/translate only; no flashy transforms",
        "decor_pattern": "accent bars, oversized numbers, and strong section transitions without gradients",
    },
    "crisp-trust": {
        "hero_pattern": "clarity-first hero with concise promise, supporting proof, and immediate consultation CTA",
        "nav_pattern": "solid trust-first nav with sticky CTA and simple anchor structure",
        "cta_pattern": "clean rectangular CTA with strong accessibility contrast and no decorative effects",
        "surface_pattern": "bright structured cards with crisp borders and controlled shadows",
        "gallery_pattern": "sparingly used supportive imagery with clean framing rather than decorative collage",
        "proof_pattern": "metrics strip, credential cards, and FAQ/proof accordion modules",
        "menu_pattern": "service or offering modules arranged in digestible cards rather than promotional blurbs",
        "footer_pattern": "service-area and contact footer with map/directions, NAP, and structured trust links",
        "motion_pattern": "minimal utility-focused transitions only",
        "decor_pattern": "precision dividers, badges, and layout accents with no ornamental noise",
    },
    "craftsman-premium": {
        "hero_pattern": "outcome-led hero with strong service promise, phone CTA, and proof badges",
        "nav_pattern": "practical nav with visible phone/quote CTA and sticky conversion row",
        "cta_pattern": "large dependable CTA bars with clear action verbs and strong contrast",
        "surface_pattern": "solid service cards, textured dark bands, and before/after modules",
        "gallery_pattern": "project or craftsmanship grid with stronger documentary treatment",
        "proof_pattern": "trust badges, service guarantees, and process timeline modules",
        "menu_pattern": "service package or offering cards with clear scopes and proof points",
        "footer_pattern": "service-area footer with phone, hours, address, and map/directions utility",
        "motion_pattern": "limited hover and reveal motion only",
        "decor_pattern": "industrial accents, linework, and grounded visual weight without tech styling",
    },
    "modern-approachable": {
        "hero_pattern": "balanced modern hero with approachable imagery, concise positioning, and clear primary CTA",
        "nav_pattern": "simple high-legibility nav with one strong CTA and tight section anchors",
        "cta_pattern": "clean rounded CTA with subtle depth and strong mobile sizing",
        "surface_pattern": "modular cards, clean background bands, and generous spacing",
        "gallery_pattern": "tidy alternating media blocks and modular image cards",
        "proof_pattern": "compact story/proof modules and clean FAQ sections",
        "menu_pattern": "digestible highlight cards or mini-feature grids built into the main page",
        "footer_pattern": "clean footer with contact block, hours if relevant, and map/directions support",
        "motion_pattern": "light stagger and hover polish only",
        "decor_pattern": "soft accent shapes and subtle dividers without trend-chasing visuals",
    },
}

INDUSTRY_DEFAULT_FAMILIES = {
    "restaurant": "editorial-luxury",
    "cafe": "warm-hospitality",
    "bakery": "warm-hospitality",
    "bar": "cinematic-bold",
    "hotel": "editorial-luxury",
    "spa": "warm-hospitality",
    "salon": "editorial-luxury",
    "plumber": "craftsman-premium",
    "electrician": "craftsman-premium",
    "hvac": "craftsman-premium",
    "contractor": "craftsman-premium",
    "roofer": "craftsman-premium",
    "landscaper": "craftsman-premium",
    "pest-control": "craftsman-premium",
    "cleaning": "modern-approachable",
    "auto-detailing": "modern-approachable",
    "dentist": "crisp-trust",
    "orthodontist": "crisp-trust",
    "medical": "crisp-trust",
    "medspa": "editorial-luxury",
    "chiropractor": "crisp-trust",
    "vet": "warm-hospitality",
    "legal": "crisp-trust",
    "accounting": "crisp-trust",
    "consulting": "crisp-trust",
    "retail": "modern-approachable",
    "florist": "modern-approachable",
    "boutique": "editorial-luxury",
    "jewelry": "editorial-luxury",
    "furniture": "modern-approachable",
    "fitness": "cinematic-bold",
    "wellness": "modern-approachable",
    "general": "modern-approachable",
}

INDUSTRY_ALIAS_MAP = {
    "coffee-shop": "cafe",
    "coffeehouse": "cafe",
    "brunch": "cafe",
    "wine-bar": "bar",
    "pub": "bar",
    "roofing": "roofer",
    "roofing-company": "roofer",
    "roofing-contractor": "roofer",
    "landscape": "landscaper",
    "landscaping": "landscaper",
    "landscaping-company": "landscaper",
    "exterminator": "pest-control",
    "pest": "pest-control",
    "pestcontrol": "pest-control",
    "pest-control-company": "pest-control",
    "house-cleaning": "cleaning",
    "home-cleaning": "cleaning",
    "cleaning-service": "cleaning",
    "maid-service": "cleaning",
    "car-detailing": "auto-detailing",
    "automotive-detailing": "auto-detailing",
    "detailing": "auto-detailing",
    "med-spa": "medspa",
    "medical-spa": "medspa",
    "orthodontics": "orthodontist",
    "orthodontic": "orthodontist",
    "chiropractic": "chiropractor",
    "veterinarian": "vet",
    "veterinary": "vet",
    "flower-shop": "florist",
    "hair-salon": "salon",
    "jeweler": "jewelry",
    "jewellery": "jewelry",
    "furniture-store": "furniture",
    "interior-design": "furniture",
    "gym": "fitness",
    "personal-training": "fitness",
    "law-firm": "legal",
    "lawyer": "legal",
    "bookkeeping": "accounting",
    "cpa": "accounting",
}

NICHE_SUBTYPE_LIBRARY = {
    "restaurant-diner": {
        "industries": {"restaurant"},
        "signal_terms": {"diner", "breakfast", "all day breakfast", "comfort food", "omelet", "omelette", "pancake"},
        "family": "warm-hospitality",
        "schema_type": "Restaurant",
        "conversion_priority": ["call-now", "location-and-hours", "menu-confidence"],
        "section_flow": [
            "Warm hero with primary CTA",
            "Trust/story introduction",
            "Breakfast-lunch-dinner menu highlights",
            "Signature comfort-food band",
            "Photo-led atmosphere and visit close",
        ],
        "component_adaptations": [
            "Favor honest appetite-led photography over moody luxury staging.",
            "Keep menu highlights immediately scannable and daypart-driven.",
            "Use friendlier, neighborhood-scale typography and warmer surfaces.",
            "Prefer proof strips, service warmth, and visit confidence over aspirational brand theater.",
        ],
        "required_sections": [
            "hero",
            "family story / trust strip",
            "breakfast-lunch-dinner menu highlights",
            "signature dishes or comfort-food feature band",
            "photo-led atmosphere / gallery",
            "visit info with hours, phone, address, and map",
        ],
        "rewrite_targets": ["menu highlights", "about copy", "visit/location copy"],
        "section_notes": [
            "Reframe the business as a beloved, reliable local diner rather than a generic restaurant.",
            "Preserve diner warmth and familiarity while making the menu presentation more polished and persuasive.",
            "Prefer rewritten section copy with stronger appetite appeal over literal source reuse.",
        ],
    },
    "restaurant-cafe": {
        "industries": {"restaurant", "cafe"},
        "signal_terms": {"cafe", "coffee", "espresso", "latte", "brunch"},
        "family": "warm-hospitality",
        "schema_type": "CafeOrCoffeeShop",
        "conversion_priority": ["visit-now", "menu-confidence", "hours-and-location"],
        "section_flow": [
            "Friendly hero with coffee or brunch emphasis",
            "Signature drinks or baked goods strip",
            "Menu highlights and ambience",
            "Community/story module",
            "Visit close with map and hours",
        ],
        "component_adaptations": [
            "Use lighter pacing, brighter surfaces, and more approachable editorial copy than a full-service restaurant.",
            "Make the hero and gallery feel morning-light and social rather than cinematic.",
        ],
        "required_sections": [
            "hero",
            "signature drinks / baked goods highlights",
            "menu highlights",
            "story or community block",
            "visit info with hours, phone, address, and map",
        ],
        "rewrite_targets": ["menu highlights", "brand voice", "visit/location copy"],
        "section_notes": [
            "Make the business feel like a habitual local favorite rather than a special-occasion restaurant.",
        ],
    },
    "restaurant-bakery": {
        "industries": {"restaurant", "bakery"},
        "signal_terms": {"bakery", "pastry", "cakes", "bread", "dessert"},
        "family": "warm-hospitality",
        "schema_type": "Bakery",
        "conversion_priority": ["visit-now", "product-confidence", "location-and-hours"],
        "section_flow": [
            "Product-led hero",
            "Bestsellers or seasonal spotlight",
            "Freshness / craft story",
            "Gift or pre-order CTA",
            "Visit close with map and hours",
        ],
        "component_adaptations": [
            "Favor tactile close-up product framing and softer merchandising rhythms.",
            "Make product cards and ordering cues clearer than a standard restaurant menu strip.",
        ],
        "required_sections": [
            "hero",
            "bestsellers / seasonal picks",
            "craft story",
            "ordering or gifting CTA",
            "visit info with hours, phone, address, and map",
        ],
        "rewrite_targets": ["product highlights", "freshness story", "CTA copy"],
    },
    "restaurant-pizzeria": {
        "industries": {"restaurant"},
        "signal_terms": {"pizza", "pizzeria", "slice", "wood-fired", "wood fired"},
        "family": "cinematic-bold",
        "schema_type": "Restaurant",
        "conversion_priority": ["order-now", "menu-confidence", "location-and-hours"],
        "section_flow": [
            "Bold appetite-led hero",
            "Signature pies and menu categories",
            "Craft/process block",
            "Gallery or social proof strip",
            "Order or visit close",
        ],
        "component_adaptations": [
            "Push stronger appetite contrast and hotter, more energetic image treatment than a diner or cafe.",
            "Make ordering and signature item hierarchy immediate.",
        ],
        "required_sections": [
            "hero",
            "signature pies / menu highlights",
            "craft or ingredient story",
            "photo-led appetite section",
            "visit or order close with map and contact",
        ],
        "rewrite_targets": ["signature product copy", "CTA copy", "menu highlights"],
    },
    "restaurant-upscale": {
        "industries": {"restaurant", "hotel", "bar"},
        "signal_terms": {"fine dining", "chef", "tasting", "wine", "steak", "cocktail"},
        "family": "editorial-luxury",
        "schema_type": "Restaurant",
        "conversion_priority": ["reservations", "atmosphere", "location-and-hours"],
        "section_flow": [
            "Atmospheric hero with reservation-first CTA",
            "Positioning and concept band",
            "Signature menu spotlight",
            "Gallery or ambience story",
            "Reservation/location close",
        ],
        "component_adaptations": [
            "Push stronger editorial spacing and more restrained copy density.",
            "Use fewer but larger hero and gallery moments.",
        ],
        "required_sections": [
            "hero",
            "positioning/story",
            "signature menu spotlight",
            "atmosphere gallery",
            "reservation/location close",
        ],
        "rewrite_targets": ["reservation CTA", "chef or concept story"],
    },
    "restaurant-bar": {
        "industries": {"bar", "restaurant"},
        "signal_terms": {"bar", "pub", "taproom", "cocktails", "nightlife", "brewery"},
        "family": "cinematic-bold",
        "schema_type": "BarOrPub",
        "conversion_priority": ["visit-tonight", "events-or-specials", "location-and-hours"],
        "section_flow": [
            "Night-out hero",
            "Signature drinks or specials",
            "Atmosphere / events strip",
            "Proof or gallery block",
            "Visit close",
        ],
        "component_adaptations": [
            "Lean into nightlife contrast, event energy, and social-proof rhythm.",
        ],
        "required_sections": [
            "hero",
            "signature drinks / specials",
            "events or vibe strip",
            "gallery / proof",
            "visit close with map and hours",
        ],
        "rewrite_targets": ["specials copy", "events copy", "CTA copy"],
    },
    "trades-plumber": {
        "industries": {"plumber"},
        "signal_terms": {"plumbing", "drain", "water heater", "pipe", "leak"},
        "family": "craftsman-premium",
        "schema_type": "Plumber",
        "conversion_priority": ["call-now", "quote-request", "trust-and-coverage"],
        "section_flow": [
            "Urgent-value hero with phone CTA",
            "Core services overview",
            "Emergency / response / trust strip",
            "Process or service-area block",
            "Contact close with map",
        ],
        "component_adaptations": [
            "Emphasize conversion bars, phone trust, and emergency-response clarity over decorative galleries.",
        ],
        "required_sections": [
            "hero",
            "services overview",
            "emergency or trust strip",
            "coverage area / process",
            "contact close with map and phone",
        ],
        "rewrite_targets": ["service descriptions", "emergency CTA", "trust copy"],
        "section_notes": [
            "Make speed, trust, and competence clearer than general craftsmanship branding.",
        ],
    },
    "trades-electrician": {
        "industries": {"electrician"},
        "signal_terms": {"electrical", "panel", "rewiring", "lighting", "generator"},
        "family": "craftsman-premium",
        "schema_type": "Electrician",
        "conversion_priority": ["call-now", "quote-request", "safety-and-trust"],
        "required_sections": [
            "hero",
            "service cards",
            "safety / licensing proof strip",
            "project or process block",
            "contact close with map and service area",
        ],
        "rewrite_targets": ["service descriptions", "safety trust copy"],
        "section_notes": [
            "Push safety, professionalism, and clarity more than generic trade bravado.",
        ],
    },
    "trades-hvac": {
        "industries": {"hvac"},
        "signal_terms": {"hvac", "heating", "cooling", "air conditioning", "furnace"},
        "family": "craftsman-premium",
        "schema_type": "HomeAndConstructionBusiness",
        "conversion_priority": ["call-now", "seasonal-service", "trust-and-coverage"],
        "required_sections": [
            "hero",
            "heating and cooling service modules",
            "seasonal maintenance / emergency strip",
            "coverage or financing block",
            "contact close with map and phone",
        ],
        "rewrite_targets": ["service descriptions", "seasonal CTA", "trust copy"],
    },
    "trades-roofer": {
        "industries": {"roofer"},
        "signal_terms": {"roof", "roofing", "shingle", "storm damage", "gutter"},
        "family": "craftsman-premium",
        "schema_type": "HomeAndConstructionBusiness",
        "conversion_priority": ["inspection-request", "storm-response", "trust-and-proof"],
        "required_sections": [
            "hero",
            "roofing services overview",
            "storm damage / inspection CTA strip",
            "project gallery or before-after",
            "coverage and contact close",
        ],
        "rewrite_targets": ["inspection CTA", "service descriptions", "storm-response copy"],
        "section_notes": [
            "Bias toward inspection and damage-response confidence instead of generic contractor language.",
        ],
    },
    "trades-landscaper": {
        "industries": {"landscaper"},
        "signal_terms": {"landscape", "lawn", "hardscape", "outdoor living", "garden"},
        "family": "modern-approachable",
        "schema_type": "HomeAndConstructionBusiness",
        "conversion_priority": ["quote-request", "project-appeal", "coverage-and-contact"],
        "required_sections": [
            "hero",
            "service highlights",
            "project gallery",
            "process or seasonal services block",
            "coverage and contact close",
        ],
        "rewrite_targets": ["service descriptions", "gallery captions", "CTA copy"],
        "section_notes": [
            "Make the site feel more design-forward and visual than utility-first trade categories.",
        ],
    },
    "trades-pest-control": {
        "industries": {"pest-control"},
        "signal_terms": {"pest", "termite", "rodent", "exterminator", "mosquito"},
        "family": "crisp-trust",
        "schema_type": "HomeAndConstructionBusiness",
        "conversion_priority": ["call-now", "inspection-request", "trust-and-clarity"],
        "required_sections": [
            "hero",
            "problem / pest categories",
            "treatment process",
            "guarantee / proof strip",
            "contact close with service area",
        ],
        "rewrite_targets": ["problem-solution copy", "guarantee copy", "CTA copy"],
    },
    "service-cleaning": {
        "industries": {"cleaning"},
        "signal_terms": {"cleaning", "maid", "housekeeping", "deep clean", "janitorial"},
        "family": "modern-approachable",
        "schema_type": "HomeAndConstructionBusiness",
        "conversion_priority": ["quote-request", "trust-and-reliability", "service-clarity"],
        "required_sections": [
            "hero",
            "service packages or service types",
            "process / checklist block",
            "trust / reliability proof",
            "contact close",
        ],
        "rewrite_targets": ["service descriptions", "process copy", "CTA copy"],
    },
    "service-auto-detailing": {
        "industries": {"auto-detailing"},
        "signal_terms": {"detailing", "paint correction", "ceramic coating", "interior detail"},
        "family": "cinematic-bold",
        "schema_type": "AutoRepair",
        "conversion_priority": ["booking", "visual-proof", "package-clarity"],
        "required_sections": [
            "hero",
            "package highlights",
            "before-after or gallery",
            "process / coatings block",
            "booking close",
        ],
        "rewrite_targets": ["package copy", "visual proof captions", "CTA copy"],
    },
    "care-dentist": {
        "industries": {"dentist"},
        "signal_terms": {"dental", "dentist", "cleaning", "teeth", "family dentistry"},
        "family": "crisp-trust",
        "schema_type": "Dentist",
        "conversion_priority": ["appointment-booking", "trust-and-credentials", "service-clarity"],
        "required_sections": [
            "hero",
            "services",
            "trust / credentials",
            "patient comfort or FAQ",
            "appointment close with map",
        ],
        "rewrite_targets": ["service explanations", "comfort copy", "CTA copy"],
    },
    "care-orthodontist": {
        "industries": {"orthodontist"},
        "signal_terms": {"orthodont", "braces", "invisalign", "smile", "aligners"},
        "family": "crisp-trust",
        "schema_type": "Dentist",
        "conversion_priority": ["consultation", "transformation-proof", "service-clarity"],
        "required_sections": [
            "hero",
            "treatment options",
            "before-after or transformation proof",
            "comfort / financing / FAQ",
            "consultation close",
        ],
        "rewrite_targets": ["treatment copy", "transformation copy", "CTA copy"],
        "section_notes": [
            "Push treatment-option clarity and reassurance more than general family dentistry language.",
        ],
    },
    "care-medspa": {
        "industries": {"medspa", "spa"},
        "signal_terms": {"med spa", "injectables", "facial", "wellness", "aesthetic"},
        "family": "editorial-luxury",
        "schema_type": "HealthAndBeautyBusiness",
        "conversion_priority": ["consultation", "treatment-appeal", "trust-and-credentials"],
        "required_sections": [
            "hero",
            "signature treatments",
            "provider / trust strip",
            "results or atmosphere gallery",
            "consultation close",
        ],
        "rewrite_targets": ["treatment copy", "consultation CTA", "trust copy"],
        "section_notes": [
            "Balance premium beauty positioning with credible clinical reassurance.",
        ],
    },
    "care-chiropractor": {
        "industries": {"chiropractor"},
        "signal_terms": {"chiropractic", "back pain", "alignment", "wellness care"},
        "family": "crisp-trust",
        "schema_type": "MedicalBusiness",
        "conversion_priority": ["consultation", "pain-relief-clarity", "trust-and-location"],
        "required_sections": [
            "hero",
            "conditions or treatments",
            "care approach / trust block",
            "FAQ or first-visit expectations",
            "appointment close",
        ],
        "rewrite_targets": ["condition/treatment copy", "first-visit copy", "CTA copy"],
    },
    "care-vet": {
        "industries": {"vet"},
        "signal_terms": {"vet", "veterinary", "pet care", "animal hospital"},
        "family": "warm-hospitality",
        "schema_type": "VeterinaryCare",
        "conversion_priority": ["appointment", "trust-and-care", "service-clarity"],
        "required_sections": [
            "hero",
            "care services overview",
            "trust / pet comfort strip",
            "team or facility block",
            "appointment close with map",
        ],
        "rewrite_targets": ["service descriptions", "care philosophy", "CTA copy"],
    },
    "trust-legal": {
        "industries": {"legal"},
        "signal_terms": {"law", "attorney", "legal", "injury", "estate planning"},
        "family": "crisp-trust",
        "schema_type": "LegalService",
        "conversion_priority": ["consultation", "authority", "case-fit-clarity"],
        "required_sections": [
            "hero",
            "practice areas",
            "authority / results / trust strip",
            "FAQ or process",
            "consultation close",
        ],
        "rewrite_targets": ["practice area copy", "authority copy", "CTA copy"],
    },
    "trust-accounting": {
        "industries": {"accounting", "consulting"},
        "signal_terms": {"accounting", "tax", "bookkeeping", "cpa", "advisory"},
        "family": "crisp-trust",
        "schema_type": "ProfessionalService",
        "conversion_priority": ["consultation", "clarity-and-trust", "service-fit"],
        "required_sections": [
            "hero",
            "services",
            "proof / trust strip",
            "process or FAQ",
            "consultation close",
        ],
        "rewrite_targets": ["service explanations", "trust copy", "CTA copy"],
    },
    "retail-florist": {
        "industries": {"florist"},
        "signal_terms": {"florist", "flowers", "bouquet", "wedding flowers", "arrangements"},
        "family": "modern-approachable",
        "schema_type": "Florist",
        "conversion_priority": ["order-or-inquire", "occasion-fit", "visit-or-delivery"],
        "required_sections": [
            "hero",
            "occasion categories or featured arrangements",
            "gallery / product highlights",
            "story / local service block",
            "order or visit close",
        ],
        "rewrite_targets": ["occasion copy", "product highlights", "CTA copy"],
        "section_notes": [
            "Make the site feel giftable and emotionally specific, not like generic retail inventory.",
        ],
    },
    "retail-boutique": {
        "industries": {"boutique", "retail"},
        "signal_terms": {"boutique", "curated", "shop", "collection", "style"},
        "family": "editorial-luxury",
        "schema_type": "Store",
        "conversion_priority": ["visit-or-shop", "curation-proof", "brand-distinctiveness"],
        "required_sections": [
            "hero",
            "featured collections or categories",
            "brand story / curation block",
            "gallery or merchandising block",
            "visit or shop close",
        ],
        "rewrite_targets": ["collection copy", "brand story", "CTA copy"],
    },
    "retail-jewelry": {
        "industries": {"jewelry"},
        "signal_terms": {"jewelry", "engagement", "rings", "gold", "diamonds"},
        "family": "editorial-luxury",
        "schema_type": "Store",
        "conversion_priority": ["appointment", "collection-appeal", "trust-and-craft"],
        "required_sections": [
            "hero",
            "signature collections",
            "craftsmanship / trust block",
            "gallery or featured pieces",
            "appointment or visit close",
        ],
        "rewrite_targets": ["collection copy", "craft story", "CTA copy"],
    },
    "retail-furniture": {
        "industries": {"furniture"},
        "signal_terms": {"furniture", "interior", "sofa", "table", "design showroom"},
        "family": "modern-approachable",
        "schema_type": "Store",
        "conversion_priority": ["visit-showroom", "collection-clarity", "design-trust"],
        "required_sections": [
            "hero",
            "featured collections",
            "room or lifestyle gallery",
            "design service or showroom block",
            "visit close",
        ],
        "rewrite_targets": ["collection copy", "showroom copy", "CTA copy"],
    },
    "wellness-salon": {
        "industries": {"salon"},
        "signal_terms": {"salon", "hair", "stylist", "color", "blowout"},
        "family": "editorial-luxury",
        "schema_type": "BeautySalon",
        "conversion_priority": ["booking", "service-appeal", "proof-and-trust"],
        "required_sections": [
            "hero",
            "signature services",
            "stylist or brand story",
            "results / gallery",
            "booking close",
        ],
        "rewrite_targets": ["service copy", "brand story", "CTA copy"],
    },
    "wellness-fitness": {
        "industries": {"fitness"},
        "signal_terms": {"fitness", "gym", "training", "strength", "classes"},
        "family": "cinematic-bold",
        "schema_type": "SportsActivityLocation",
        "conversion_priority": ["trial-signup", "offer-clarity", "social-proof"],
        "required_sections": [
            "hero",
            "programs or classes",
            "proof / community strip",
            "facility or results gallery",
            "trial close",
        ],
        "rewrite_targets": ["program copy", "offer copy", "CTA copy"],
    },
}

ALLOWED_DESIGN_FAMILIES = set(DESIGN_FAMILY_LIBRARY)

JOBS_DIR = ROOT / "jobs"
PREVIEWS_DIR = ROOT / "previews"
QUALIFICATION_RUNS_DIR = ROOT / "qualification-runs"
STATE_LOCK = threading.Lock()


def resolve_public_base_url() -> str:
    for key in (
        "WEBSITE_REDESIGN_PUBLIC_BASE_URL",
        "SERVICE_URL_RUNNER_4321",
        "SERVICE_URL_RUNNER",
        "COOLIFY_URL",
    ):
        value = os.environ.get(key, "").strip().rstrip("/")
        if value:
            return value
    return f"http://127.0.0.1:{PORT}"


PUBLIC_BASE_URL = resolve_public_base_url()
GLOBAL_OPENCODE_CONFIG = Path(os.environ.get("OPENCODE_GLOBAL_CONFIG", "/root/.config/opencode/opencode.json"))


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    QUALIFICATION_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    bootstrap_skills_dir()


def bootstrap_skills_dir() -> None:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    bundled_files = [path for path in BUNDLED_SKILLS_DIR.rglob("*.md") if path.is_file()]
    if any(SKILLS_DIR.rglob("*.md")):
        return
    for source in bundled_files:
        relative = source.relative_to(BUNDLED_SKILLS_DIR)
        destination = SKILLS_DIR / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or f"site-{uuid.uuid4().hex[:8]}"


def parse_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def job_state_path(job_id: str) -> Path:
    return JOBS_DIR / job_id / "state.json"


def job_dir_path(job_id: str) -> Path:
    return JOBS_DIR / job_id


def update_state(job_id: str, **fields) -> dict:
    with STATE_LOCK:
        path = job_state_path(job_id)
        state = load_json(path)
        state.update(fields)
        state["updated_at"] = now_iso()
        write_json(path, state)
        return state


def get_state(job_id: str) -> dict | None:
    path = job_state_path(job_id)
    if not path.exists():
        return None
    return load_json(path)


def run_command(
    args: list[str],
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_dist_server(job_dir: Path) -> tuple[subprocess.Popen, str]:
    dist_dir = job_dir / "dist"
    port = reserve_port()
    process = subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(dist_dir)],
        cwd=str(job_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    url = f"http://127.0.0.1:{port}/index.html"
    for _ in range(30):
        if process.poll() is not None:
            raise RuntimeError("temporary preview server exited before audits could run")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return process, url
        except Exception:
            time.sleep(0.25)
    process.terminate()
    raise RuntimeError("temporary preview server did not become ready in time")


def stop_dist_server(process: subprocess.Popen | None) -> None:
    if not process:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def safe_relativize(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except Exception:
        return str(path)


def load_global_opencode_config() -> dict:
    if not GLOBAL_OPENCODE_CONFIG.exists():
        return {}
    try:
        return json.loads(GLOBAL_OPENCODE_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_local_opencode_config(job_dir: Path) -> Path:
    global_config = load_global_opencode_config()
    mcp_config = global_config.get("mcp", {}) if isinstance(global_config, dict) else {}

    local_config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {},
        "tools": {},
    }

    for server_name, server_config in mcp_config.items():
        if not isinstance(server_config, dict):
            continue
        disabled = dict(server_config)
        disabled["enabled"] = False
        local_config["mcp"][server_name] = disabled
        local_config["tools"][f"{server_name}_*"] = False

    config_path = job_dir / "opencode.local.json"
    config_path.write_text(json.dumps(local_config, indent=2), encoding="utf-8")
    return config_path


def validate_model_policy() -> None:
    if MODEL.startswith("openrouter/"):
        raise RuntimeError(
            "OpenRouter models are disabled for this runner. "
            "Configure a non-openrouter OpenCode model before starting the service."
        )


def truncate_text(value: str, limit: int = 1800) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def normalize_design_family(value: str) -> str:
    normalized = slugify(value)
    if normalized not in ALLOWED_DESIGN_FAMILIES:
        raise ValueError(f"design_family must be one of: {', '.join(sorted(ALLOWED_DESIGN_FAMILIES))}")
    return normalized


def canonicalize_industry(value: str) -> str:
    normalized = slugify(value)
    return INDUSTRY_ALIAS_MAP.get(normalized, normalized)


def summarize_value_list(items: list[str], fallback: str = "None") -> str:
    filtered = [item for item in items if item]
    return ", ".join(filtered) if filtered else fallback


def default_section_flow(industry: str, family_key: str, subtype: str = "") -> list[str]:
    niche = NICHE_SUBTYPE_LIBRARY.get(subtype or "")
    if niche and niche.get("section_flow"):
        return list(niche["section_flow"])
    if industry == "restaurant":
        if family_key == "editorial-luxury":
            return [
                "Atmospheric hero with reservation-first CTA",
                "Signature positioning and story band",
                "Image-led menu highlights",
                "Ambience gallery or social proof strip",
                "Location, hours, and reservation close",
            ]
        return [
            "Warm hero with primary CTA",
            "Trust/story introduction",
            "Menu or service highlights",
            "Photo-led proof or testimonials",
            "Visit/contact close",
        ]
    if family_key == "craftsman-premium":
        return [
            "Outcome-led hero with phone/quote CTA",
            "Why choose us proof strip",
            "Service cards or problem-solution blocks",
            "Process / before-after / testimonials",
            "Coverage area and strong close",
        ]
    if family_key == "crisp-trust":
        return [
            "Authority-led hero with primary CTA",
            "Trust metrics and proof",
            "Service overview and differentiators",
            "Testimonials / FAQ",
            "Consultation or contact close",
        ]
    return [
        "Distinctive hero with clear CTA",
        "Value proposition and business story",
        "Services or featured offerings",
        "Proof / testimonials / imagery",
        "Conversion-focused closing section",
    ]


def infer_conversion_priority(industry: str) -> list[str]:
    if industry == "restaurant":
        return ["reservations", "location-and-hours", "menu-confidence"]
    if industry in {"plumber", "electrician", "hvac", "contractor"}:
        return ["call-now", "quote-request", "trust-and-coverage"]
    if industry in {"dentist", "medical", "legal", "consulting"}:
        return ["consultation", "credibility", "service-clarity"]
    return ["primary-cta", "trust", "clarity"]


def infer_conversion_priority_for_subtype(industry: str, subtype: str) -> list[str]:
    niche = NICHE_SUBTYPE_LIBRARY.get(subtype)
    if niche and niche.get("conversion_priority"):
        return list(niche["conversion_priority"])
    return infer_conversion_priority(industry)


INDUSTRY_DETECTION_RULES = {
    "restaurant": {
        "strong": {
            "restaurant",
            "diner",
            "menu",
            "breakfast",
            "lunch",
            "dinner",
            "brunch",
            "omelette",
            "omelet",
            "pancakes",
            "burgers",
            "sandwiches",
            "reservations",
        },
        "weak": {"food", "eat", "kitchen", "cocktails", "drinks", "dessert", "appetizers"},
    },
    "bakery": {
        "strong": {"bakery", "pastry", "pastries", "bread", "cakes", "croissant", "cupcakes"},
        "weak": {"dessert", "baked", "sweet"},
    },
    "cafe": {
        "strong": {"cafe", "coffee", "espresso", "latte", "tea", "roastery"},
        "weak": {"barista", "brew", "brunch"},
    },
    "bar": {
        "strong": {"bar", "pub", "cocktail", "wine bar", "taproom", "brewery"},
        "weak": {"drinks", "beer", "happy hour"},
    },
    "hotel": {
        "strong": {"hotel", "inn", "resort", "suites", "lodging"},
        "weak": {"stay", "rooms", "book a stay"},
    },
    "plumber": {
        "strong": {"plumber", "plumbing", "drain cleaning", "water heater", "pipe repair"},
        "weak": {"leak", "sewer", "fixture"},
    },
    "electrician": {
        "strong": {"electrician", "electrical", "panel upgrade", "rewiring"},
        "weak": {"generator", "lighting", "wiring"},
    },
    "hvac": {
        "strong": {"hvac", "heating", "cooling", "air conditioning", "furnace"},
        "weak": {"ac repair", "heat pump", "thermostat"},
    },
    "contractor": {
        "strong": {"contractor", "construction", "remodeling", "renovation", "build"},
        "weak": {"project", "estimate", "licensed"},
    },
    "roofer": {
        "strong": {"roofing", "roofer", "roof repair", "roof replacement"},
        "weak": {"shingles", "gutter", "storm damage"},
    },
    "landscaper": {
        "strong": {"landscaping", "landscaper", "lawn care", "hardscape"},
        "weak": {"mulch", "yard", "patio"},
    },
    "pest-control": {
        "strong": {"pest control", "exterminator", "termite", "rodent"},
        "weak": {"bugs", "inspection", "ants"},
    },
    "cleaning": {
        "strong": {"cleaning service", "house cleaning", "maid service", "janitorial"},
        "weak": {"deep clean", "move out clean", "office cleaning"},
    },
    "auto-detailing": {
        "strong": {"auto detailing", "car detailing", "ceramic coating", "paint correction"},
        "weak": {"vehicle", "wash", "interior detail"},
    },
    "dentist": {
        "strong": {"dentist", "dental", "teeth cleaning", "oral health"},
        "weak": {"smile", "tooth", "crown"},
    },
    "orthodontist": {
        "strong": {"orthodontist", "braces", "invisalign", "orthodontics"},
        "weak": {"aligners", "bite", "retainer"},
    },
    "chiropractor": {
        "strong": {"chiropractor", "chiropractic", "spinal adjustment"},
        "weak": {"back pain", "neck pain", "alignment"},
    },
    "medical": {
        "strong": {"medical", "clinic", "physician", "patient care"},
        "weak": {"appointment", "treatment", "healthcare"},
    },
    "medspa": {
        "strong": {"med spa", "medspa", "botox", "filler", "laser treatment"},
        "weak": {"aesthetic", "skin", "injectables"},
    },
    "vet": {
        "strong": {"veterinary", "veterinarian", "animal hospital", "pet care"},
        "weak": {"pets", "vaccination", "wellness exam"},
    },
    "legal": {
        "strong": {"law firm", "attorney", "lawyer", "legal services"},
        "weak": {"case", "litigation", "consultation"},
    },
    "accounting": {
        "strong": {"accounting", "cpa", "tax preparation", "bookkeeping"},
        "weak": {"payroll", "financial", "returns"},
    },
    "consulting": {
        "strong": {"consulting", "advisor", "strategy", "business consulting"},
        "weak": {"insights", "growth", "solutions"},
    },
    "salon": {
        "strong": {"salon", "hair salon", "stylist", "hair color"},
        "weak": {"cut", "blowout", "beauty"},
    },
    "spa": {
        "strong": {"spa", "massage", "facial", "wellness spa"},
        "weak": {"relax", "treatment", "bodywork"},
    },
    "fitness": {
        "strong": {"fitness", "gym", "personal training", "workout"},
        "weak": {"classes", "strength", "membership"},
    },
    "retail": {
        "strong": {"shop", "store", "boutique", "collection"},
        "weak": {"products", "new arrivals", "gift card"},
    },
    "florist": {
        "strong": {"florist", "flowers", "bouquet", "floral"},
        "weak": {"arrangements", "wedding flowers", "same day delivery"},
    },
    "jewelry": {
        "strong": {"jewelry", "jewellery", "engagement ring", "necklace"},
        "weak": {"bracelet", "earrings", "fine jewelry"},
    },
    "furniture": {
        "strong": {"furniture", "sofa", "dining table", "home furnishings"},
        "weak": {"living room", "bedroom", "chairs"},
    },
}


def detect_industry_from_source(
    request: dict,
    source_summary: dict,
    business_profile: dict,
    enrichment: dict,
) -> dict:
    explicit_industry = request.get("industry", DEFAULT_INDUSTRY)
    should_override = explicit_industry in {"", DEFAULT_INDUSTRY, "general"}
    if not should_override:
        return {
            "industry": explicit_industry,
            "source": "operator",
            "confidence": 1.0,
            "signals": [f"operator supplied industry={explicit_industry}"],
            "scores": {explicit_industry: 1.0},
        }

    text_parts = [
        request.get("website_url", ""),
        request.get("hostname", ""),
        source_summary.get("title", ""),
        source_summary.get("description", ""),
        source_summary.get("markdown_excerpt", ""),
        business_profile.get("business_name", ""),
        business_profile.get("address", ""),
        business_profile.get("menu_url", ""),
        " ".join(source_summary.get("top_links", [])[:8]),
        " ".join(business_profile.get("core_highlights", [])[:8]),
        " ".join(business_profile.get("external_enrichment_notes", [])[:4]),
    ]
    text = " ".join(part for part in text_parts if part).lower()
    scores: dict[str, float] = {}
    signals_by_industry: dict[str, list[str]] = {}

    for industry, rule in INDUSTRY_DETECTION_RULES.items():
        score = 0.0
        signals: list[str] = []
        for term in rule.get("strong", set()):
            if term in text:
                score += 2.0
                signals.append(term)
        for term in rule.get("weak", set()):
            if term in text:
                score += 0.75
                signals.append(term)
        if score > 0:
            scores[industry] = round(score, 2)
            signals_by_industry[industry] = signals[:8]

    if business_profile.get("menu_url"):
        scores["restaurant"] = round(scores.get("restaurant", 0.0) + 3.0, 2)
        signals_by_industry.setdefault("restaurant", []).append("menu url")
    if business_profile.get("hours"):
        for hospitality in ("restaurant", "cafe", "bakery", "bar"):
            if hospitality in scores:
                scores[hospitality] = round(scores[hospitality] + 0.25, 2)

    if not scores:
        return {
            "industry": "general",
            "source": "inferred",
            "confidence": 0.0,
            "signals": [],
            "scores": {},
        }

    best = max(scores, key=scores.get)
    ordered_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_score = ordered_scores[0][1]
    runner_up = ordered_scores[1][1] if len(ordered_scores) > 1 else 0.0
    confidence = min(1.0, 0.45 + ((top_score - runner_up) * 0.08) + min(top_score * 0.04, 0.35))

    return {
        "industry": best,
        "source": "inferred",
        "confidence": round(confidence, 2),
        "signals": signals_by_industry.get(best, [])[:8],
        "scores": {key: value for key, value in ordered_scores[:6]},
    }


def infer_business_subtype(request: dict, business_profile: dict, source_summary: dict) -> str:
    industry = request["industry"]
    text = " ".join(
        [
            source_summary.get("title", ""),
            source_summary.get("description", ""),
            business_profile.get("business_name", ""),
            " ".join(business_profile.get("core_highlights", [])),
        ]
    ).lower()
    for subtype, config in NICHE_SUBTYPE_LIBRARY.items():
        if industry not in config.get("industries", set()):
            continue
        if any(term in text for term in config.get("signal_terms", set())):
            return subtype
    for subtype, config in NICHE_SUBTYPE_LIBRARY.items():
        if industry in config.get("industries", set()):
            return subtype
    if industry == "restaurant":
        return "restaurant-general"
    if industry in {"plumber", "electrician", "hvac", "contractor", "roofer", "landscaper", "pest-control"}:
        return "local-trades"
    if industry in {"dentist", "medical", "legal", "consulting", "accounting", "orthodontist", "chiropractor"}:
        return "trust-service"
    return industry or "general"


def build_component_blueprint(request: dict, design_engine: dict, business_profile: dict, source_summary: dict) -> dict:
    family_key = design_engine.get("family", "modern-approachable")
    library = MAGICUI_COMPONENT_LIBRARY.get(family_key, MAGICUI_COMPONENT_LIBRARY["modern-approachable"])
    subtype = infer_business_subtype(request, business_profile, source_summary)
    niche = NICHE_SUBTYPE_LIBRARY.get(subtype, {})
    adaptations = list(niche.get("component_adaptations", []))

    return {
        "family": family_key,
        "business_subtype": subtype,
        "source": "magicui-inspired internal component vocabulary",
        "hero_pattern": library["hero_pattern"],
        "nav_pattern": library["nav_pattern"],
        "cta_pattern": library["cta_pattern"],
        "surface_pattern": library["surface_pattern"],
        "gallery_pattern": library["gallery_pattern"],
        "proof_pattern": library["proof_pattern"],
        "menu_pattern": library["menu_pattern"],
        "footer_pattern": library["footer_pattern"],
        "motion_pattern": library["motion_pattern"],
        "decor_pattern": library["decor_pattern"],
        "adaptations": adaptations,
    }


def select_design_family(request: dict, business_profile: dict, source_summary: dict) -> dict:
    explicit = request.get("design_family")
    if explicit:
        profile = DESIGN_FAMILY_LIBRARY[explicit]
        return {
            "family": explicit,
            "source": "operator",
            "rationale": f"Operator explicitly selected {explicit}.",
            "profile": profile,
        }

    text = " ".join(
        [
            request.get("design_goal", ""),
            request.get("brand_notes", ""),
            source_summary.get("title", ""),
            source_summary.get("description", ""),
            business_profile.get("business_name", ""),
            " ".join(business_profile.get("core_highlights", [])),
        ]
    ).lower()

    subtype = infer_business_subtype(request, business_profile, source_summary)
    niche = NICHE_SUBTYPE_LIBRARY.get(subtype, {})
    family = niche.get("family") or INDUSTRY_DEFAULT_FAMILIES.get(request["industry"], "modern-approachable")
    rationale = [f"default for industry={request['industry']}"]
    diner_signals = (
        "diner",
        "family-owned",
        "breakfast",
        "all day breakfast",
        "pancakes",
        "omelette",
        "omelet",
        "neighborhood",
        "comfort food",
    )

    if niche.get("family"):
        rationale.append(f"niche subtype {subtype} maps best to {family}")
    elif request["industry"] == "restaurant" and any(term in text for term in diner_signals):
        family = "warm-hospitality"
        rationale.append("diner-style restaurant benefits more from warm neighborhood hospitality than luxury editorial cues")
    elif any(term in text for term in ("luxury", "premium", "editorial", "fine dining", "steak", "cocktail", "hotel")):
        family = "editorial-luxury"
        rationale.append("language suggests premium/editorial positioning")
    elif any(term in text for term in ("warm", "cozy", "family", "neighborhood", "cafe", "bakery", "welcoming")):
        family = "warm-hospitality"
        rationale.append("language suggests warm hospitality positioning")
    elif any(term in text for term in ("bold", "cinematic", "dramatic", "immersive", "nightlife")):
        family = "cinematic-bold"
        rationale.append("language suggests dramatic visual direction")
    elif request["industry"] in {"plumber", "electrician", "hvac", "contractor"}:
        family = "craftsman-premium"
        rationale.append("local trade service prioritizes practical premium trust")
    elif request["industry"] in {"dentist", "medical", "legal", "consulting"}:
        family = "crisp-trust"
        rationale.append("professional service benefits from clean trust-first direction")

    return {
        "family": family,
        "source": "inferred",
        "rationale": "; ".join(rationale),
        "profile": DESIGN_FAMILY_LIBRARY[family],
    }


def build_concept_blueprint(request: dict, business_profile: dict, source_summary: dict, design_engine: dict, source_assets: list[dict]) -> dict:
    family_key = design_engine["family"]
    profile = design_engine["profile"]
    subtype = infer_business_subtype(request, business_profile, source_summary)
    section_flow = default_section_flow(request["industry"], family_key, subtype)
    conversion_priority = infer_conversion_priority_for_subtype(request["industry"], subtype)
    source_title = source_summary.get("title", "").split("-")[0].strip()
    business_name = business_profile.get("business_name") or source_title or request["hostname"]
    image_policy = (
        "Preserve and elevate source imagery where credible, then supplement with premium editorial imagery only if needed."
        if request["allow_external_images"]
        else "Work entirely from source assets, typography, color, and layout rather than adding external imagery."
    )
    if request["image_strategy"] == "source-only":
        image_policy = "Use only source imagery and logo assets; the design must win through composition and typography."
    elif request["image_strategy"] == "stock-first":
        image_policy = "Use polished editorial imagery as the dominant visual layer while preserving any usable brand marks."

    return {
        "business_name": business_name,
        "family": family_key,
        "creative_thesis": request.get("design_goal") or profile["summary"],
        "family_summary": profile["summary"],
        "typography_system": profile["typography"],
        "color_logic": profile["palette"],
        "layout_system": profile["layout"],
        "component_language": profile["components"],
        "motion_policy": profile["motion"],
        "anti_patterns": profile["anti_patterns"],
        "section_flow": section_flow,
        "conversion_priority": conversion_priority,
        "image_policy": image_policy,
        "asset_strength": "strong" if len(source_assets) >= 6 else ("moderate" if len(source_assets) >= 3 else "weak"),
        "content_focus": business_profile.get("core_highlights", [])[:5],
        "footer_requirements": "Include a dedicated footer/location module with address, hours, phone, and a real Google Map embed whenever practical. At minimum, include a real directions link tied to the actual business location.",
    }


def infer_schema_type(industry: str) -> str:
    mapping = {
        "restaurant": "Restaurant",
        "cafe": "CafeOrCoffeeShop",
        "bakery": "Bakery",
        "bar": "BarOrPub",
        "hotel": "Hotel",
        "spa": "DaySpa",
        "salon": "BeautySalon",
        "plumber": "Plumber",
        "electrician": "Electrician",
        "hvac": "HomeAndConstructionBusiness",
        "contractor": "HomeAndConstructionBusiness",
        "dentist": "Dentist",
        "medical": "MedicalBusiness",
        "legal": "LegalService",
        "consulting": "ProfessionalService",
        "retail": "Store",
        "wellness": "HealthAndBeautyBusiness",
        "general": "LocalBusiness",
    }
    return mapping.get(industry, "LocalBusiness")


def infer_schema_type_for_subtype(industry: str, subtype: str) -> str:
    niche = NICHE_SUBTYPE_LIBRARY.get(subtype)
    if niche and niche.get("schema_type"):
        return niche["schema_type"]
    return infer_schema_type(industry)


def build_seo_blueprint(request: dict, business_profile: dict, source_summary: dict, concept_blueprint: dict) -> dict:
    business_name = business_profile.get("business_name") or source_summary.get("title", "").split("-")[0].strip() or request["hostname"]
    subtype = infer_business_subtype(request, business_profile, source_summary)
    location_hint = ""
    address = business_profile.get("address", "")
    if address:
        location_hint = address.split(",")[-1].strip() if "," in address else address
    headline_keywords = business_profile.get("core_highlights", [])[:4]
    return {
        "schema_type": infer_schema_type_for_subtype(request["industry"], subtype),
        "canonical_url": request["website_url"],
        "title_formula": f"{business_name} | {request['industry'].replace('-', ' ').title()} in {location_hint or 'your area'}",
        "meta_description_focus": "Lead with the offer, atmosphere or trust angle, then reinforce location and a primary CTA in 120-160 characters.",
        "content_keywords": headline_keywords,
        "local_signals": {
            "business_name": business_name,
            "address": business_profile.get("address", ""),
            "phone": business_profile.get("phone", ""),
            "hours": business_profile.get("hours", ""),
            "maps_query_url": business_profile.get("maps_query_url", ""),
        },
        "og_image_strategy": "Use the strongest hero or branded source image as the social preview image and ensure the meta tags point to it.",
        "heading_rule": "Use exactly one descriptive H1 and a logical H2/H3 hierarchy for major sections.",
        "alt_text_rule": "Every non-decorative image should have descriptive alt text tied to the business, menu, service, or atmosphere.",
        "footer_rule": concept_blueprint.get("footer_requirements", ""),
    }


def build_content_blueprint(request: dict, business_profile: dict, source_summary: dict, component_blueprint: dict) -> dict:
    menu_rule = ""
    if request["industry"] == "restaurant":
        menu_rule = (
            "Do not link out to the legacy menu page. Rebuild menu highlights, featured dishes, pricing cues, and dayparts as part of the redesigned experience."
        )
    trust_signals = [item for item in business_profile.get("core_highlights", []) if item]
    if business_profile.get("address"):
        trust_signals.append("real address present")
    if business_profile.get("phone"):
        trust_signals.append("direct phone present")
    if business_profile.get("hours"):
        trust_signals.append("hours present")
    subtype = component_blueprint.get("business_subtype", "general")
    niche = NICHE_SUBTYPE_LIBRARY.get(subtype, {})
    required_sections = ["hero", "proof", "contact-footer"]
    rewrite_targets = ["hero copy", "value proposition", "CTA copy"]
    section_notes = list(niche.get("section_notes", []))
    if niche.get("required_sections"):
        required_sections = list(niche["required_sections"])
    if niche.get("rewrite_targets"):
        rewrite_targets.extend(niche["rewrite_targets"])
    return {
        "business_subtype": subtype,
        "rewrite_rule": "Rewrite and improve source copy into sharper, clearer, more persuasive language. Preserve facts, but do not reuse long sentences verbatim.",
        "proof_rule": "Use only verifiable proof from source facts or extracted enrichment. If specific reviews, awards, or ratings are not present, do not invent them.",
        "link_rule": "Do not use legacy source-site navigation or CTA links in the redesigned preview. Keep navigation internal to the preview and rebuild important content as sections.",
        "menu_rule": menu_rule,
        "trust_signals": trust_signals[:6],
        "review_evidence_present": bool(business_profile.get("review_snippets")),
        "forbidden_urls": [url for url in [business_profile.get("menu_url"), request["website_url"]] if url],
        "required_sections": required_sections,
        "rewrite_targets": list(dict.fromkeys(rewrite_targets)),
        "section_notes": section_notes,
    }


def normalize_request(payload: dict) -> dict:
    website_url = str(payload.get("website_url", "")).strip()
    if not website_url:
        raise ValueError("website_url is required")

    parsed = urlparse(website_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("website_url must be a valid http/https URL")

    enabled_skills = payload.get("enabled_skills")
    if enabled_skills is None:
        normalized_skills = list(DEFAULT_SKILLS)
    elif isinstance(enabled_skills, str):
        normalized_skills = [item.strip() for item in enabled_skills.split(",") if item.strip()]
    elif isinstance(enabled_skills, list):
        normalized_skills = [str(item).strip() for item in enabled_skills if str(item).strip()]
    else:
        raise ValueError("enabled_skills must be an array or comma-delimited string")

    client_slug = payload.get("client_slug") or parsed.netloc
    industry = canonicalize_industry(str(payload.get("industry") or DEFAULT_INDUSTRY))
    design_family_input = str(payload.get("design_family") or payload.get("template_family") or "").strip()
    run_mode = str(payload.get("run_mode") or payload.get("delivery_mode") or "prospect").strip().lower()
    if run_mode not in ALLOWED_RUN_MODES:
        raise ValueError(f"run_mode must be one of: {', '.join(sorted(ALLOWED_RUN_MODES))}")
    mode_defaults = RUN_MODE_DEFAULTS[run_mode]

    generator_profile = str(payload.get("generator_profile") or mode_defaults["generator_profile"]).strip().lower()
    if generator_profile not in ALLOWED_GENERATOR_PROFILES:
        raise ValueError(f"generator_profile must be one of: {', '.join(sorted(ALLOWED_GENERATOR_PROFILES))}")
    image_strategy = str(payload.get("image_strategy") or "hybrid").strip().lower()
    if image_strategy not in ALLOWED_IMAGE_STRATEGIES:
        raise ValueError(f"image_strategy must be one of: {', '.join(sorted(ALLOWED_IMAGE_STRATEGIES))}")
    source_expansion_mode = str(payload.get("source_expansion_mode") or mode_defaults["source_expansion_mode"]).strip().lower()
    if source_expansion_mode not in ALLOWED_SOURCE_EXPANSION_MODES:
        raise ValueError(
            f"source_expansion_mode must be one of: {', '.join(sorted(ALLOWED_SOURCE_EXPANSION_MODES))}"
        )
    search_budget = payload.get("search_budget", mode_defaults["search_budget"])
    try:
        search_budget = max(0, min(int(search_budget), 8))
    except Exception:
        raise ValueError("search_budget must be an integer")

    return {
        "website_url": website_url,
        "client_slug": slugify(str(client_slug)),
        "brand_notes": str(payload.get("brand_notes", "")).strip(),
        "dry_run": bool(payload.get("dry_run", False)),
        "hostname": parsed.netloc,
        "callback_url": str(payload.get("callback_url", "")).strip(),
        "notify_email": str(payload.get("notify_email", "")).strip(),
        "industry": industry,
        "design_family": normalize_design_family(design_family_input) if design_family_input else "",
        "enabled_skills": normalized_skills or list(DEFAULT_SKILLS),
        "extra_instructions": str(payload.get("extra_instructions", "")).strip(),
        "run_mode": run_mode,
        "generator_profile": generator_profile,
        "image_strategy": image_strategy,
        "reuse_source_images": parse_bool(payload.get("reuse_source_images"), True),
        "allow_external_images": parse_bool(payload.get("allow_external_images"), True),
        "design_goal": str(payload.get("design_goal", "")).strip(),
        "prompt_append": str(payload.get("prompt_append", "")).strip(),
        "source_expansion_mode": source_expansion_mode,
        "search_enrichment": parse_bool(payload.get("search_enrichment"), mode_defaults["search_enrichment"]),
        "search_budget": search_budget,
        "content_critique": parse_bool(
            payload.get("content_critique"),
            mode_defaults["content_critique"] and parse_bool(DEFAULT_CONTENT_CRITIQUE, True),
        ),
        "content_autofix": parse_bool(
            payload.get("content_autofix"),
            mode_defaults["content_autofix"] and parse_bool(DEFAULT_CONTENT_AUTOFIX, True),
        ),
        "seo_critique": parse_bool(
            payload.get("seo_critique"),
            mode_defaults["seo_critique"] and parse_bool(DEFAULT_SEO_CRITIQUE, True),
        ),
        "seo_autofix": parse_bool(
            payload.get("seo_autofix"),
            mode_defaults["seo_autofix"] and parse_bool(DEFAULT_SEO_AUTOFIX, True),
        ),
        "impeccable_critique": parse_bool(
            payload.get("impeccable_critique"),
            mode_defaults["impeccable_critique"] and parse_bool(DEFAULT_IMPECCABLE_CRITIQUE, True),
        ),
        "impeccable_autofix": parse_bool(
            payload.get("impeccable_autofix"),
            mode_defaults["impeccable_autofix"] and parse_bool(DEFAULT_IMPECCABLE_AUTOFIX, True),
        ),
        "lighthouse_critique": parse_bool(
            payload.get("lighthouse_critique"),
            mode_defaults["lighthouse_critique"] and parse_bool(DEFAULT_LIGHTHOUSE_CRITIQUE, True),
        ),
        "lighthouse_autofix": parse_bool(
            payload.get("lighthouse_autofix"),
            mode_defaults["lighthouse_autofix"] and parse_bool(DEFAULT_LIGHTHOUSE_AUTOFIX, True),
        ),
        "axe_critique": parse_bool(
            payload.get("axe_critique"),
            mode_defaults["axe_critique"] and parse_bool(DEFAULT_AXE_CRITIQUE, True),
        ),
        "axe_autofix": parse_bool(
            payload.get("axe_autofix"),
            mode_defaults["axe_autofix"] and parse_bool(DEFAULT_AXE_AUTOFIX, True),
        ),
    }


def normalize_qualification_request(payload: dict) -> dict:
    request = normalize_request(payload)
    request["company_name"] = str(payload.get("company_name", "")).strip()
    request["lead_id"] = str(payload.get("lead_id", "")).strip()
    request["source_row_id"] = str(payload.get("source_row_id", "")).strip()
    request["qualification_notes"] = str(payload.get("qualification_notes", "")).strip()
    return request


def list_available_skills() -> dict:
    base_skills = sorted(
        path.stem for path in SKILLS_DIR.glob("*.md") if path.is_file()
    )
    industry_skills = sorted(
        path.stem for path in (SKILLS_DIR / "industry").glob("*.md") if path.is_file()
    )
    return {
        "default_skills": list(DEFAULT_SKILLS),
        "default_industry": DEFAULT_INDUSTRY,
        "skills_dir": str(SKILLS_DIR),
        "base_skills": base_skills,
        "industry_skills": industry_skills,
    }


def resolve_skill_files(request: dict) -> list[Path]:
    skill_files: list[Path] = []
    for skill_name in request["enabled_skills"]:
        candidate = SKILLS_DIR / f"{skill_name}.md"
        if candidate.exists():
            skill_files.append(candidate)
    industry_file = SKILLS_DIR / "industry" / f"{request['industry']}.md"
    if industry_file.exists():
        skill_files.append(industry_file)
    return skill_files


def firecrawl_post(path: str, payload: dict) -> dict:
    request = Request(
        f"{FIRECRAWL_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=FIRECRAWL_SCRAPE_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Firecrawl {path} failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Firecrawl {path} request failed: {exc}") from exc


def firecrawl_search(query: str, limit: int = 5, scrape_markdown: bool = False) -> dict:
    payload: dict = {"query": query, "limit": limit}
    if scrape_markdown:
        payload["scrapeOptions"] = {"formats": ["markdown"]}
    return firecrawl_post("/v1/search", payload)


def summarize_firecrawl_payload(scrape: dict, mapped_links: list[str] | None = None) -> dict:
    data = scrape.get("data", {}) if isinstance(scrape, dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
    markdown = data.get("markdown", "") if isinstance(data, dict) else ""
    html = data.get("html", "") if isinstance(data, dict) else ""
    base_url = metadata.get("url") or metadata.get("sourceURL", "")
    html_links = extract_internal_links(html, base_url)
    merged_links: list[str] = []
    for candidate in list(mapped_links or []) + html_links:
        if candidate and candidate not in merged_links:
            merged_links.append(candidate)
    return {
        "title": metadata.get("title", ""),
        "description": metadata.get("description", ""),
        "language": metadata.get("language", ""),
        "url": base_url,
        "markdown_excerpt": truncate_text(markdown, 2400),
        "html_excerpt": truncate_text(html, 1400),
        "top_links": merged_links[:12],
    }


def summarize_search_item(item: dict) -> dict:
    markdown = item.get("markdown", "") if isinstance(item, dict) else ""
    return {
        "title": item.get("title", ""),
        "description": item.get("description", ""),
        "url": item.get("url", ""),
        "markdown_excerpt": truncate_text(markdown, 900),
    }


SOCIAL_PROFILE_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "tiktok.com",
    "www.tiktok.com",
    "linktr.ee",
    "www.linktr.ee",
}


def strip_html_tags(value: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", " ", value or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\\s+", " ", text).strip()


def parse_json_ld_blocks(html: str) -> list[dict]:
    blocks: list[dict] = []
    if not html:
        return blocks
    for match in re.finditer(
        r"<script[^>]+type=[\"']application/ld\\+json[\"'][^>]*>(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw = (match.group(1) or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(unescape(raw))
        except Exception:
            continue
        if isinstance(payload, list):
            blocks.extend(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            blocks.append(payload)
    return blocks


def flatten_json_ld_items(items: list[dict]) -> list[dict]:
    flattened: list[dict] = []
    queue = list(items)
    while queue:
        item = queue.pop(0)
        if not isinstance(item, dict):
            continue
        flattened.append(item)
        graph = item.get("@graph")
        if isinstance(graph, list):
            queue.extend(node for node in graph if isinstance(node, dict))
    return flattened


def extract_internal_links(html: str, base_url: str, limit: int = 12) -> list[str]:
    if not html or not base_url:
        return []
    parsed_base = urlparse(base_url)
    base_host = parsed_base.netloc.lower()
    links: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"""href=["']([^"'#]+)["']""", html, flags=re.IGNORECASE):
        href = (match.group(1) or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower() != base_host:
            continue
        normalized = parsed._replace(fragment="", query="").geturl().rstrip("/")
        if normalized == base_url.rstrip("/"):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)
        if len(links) >= limit:
            break
    return links


def detect_source_flags(request: dict, source_summary: dict, html: str) -> dict:
    website_url = request.get("website_url", "")
    parsed = urlparse(website_url)
    host = parsed.netloc.lower()
    lowered_html = (html or "").lower()
    title = (source_summary.get("title", "") or "").strip().lower()
    combined_text = " ".join(
        bit for bit in [title, source_summary.get("description", ""), strip_html_tags(html)[:1200]] if bit
    ).lower()
    is_social_profile = host in SOCIAL_PROFILE_HOSTS
    is_bot_challenge = (
        "just a moment" in title
        or "attention required" in title
        or "cloudflare" in lowered_html
        or "cf-chl" in lowered_html
    )
    is_ordering_microsite = any(
        phrase in combined_text
        for phrase in (
            "menu & order online",
            "order online",
            "carryout",
            "delivery",
            "check availability",
            "sign up for deals",
        )
    )
    return {
        "is_social_profile": is_social_profile,
        "is_bot_challenge": is_bot_challenge,
        "is_ordering_microsite": is_ordering_microsite,
    }


def analyze_with_firecrawl(url: str, include_map: bool = False) -> dict:
    scrape = firecrawl_post("/v1/scrape", {"url": url, "formats": ["markdown", "html"]})
    mapped_links: list[str] = []
    if include_map:
        mapping = firecrawl_post("/v1/map", {"url": url, "limit": 8})
        mapped_links = mapping.get("links", [])[:8]
    return {
        "scrape": scrape,
        "summary": summarize_firecrawl_payload(scrape, mapped_links),
    }


def score_source_completeness(source_summary: dict, asset_candidates: list[dict], top_links: list[str]) -> dict:
    markdown = source_summary.get("markdown_excerpt", "") or ""
    description = source_summary.get("description", "") or ""
    score = 0.0
    reasons: list[str] = []

    if len(markdown) >= 500:
        score += 0.28
        reasons.append("source markdown has usable length")
    if description:
        score += 0.1
        reasons.append("metadata description found")
    if any(link for link in top_links if any(key in link.lower() for key in ("menu", "about", "contact", "gallery"))):
        score += 0.22
        reasons.append("important internal links discovered")
    if any(asset.get("role") == "logo" for asset in asset_candidates):
        score += 0.12
        reasons.append("logo-like asset found")
    if len(asset_candidates) >= 4:
        score += 0.18
        reasons.append("multiple visual assets found")
    if re.search(r"\b(call|hours|address|family-owned|menu)\b", markdown, flags=re.IGNORECASE):
        score += 0.1
        reasons.append("business facts present in extracted content")

    return {"score": min(score, 1.0), "reasons": reasons}


def should_enrich_source(request: dict, completeness: dict) -> bool:
    if not request.get("search_enrichment", True):
        return False
    mode = request["source_expansion_mode"]
    if mode == "aggressive":
        return True
    threshold = 0.65 if mode == "balanced" else 0.4
    return completeness.get("score", 0.0) < threshold


def build_search_queries(request: dict, source_summary: dict) -> list[str]:
    title = source_summary.get("title", "") or ""
    description = source_summary.get("description", "") or ""
    base = title.split("-")[0].strip() or request["hostname"]
    queries = [base]
    if description:
        queries.append(f"{base} {description[:80]}")
    queries.append(f"{base} reviews hours menu")
    return queries


def summarize_html_structure(html: str) -> dict:
    if not html:
        return {
            "h1_count": 0,
            "h2_count": 0,
            "section_count": 0,
            "button_count": 0,
            "form_count": 0,
            "nav_link_count": 0,
            "cta_hits": [],
            "trust_hits": [],
        }

    lowercase = html.lower()
    cta_terms = (
        "book",
        "reserve",
        "reservation",
        "call",
        "contact",
        "quote",
        "schedule",
        "visit",
        "order",
        "get started",
        "request",
    )
    trust_terms = (
        "testimonial",
        "testimonials",
        "reviews",
        "review",
        "award",
        "awards",
        "years",
        "family-owned",
        "family owned",
        "trusted",
        "guarantee",
        "certified",
    )

    return {
        "h1_count": len(re.findall(r"<h1\b", html, flags=re.IGNORECASE)),
        "h2_count": len(re.findall(r"<h2\b", html, flags=re.IGNORECASE)),
        "section_count": len(re.findall(r"<section\b", html, flags=re.IGNORECASE)),
        "button_count": len(re.findall(r"<button\b", html, flags=re.IGNORECASE)),
        "form_count": len(re.findall(r"<form\b", html, flags=re.IGNORECASE)),
        "nav_link_count": len(re.findall(r"<nav\b", html, flags=re.IGNORECASE)),
        "cta_hits": [term for term in cta_terms if term in lowercase],
        "trust_hits": [term for term in trust_terms if term in lowercase],
    }


def clamp_score(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def is_restaurant_like_industry(industry: str) -> bool:
    normalized = canonicalize_industry(industry or "")
    return normalized in {"restaurant", "cafe", "bakery", "bar"} or any(
        token in normalized for token in ("restaurant", "cafe", "bakery", "bar", "pizza", "bistro", "diner")
    )


def score_contact_accessibility(business_profile: dict) -> tuple[float, list[str], list[str]]:
    score = 0.0
    strong: list[str] = []
    weak: list[str] = []

    if business_profile.get("phone"):
        score += 5
        strong.append("phone number is visible")
    else:
        weak.append("phone number was not detected")
    if business_profile.get("address"):
        score += 5
        strong.append("address is present")
    else:
        weak.append("address was not detected")
    if business_profile.get("hours"):
        score += 5
        strong.append("hours are visible")
    else:
        weak.append("hours were not detected")
    if business_profile.get("maps_query_url"):
        score += 5
        strong.append("location can be mapped")
    else:
        weak.append("no mappable location was found")
    return score, strong, weak


def score_page_coverage(
    request: dict,
    business_profile: dict,
    top_links: list[str],
) -> tuple[float, dict, list[str], list[str]]:
    link_blob = "\n".join(top_links or []).lower()
    found: dict[str, bool] = {}

    found["contact"] = any(term in link_blob for term in ("contact", "location", "directions", "visit-us"))
    found["about"] = any(term in link_blob for term in ("about", "story", "team", "our-story", "about-us"))
    if request.get("industry") in {"restaurant", "cafe", "bakery", "bar"}:
        found["offer"] = bool(business_profile.get("menu_url")) or any(
            term in link_blob for term in ("menu", "food", "drinks", "order")
        )
    else:
        found["offer"] = any(
            term in link_blob for term in ("service", "services", "pricing", "quote", "solutions", "work")
        )
    found["proof"] = any(
        term in link_blob for term in ("review", "reviews", "testimonial", "testimonials", "gallery", "portfolio", "case-study")
    )

    restaurant_like = is_restaurant_like_industry(request.get("industry", ""))
    if restaurant_like:
        if not found["contact"] and (business_profile.get("phone") or business_profile.get("address") or business_profile.get("hours")):
            found["contact"] = True
        if not found["offer"] and business_profile.get("menu_url"):
            found["offer"] = True
        if not found["proof"] and business_profile.get("review_snippets"):
            found["proof"] = True

    strong: list[str] = []
    weak: list[str] = []
    score = 0.0
    for name, present in found.items():
        if present:
            score += 5

    if found["contact"]:
        strong.append("the site exposes a dedicated contact/location path")
    else:
        weak.append("no obvious contact/location page was discovered")
    if found["about"]:
        strong.append("the site has an about/story page")
    else:
        weak.append("no obvious about/story page was discovered")
    if found["offer"]:
        strong.append("the site has a dedicated offer page (menu/services/pricing)")
    else:
        weak.append("no clear menu/services/pricing page was discovered")
    if found["proof"]:
        strong.append("the site has a proof-oriented page (reviews/gallery/portfolio)")
    else:
        weak.append("no obvious proof page was discovered")

    return min(score, 20), found, strong, weak


def audit_source_visual_design(job_dir: Path, request: dict) -> dict:
    source_root = job_dir / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    analysis_dir = source_root / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    output_path = analysis_dir / "source-visual-audit.json"
    screenshot_path = source_root / "source-homepage.png"
    payload, log = run_node_json_script(
        "run_source_visual_audit.mjs",
        [request["website_url"], str(output_path), str(screenshot_path)],
        cwd=job_dir,
        timeout=VISUAL_AUDIT_TIMEOUT,
    )

    log_path = analysis_dir / "source-visual-audit.log"
    log_path.write_text(
        f"exit_code={log['exit_code']}\n\nSTDOUT:\n{log['stdout']}\n\nSTDERR:\n{log['stderr']}\n",
        encoding="utf-8",
    )

    if not payload:
        payload = {
            "status": "error",
            "visualDesignScore": None,
            "strongSignals": [],
            "weakSignals": [],
            "metrics": {},
            "error": "No source visual audit payload returned.",
        }

    payload["log"] = str(log_path)
    payload["output_file"] = str(output_path)
    payload["screenshot"] = str(screenshot_path) if screenshot_path.exists() else ""
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def audit_source_lighthouse(job_dir: Path, request: dict) -> dict:
    source_root = job_dir / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    analysis_dir = source_root / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    output_path = analysis_dir / "source-lighthouse-audit.json"
    payload, log = run_node_json_script(
        "run_lighthouse_audit.mjs",
        [request["website_url"], str(output_path)],
        cwd=job_dir,
        timeout=LIGHTHOUSE_TIMEOUT,
    )

    log_path = analysis_dir / "source-lighthouse-audit.log"
    log_path.write_text(
        f"exit_code={log['exit_code']}\n\nSTDOUT:\n{log['stdout']}\n\nSTDERR:\n{log['stderr']}\n",
        encoding="utf-8",
    )

    if not payload:
        payload = {
            "status": "error",
            "findingsCount": 0,
            "findings": [],
            "scores": {},
            "error": "No source Lighthouse payload returned.",
        }

    payload["log"] = str(log_path)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def audit_source_axe(job_dir: Path, request: dict) -> dict:
    source_root = job_dir / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    analysis_dir = source_root / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    output_path = analysis_dir / "source-axe-audit.json"
    payload, log = run_node_json_script(
        "run_axe_audit.mjs",
        [request["website_url"], str(output_path)],
        cwd=job_dir,
        timeout=AXE_TIMEOUT,
    )

    log_path = analysis_dir / "source-axe-audit.log"
    log_path.write_text(
        f"exit_code={log['exit_code']}\n\nSTDOUT:\n{log['stdout']}\n\nSTDERR:\n{log['stderr']}\n",
        encoding="utf-8",
    )

    if not payload:
        payload = {
            "status": "error",
            "findingsCount": 0,
            "findings": [],
            "error": "No source axe payload returned.",
        }

    payload["log"] = str(log_path)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def assess_website_quality(request: dict, source_context: dict) -> dict:
    source = source_context.get("source", {}) if isinstance(source_context, dict) else {}
    source_summary = source.get("summary", {}) if isinstance(source, dict) else {}
    source_flags = source.get("flags", {}) if isinstance(source, dict) else {}
    business_profile = source_context.get("business_profile", {}) if isinstance(source_context, dict) else {}
    asset_candidates = source.get("asset_candidates", []) if isinstance(source, dict) else []
    completeness = source.get("completeness", {}) if isinstance(source, dict) else {}
    top_links = source_summary.get("top_links", []) if isinstance(source_summary, dict) else []
    visual_audit = source_context.get("visual_audit", {}) if isinstance(source_context, dict) else {}
    source_lighthouse = source_context.get("source_lighthouse", {}) if isinstance(source_context, dict) else {}
    source_axe = source_context.get("source_axe", {}) if isinstance(source_context, dict) else {}

    html = ""
    index_file = source.get("index_file") if isinstance(source, dict) else ""
    if index_file:
        try:
            html = Path(index_file).read_text(encoding="utf-8")
        except Exception:
            html = ""

    structure = summarize_html_structure(html)
    markdown = source_summary.get("markdown_excerpt", "") or ""

    strong_signals: list[str] = []
    weak_signals: list[str] = []

    content_score = 0.0
    if len(markdown) >= 1800:
        content_score += 20
        strong_signals.append("source content is substantial")
    elif len(markdown) >= 900:
        content_score += 14
        strong_signals.append("source content has moderate depth")
    elif len(markdown) >= 350:
        content_score += 8
    else:
        weak_signals.append("very little crawlable website content was captured")

    if len(top_links) >= 5:
        content_score += 4
        strong_signals.append("multiple meaningful internal links were discovered")
    elif len(top_links) <= 1:
        weak_signals.append("very few internal navigation links were discovered")
    content_score = min(content_score, 20)

    contact_score, contact_strong, contact_weak = score_contact_accessibility(business_profile)
    strong_signals.extend(contact_strong)
    weak_signals.extend(contact_weak)

    page_coverage_score, page_coverage, page_coverage_strong, page_coverage_weak = score_page_coverage(
        request,
        business_profile,
        top_links,
    )
    strong_signals.extend(page_coverage_strong)
    weak_signals.extend(page_coverage_weak)

    conversion_score = 0.0
    cta_hits = structure.get("cta_hits", [])
    if cta_hits:
        conversion_score += min(12, 4 + len(cta_hits) * 2)
        strong_signals.append(f"CTA language is present ({', '.join(cta_hits[:3])})")
    else:
        weak_signals.append("clear CTA language was not detected")
    if structure.get("button_count", 0) >= 2:
        conversion_score += 4
    if structure.get("form_count", 0) >= 1:
        conversion_score += 4
        strong_signals.append("an on-page form is present")
    conversion_score = min(conversion_score, 20)

    trust_score = 0.0
    trust_hits = structure.get("trust_hits", [])
    if trust_hits:
        trust_score += min(12, 4 + len(trust_hits) * 2)
        strong_signals.append(f"trust signals are present ({', '.join(trust_hits[:3])})")
    else:
        weak_signals.append("testimonial/review/credibility signals were not detected")
    if business_profile.get("core_highlights"):
        trust_score += min(8, len(business_profile["core_highlights"]) * 2)
    trust_score = min(trust_score, 20)

    visual_score = 0.0
    logo_assets = [item for item in asset_candidates if item.get("role") == "logo"]
    if logo_assets:
        visual_score += 6
        strong_signals.append("brand/logo assets were detected")
    else:
        weak_signals.append("logo-like assets were not detected")
    if len(asset_candidates) >= 6:
        visual_score += 10
        strong_signals.append("the site has a healthy number of reusable visual assets")
    elif len(asset_candidates) >= 3:
        visual_score += 6
    else:
        weak_signals.append("very few reusable visual assets were found")
    if any(item.get("type") in {"og-image", "social-image"} for item in asset_candidates):
        visual_score += 4
    visual_score = min(visual_score, 20)

    visual_design_score = None
    raw_visual_score = visual_audit.get("visualDesignScore")
    if isinstance(raw_visual_score, (int, float)):
        visual_design_score = clamp_score((float(raw_visual_score) / 100.0) * 20.0, 0.0, 20.0)
        strong_signals.extend(list(visual_audit.get("strongSignals", []))[:4])
        weak_signals.extend(list(visual_audit.get("weakSignals", []))[:4])
    else:
        weak_signals.append("visual design audit was unavailable")

    technical_health_score = None
    lighthouse_scores = source_lighthouse.get("scores", {}) if isinstance(source_lighthouse, dict) else {}
    score_values = [
        float(lighthouse_scores.get("accessibility", 0) or 0),
        float(lighthouse_scores.get("bestPractices", 0) or 0),
        float(lighthouse_scores.get("seo", 0) or 0),
        float(lighthouse_scores.get("performance", 0) or 0),
    ]
    if any(score_values):
        weighted_average = (score_values[0] + score_values[1] + score_values[2] + (score_values[3] * 0.5)) / 3.5
        technical_health_score = clamp_score((weighted_average / 100.0) * 20.0, 0.0, 20.0)
        if weighted_average >= 85:
            strong_signals.append("technical baseline looks healthy")
        else:
            weak_signals.append("technical baseline looks dated or under-optimized")
        if lighthouse_scores.get("seo", 0) and float(lighthouse_scores.get("seo", 0)) < 70:
            weak_signals.append("SEO fundamentals look weak")
        if lighthouse_scores.get("bestPractices", 0) and float(lighthouse_scores.get("bestPractices", 0)) < 70:
            weak_signals.append("browser best-practices score is weak")
        if lighthouse_scores.get("accessibility", 0) and float(lighthouse_scores.get("accessibility", 0)) >= 88:
            strong_signals.append("accessibility baseline looks solid")
    else:
        weak_signals.append("technical audit was unavailable")

    accessibility_score = None
    axe_findings = list(source_axe.get("findings", [])) if isinstance(source_axe, dict) else []
    if source_axe.get("status") == "clean":
        accessibility_score = 20.0
        strong_signals.append("no major accessibility violations were detected")
    elif axe_findings:
        high_findings = sum(1 for item in axe_findings if item.get("severity") in {"critical", "serious", "high"})
        total_findings = len(axe_findings)
        accessibility_score = clamp_score(20 - (high_findings * 4) - ((total_findings - high_findings) * 1.5), 0.0, 20.0)
        weak_signals.append("accessibility violations are visible on the live site")
    else:
        weak_signals.append("accessibility audit was unavailable")

    structure_score = 0.0
    if structure.get("h1_count", 0) >= 1:
        structure_score += 4
    else:
        weak_signals.append("no H1 heading was detected")
    if structure.get("h2_count", 0) >= 3:
        structure_score += 6
    elif structure.get("h2_count", 0) == 0:
        weak_signals.append("section hierarchy looks thin")
    if structure.get("section_count", 0) >= 4:
        structure_score += 6
    elif structure.get("section_count", 0) <= 1:
        weak_signals.append("page structure appears shallow")
    if structure.get("nav_link_count", 0) >= 1:
        structure_score += 4
    structure_score = min(structure_score, 20)

    component_scores = {
        "content_depth": round(content_score, 1),
        "contact_accessibility": round(contact_score, 1),
        "page_coverage": round(page_coverage_score, 1),
        "conversion_clarity": round(conversion_score, 1),
        "trust_signals": round(trust_score, 1),
        "visual_assets": round(visual_score, 1),
        "visual_design": round(visual_design_score, 1) if isinstance(visual_design_score, (int, float)) else None,
        "technical_health": round(technical_health_score, 1) if isinstance(technical_health_score, (int, float)) else None,
        "accessibility_baseline": round(accessibility_score, 1) if isinstance(accessibility_score, (int, float)) else None,
        "site_structure": round(structure_score, 1),
    }
    available_component_scores = [value for value in component_scores.values() if isinstance(value, (int, float))]
    component_total = sum(available_component_scores)
    component_max = 20.0 * len(available_component_scores)
    website_quality_score = clamp_score((component_total / component_max) * 100.0 if component_max else 0.0)
    redesign_opportunity_score = clamp_score(100 - website_quality_score)
    completeness_score = float(completeness.get("score", 0.0) or 0.0)
    confidence = round(
        clamp_score((completeness_score * 70) + (min(len(strong_signals) + len(weak_signals), 10) * 3), 0, 100),
        1,
    )

    if website_quality_score >= 70:
        qualification_status = "skip"
        summary = "The site already shows enough structure, trust, and conversion signals that it is a weaker redesign outreach target."
    elif website_quality_score >= 45:
        qualification_status = "review"
        summary = "The site has mixed quality signals. It may still be worth outreach, but it is not an obvious weak-site target."
    else:
        qualification_status = "target"
        summary = "The site looks weak enough to justify redesign outreach."

    restaurant_like = is_restaurant_like_industry(request.get("industry", ""))
    if source_flags.get("is_social_profile"):
        qualification_status = "review"
        summary = "The lead points to a social profile rather than a standalone website, so it should be handled in a separate outreach bucket."
        weak_signals.insert(0, "the provided URL is a social profile, not a standalone website")
    elif source_flags.get("fetch_failed"):
        qualification_status = "review"
        summary = "The site could not be reliably fetched during automated evaluation, so it should be reviewed manually before outreach."
        weak_signals.insert(0, "the site could not be fetched reliably during evaluation")
    elif source_flags.get("is_bot_challenge"):
        qualification_status = "review"
        summary = "The site blocked automated evaluation with a bot challenge, so it should be reviewed manually before outreach."
        weak_signals.insert(0, "the site returned a bot-protection or challenge page during evaluation")
    elif restaurant_like and qualification_status == "target":
        has_good_restaurant_baseline = (
            (content_score >= 16 and conversion_score >= 10 and (page_coverage_score >= 10 or contact_score >= 10 or trust_score >= 8))
            or (page_coverage_score >= 10 and conversion_score >= 8 and (content_score >= 10 or contact_score >= 5))
        )
        if has_good_restaurant_baseline or source_flags.get("is_ordering_microsite"):
            qualification_status = "review"
            summary = "The site is operationally decent but still worth a manual review before redesign outreach."

    quality_tier = "strong" if website_quality_score >= 70 else ("mid" if website_quality_score >= 45 else "weak")

    return {
        "website_quality_score": round(website_quality_score, 1),
        "redesign_opportunity_score": round(redesign_opportunity_score, 1),
        "qualification_status": qualification_status,
        "is_candidate": qualification_status == "target",
        "quality_tier": quality_tier,
        "confidence": confidence,
        "summary": summary,
        "strong_signals": strong_signals[:8],
        "weak_signals": weak_signals[:8],
        "component_scores": component_scores,
        "structure_summary": structure,
        "page_coverage": page_coverage,
        "completeness": completeness,
        "source_flags": source_flags,
        "visual_audit_summary": {
            "visual_design_score": raw_visual_score,
            "strong_signals": list(visual_audit.get("strongSignals", []))[:6],
            "weak_signals": list(visual_audit.get("weakSignals", []))[:6],
            "metrics": visual_audit.get("metrics", {}),
        },
        "source_lighthouse_summary": {
            "status": source_lighthouse.get("status"),
            "scores": lighthouse_scores,
            "findings_count": source_lighthouse.get("findingsCount", 0),
            "top_findings": list(source_lighthouse.get("findings", []))[:5],
        },
        "source_axe_summary": {
            "status": source_axe.get("status"),
            "findings_count": len(axe_findings),
            "top_findings": axe_findings[:5],
        },
    }


def enrich_source_context(request: dict, source_summary: dict) -> dict:
    budget = request["search_budget"]
    queries = build_search_queries(request, source_summary)
    seen: set[str] = set()
    results: list[dict] = []
    for query in queries:
        if len(results) >= budget:
            break
        response = firecrawl_search(query, limit=budget, scrape_markdown=True)
        for item in response.get("data", []):
            url = item.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(summarize_search_item(item))
            if len(results) >= budget:
                break
    return {
        "queries": queries,
        "results": results,
    }


def extract_business_profile(
    request: dict,
    source_summary: dict,
    enrichment: dict,
    source_assets: list[dict],
    source_html: str = "",
) -> dict:
    markdown = source_summary.get("markdown_excerpt", "") or ""
    combined_text = "\n".join(bit for bit in [markdown, strip_html_tags(source_html)] if bit)
    json_ld_items = flatten_json_ld_items(parse_json_ld_blocks(source_html))

    def match(pattern: str) -> str:
        found = re.search(pattern, combined_text, flags=re.IGNORECASE)
        return found.group(1).strip() if found else ""

    def extract_phone() -> str:
        tel_match = re.search(r"tel:([+0-9().\\-\\s]{7,})", source_html, flags=re.IGNORECASE)
        if tel_match:
            return tel_match.group(1).strip()
        return match(r"(\\+?\\d[\\d().\\-\\s]{7,}\\d)")

    def extract_address() -> str:
        for item in json_ld_items:
            address = item.get("address")
            if isinstance(address, dict):
                parts = [
                    str(address.get("streetAddress", "")).strip(),
                    str(address.get("addressLocality", "")).strip(),
                    str(address.get("addressRegion", "")).strip(),
                    str(address.get("postalCode", "")).strip(),
                ]
                cleaned = ", ".join(part for part in parts if part)
                if cleaned:
                    return cleaned
        street_pattern = (
            r"(\\d{1,6}\\s+[A-Za-z0-9 .'-]+(?:street|st|road|rd|avenue|ave|boulevard|blvd|lane|ln|drive|dr|highway|hwy|place|pl|court|ct)\\b(?:,\\s*[^\\n,]+){0,3})"
        )
        return match(street_pattern) or match(r"(\\d{1,6}\\s+[^\\n,]+(?:,\\s*[^\\n,]+){1,3})")

    def extract_hours() -> str:
        for item in json_ld_items:
            opening_hours = item.get("openingHours")
            if isinstance(opening_hours, list):
                joined = "; ".join(str(bit).strip() for bit in opening_hours if str(bit).strip())
                if joined:
                    return joined
            if isinstance(opening_hours, str) and opening_hours.strip():
                return opening_hours.strip()
            specs = item.get("openingHoursSpecification")
            if isinstance(specs, list) and specs:
                rendered: list[str] = []
                for spec in specs[:7]:
                    if not isinstance(spec, dict):
                        continue
                    day = spec.get("dayOfWeek")
                    opens = spec.get("opens")
                    closes = spec.get("closes")
                    if day and opens and closes:
                        rendered.append(f"{day}: {opens}-{closes}")
                if rendered:
                    return "; ".join(rendered)
        return match(r"(?:Opening Hours|Hours)\\s*:?\\s*([^\\n]{6,120})")

    def extract_menu_url() -> str:
        for match in re.finditer(r"\[([^\]]+)\]\((https?://[^\)]+)\)", combined_text, flags=re.IGNORECASE):
            label = (match.group(1) or "").lower()
            href = (match.group(2) or "").strip()
            if "menu" in label and href:
                return urljoin(request["website_url"], href)
        for match in re.finditer(r"""href=["']([^"']+)["']""", source_html, flags=re.IGNORECASE):
            href = (match.group(1) or "").strip()
            if any(token in href.lower() for token in ("menu", "order", "reservation", "book")):
                return urljoin(request["website_url"], href)
        return ""

    phone = extract_phone()
    hours = extract_hours()
    address = extract_address()
    business_name = source_summary.get("title", "").split("-")[0].strip() or request["hostname"]
    maps_query_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(address)}" if address else ""
    menu_url = extract_menu_url()

    highlights = []
    for phrase in (
        "family-owned",
        "over 30 years",
        "breakfast",
        "lunch",
        "dinner",
        "fresh ingredients",
        "exceptional service",
    ):
        if phrase.lower() in markdown.lower():
            highlights.append(phrase)

    enrichment_notes = []
    for item in enrichment.get("results", [])[: request["search_budget"]]:
        bit = item.get("description") or item.get("markdown_excerpt") or ""
        if bit:
            enrichment_notes.append(truncate_text(bit, 220))

    review_snippets = []
    for item in enrichment.get("results", [])[: request["search_budget"]]:
        bit = item.get("description") or item.get("markdown_excerpt") or ""
        if re.search(r"\b(review|rated|stars?)\b", bit, flags=re.IGNORECASE):
            review_snippets.append(truncate_text(bit, 180))

    return {
        "business_name": business_name,
        "category": request["industry"],
        "website_url": request["website_url"],
        "address": address,
        "phone": phone,
        "hours": hours,
        "maps_query_url": maps_query_url,
        "menu_url": menu_url,
        "core_highlights": highlights[:6],
        "source_description": source_summary.get("description", ""),
        "source_title": source_summary.get("title", ""),
        "asset_count": len(source_assets),
        "external_enrichment_notes": enrichment_notes[:4],
        "review_snippets": review_snippets[:3],
        "sources": [source_summary.get("url", "")] + [item.get("url", "") for item in enrichment.get("results", [])[:4]],
    }


def render_skill_bundle(skill_files: list[Path]) -> str:
    if not skill_files:
        return "No additional skill files loaded."

    sections = []
    for path in skill_files:
        body = path.read_text(encoding="utf-8").strip()
        sections.append(f"## {path.stem}\n{body}")
    return "\n\n".join(sections)


def extract_asset_candidates(html: str, base_url: str) -> list[dict]:
    if not html:
        return []

    candidates: list[dict] = []
    seen: set[str] = set()
    patterns = [
        (r"<img[^>]+src=[\"']([^\"']+)[\"'][^>]*?(?:alt=[\"']([^\"']*)[\"'])?[^>]*>", "image"),
        (r"<meta[^>]+property=[\"']og:image[\"'][^>]+content=[\"']([^\"']+)[\"'][^>]*>", "og-image"),
        (r"<meta[^>]+name=[\"']twitter:image[\"'][^>]+content=[\"']([^\"']+)[\"'][^>]*>", "social-image"),
        (r"<link[^>]+rel=[\"'][^\"']*icon[^\"']*[\"'][^>]+href=[\"']([^\"']+)[\"'][^>]*>", "icon"),
    ]
    for pattern, asset_type in patterns:
        for match in re.finditer(pattern, html, flags=re.IGNORECASE):
            src = match.group(1).strip() if match.group(1) else ""
            if not src:
                continue
            full_url = urljoin(base_url, src)
            if full_url in seen:
                continue
            seen.add(full_url)
            alt = ""
            if match.lastindex and match.lastindex > 1 and match.group(2):
                alt = match.group(2).strip()
            lower = full_url.lower()
            role = "general"
            if "logo" in lower or "brand" in lower or asset_type == "icon":
                role = "logo"
            candidates.append(
                {
                    "type": asset_type,
                    "url": full_url,
                    "alt": alt,
                    "role": role,
                }
            )
            if len(candidates) >= 12:
                return candidates
    return candidates


def fetch_source_html(job_dir: Path, request: dict) -> dict:
    source_root = job_dir / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    fetch_log = source_root / "fetch.log"
    host_root = source_root / request["hostname"]
    host_root.mkdir(parents=True, exist_ok=True)
    index_file = host_root / "index.html"
    cmd = [
        "curl",
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--user-agent",
        "Mozilla/5.0 (compatible; WebsiteRedesignBot/1.0)",
        "--max-time",
        "60",
        "--output",
        str(index_file),
        request["website_url"],
    ]
    result = run_command(cmd, timeout=120)
    fetch_log.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    if result.returncode != 0 or not index_file.exists() or index_file.stat().st_size == 0:
        raise RuntimeError("Failed to fetch source HTML")
    return {
        "exit_code": result.returncode,
        "method": "curl-fallback",
        "log": str(fetch_log),
        "source_root": str(source_root),
        "index_file": str(index_file),
    }


def analyze_site_context(job_dir: Path, request: dict) -> dict:
    source_root = job_dir / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    analysis_dir = source_root / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    html = ""

    result: dict = {
        "source": None,
        "enrichment": {"results": []},
        "classification": {},
        "business_profile": {},
        "design_engine": {},
        "component_blueprint": {},
        "concept_blueprint": {},
        "content_blueprint": {},
        "seo_blueprint": {},
    }

    try:
        source_analysis = analyze_with_firecrawl(request["website_url"], include_map=True)
        (analysis_dir / "source.json").write_text(json.dumps(source_analysis, indent=2), encoding="utf-8")
        html = source_analysis["scrape"].get("data", {}).get("html", "")
        host_root = source_root / request["hostname"]
        host_root.mkdir(parents=True, exist_ok=True)
        (host_root / "index.html").write_text(html, encoding="utf-8")
        asset_candidates = extract_asset_candidates(html, request["website_url"])
        result["source"] = {
            "method": "firecrawl",
            "analysis_file": str(analysis_dir / "source.json"),
            "source_root": str(source_root),
            "index_file": str(host_root / "index.html"),
            "summary": source_analysis["summary"],
            "asset_candidates": asset_candidates,
            "flags": detect_source_flags(request, source_analysis["summary"], html),
        }
    except Exception as exc:
        try:
            fallback = fetch_source_html(job_dir, request)
            fallback["warning"] = f"Firecrawl source analysis unavailable: {exc}"
            try:
                html = Path(fallback["index_file"]).read_text(encoding="utf-8")
                fallback["asset_candidates"] = extract_asset_candidates(html, request["website_url"])
                fallback["summary"] = {
                    "title": match.group(1).strip() if (match := re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)) else "",
                    "description": "",
                    "language": "",
                    "url": request["website_url"],
                    "markdown_excerpt": truncate_text(strip_html_tags(html), 2400),
                    "html_excerpt": truncate_text(html, 1400),
                    "top_links": extract_internal_links(html, request["website_url"]),
                }
                fallback["flags"] = detect_source_flags(request, fallback["summary"], html)
            except Exception:
                fallback["asset_candidates"] = []
                fallback["summary"] = {
                    "title": "",
                    "description": "",
                    "language": "",
                    "url": request["website_url"],
                    "markdown_excerpt": "",
                    "html_excerpt": "",
                    "top_links": [],
                }
                fallback["flags"] = {}
        except Exception as fetch_exc:
            fallback = {
                "method": "unavailable",
                "warning": f"Firecrawl source analysis unavailable: {exc}",
                "error": str(fetch_exc),
                "source_root": str(source_root),
                "index_file": "",
                "asset_candidates": [],
                "summary": {
                    "title": "",
                    "description": "",
                    "language": "",
                    "url": request["website_url"],
                    "markdown_excerpt": "",
                    "html_excerpt": "",
                    "top_links": [],
                },
                "flags": {
                    "is_social_profile": urlparse(request["website_url"]).netloc.lower() in SOCIAL_PROFILE_HOSTS,
                    "is_bot_challenge": False,
                    "is_ordering_microsite": False,
                    "fetch_failed": True,
                },
            }
        result["source"] = fallback

    source_summary = result["source"].get("summary", {}) if isinstance(result["source"], dict) else {}
    source_assets = result["source"].get("asset_candidates", []) if isinstance(result["source"], dict) else []
    top_links = source_summary.get("top_links", []) if isinstance(source_summary, dict) else []
    completeness = score_source_completeness(source_summary, source_assets, top_links)
    result["source"]["completeness"] = completeness

    if should_enrich_source(request, completeness):
        try:
            enrichment = enrich_source_context(request, source_summary)
            (analysis_dir / "search-enrichment.json").write_text(json.dumps(enrichment, indent=2), encoding="utf-8")
            enrichment["analysis_file"] = str(analysis_dir / "search-enrichment.json")
            result["enrichment"] = enrichment
        except Exception as exc:
            result["enrichment"] = {"results": [], "error": str(exc)}

    result["business_profile"] = extract_business_profile(
        request,
        source_summary,
        result["enrichment"],
        source_assets,
        html,
    )
    classification = detect_industry_from_source(
        request,
        source_summary,
        result["business_profile"],
        result["enrichment"],
    )
    result["classification"] = classification
    detected_industry = classification.get("industry") or request["industry"]
    request["industry"] = detected_industry
    result["business_profile"]["category"] = detected_industry
    (analysis_dir / "business-profile.json").write_text(
        json.dumps(result["business_profile"], indent=2),
        encoding="utf-8",
    )
    (analysis_dir / "classification.json").write_text(
        json.dumps(result["classification"], indent=2),
        encoding="utf-8",
    )

    result["design_engine"] = select_design_family(request, result["business_profile"], source_summary)
    result["component_blueprint"] = build_component_blueprint(
        request,
        result["design_engine"],
        result["business_profile"],
        source_summary,
    )
    result["concept_blueprint"] = build_concept_blueprint(
        request,
        result["business_profile"],
        source_summary,
        result["design_engine"],
        source_assets,
    )
    result["seo_blueprint"] = build_seo_blueprint(
        request,
        result["business_profile"],
        source_summary,
        result["concept_blueprint"],
    )
    result["content_blueprint"] = build_content_blueprint(
        request,
        result["business_profile"],
        source_summary,
        result["component_blueprint"],
    )
    (analysis_dir / "design-engine.json").write_text(json.dumps(result["design_engine"], indent=2), encoding="utf-8")
    (analysis_dir / "component-blueprint.json").write_text(
        json.dumps(result["component_blueprint"], indent=2),
        encoding="utf-8",
    )
    (analysis_dir / "concept-blueprint.json").write_text(
        json.dumps(result["concept_blueprint"], indent=2),
        encoding="utf-8",
    )
    (analysis_dir / "content-blueprint.json").write_text(
        json.dumps(result["content_blueprint"], indent=2),
        encoding="utf-8",
    )
    (analysis_dir / "seo-blueprint.json").write_text(
        json.dumps(result["seo_blueprint"], indent=2),
        encoding="utf-8",
    )

    return result


def profile_limits(profile: str) -> dict:
    if profile == "lean":
        return {"source_chars": 260, "links": 3, "assets": 3, "enrichment_chars": 90}
    if profile == "quality":
        return {"source_chars": 420, "links": 5, "assets": 4, "enrichment_chars": 140}
    return {"source_chars": 340, "links": 4, "assets": 4, "enrichment_chars": 110}


def render_compact_skill_directives(skill_names: list[str], industry: str) -> str:
    lines = [
        "- Preserve facts, improve hierarchy, and strengthen conversion paths.",
        "- Pick one clear art direction before building.",
        "- Recompose the page instead of restyling the legacy layout.",
        "- Deliver polished static HTML/CSS/JS in ./dist with strong mobile behavior.",
        "- Fix obvious generic, low-contrast, or weak-hierarchy issues before finishing.",
    ]
    if industry == "restaurant":
        lines.append("- For restaurants, prioritize appetite appeal, atmosphere, reservations, hours, location confidence, and concise menu highlights.")
    if skill_names:
        lines.append(f"- Active skill packs: {', '.join(skill_names)}.")
    return "\n".join(lines)


def render_asset_guidance(request: dict, source_assets: list[dict]) -> str:
    strategy = request["image_strategy"]
    if strategy == "source-only":
        mode = "Use only source-site assets and logos. Do not introduce external imagery."
    elif strategy == "source-first":
        mode = "Prefer source-site assets and logos. Only use external imagery if the source lacks a credible hero image."
    elif strategy == "stock-first":
        mode = "Prefer external editorial/stock imagery while preserving any usable source logo or icon."
    else:
        mode = "Use a hybrid approach: preserve any usable logo or brand mark, reuse good source photos when credible, and supplement weak imagery with high-quality external/editorial imagery."

    external = (
        "External imagery is allowed."
        if request["allow_external_images"]
        else "External imagery is not allowed; work only with source assets and non-photographic treatments."
    )
    reuse = (
        "Reusing source images is encouraged when quality is acceptable."
        if request["reuse_source_images"]
        else "Do not reuse source photography unless absolutely necessary."
    )
    candidates = "\n".join(
        f"- {item['url']} ({item.get('role', 'general')}{', alt=' + item['alt'] if item.get('alt') else ''})"
        for item in source_assets[:4]
    ) or "- None detected"
    return f"""{mode}
{external}
{reuse}

Detected source asset candidates:
{candidates}
"""


def build_prompt_parts(request: dict, job_dir: Path) -> tuple[dict, list[str]]:
    source_context = request.get("source_context") or {}
    source = source_context.get("source", {})
    source_summary = source.get("summary", {})
    enrichment = source_context.get("enrichment", {})
    business_profile = source_context.get("business_profile", {})
    design_engine = source_context.get("design_engine", {})
    component_blueprint = source_context.get("component_blueprint", {})
    concept_blueprint = source_context.get("concept_blueprint", {})
    content_blueprint = source_context.get("content_blueprint", {})
    seo_blueprint = source_context.get("seo_blueprint", {})
    limits = profile_limits(request["generator_profile"])
    source_assets = source.get("asset_candidates", []) or []

    skill_files = resolve_skill_files(request)
    skill_names = [path.stem for path in skill_files]
    compact_skill_directives = render_compact_skill_directives(skill_names, request["industry"])

    stable_prefix = f"""You are redesigning a client's website into a polished static preview.

Core rules:
- Build in ./dist and ensure ./dist/index.html exists.
- Keep all asset paths relative.
- Preserve facts, but improve clarity, conversion, and presentation.
- Keep the result premium, art-directed, and previewable without a build step.
- Write a concise ./dist/redesign-summary.md before finishing.

Working directives:
{compact_skill_directives}
"""

    design_guardrails = """Pre-generation design guardrails:
- Avoid default-font personality, gradient text, and generic SaaS landing-page patterns.
- Maintain strong body/CTA contrast and animate only transform/opacity.
- Use the internal family, component blueprint, and concept blueprint as the primary design system.
- Include a real location module near the footer with address, hours, phone, and a real map/embed or directions link.
- Keep navigation internal to the preview; do not reuse legacy source-site URLs.
- Do not fabricate testimonials, ratings, awards, or statistics.
- Rewrite source marketing copy; do not lift long paragraphs verbatim.
"""

    operator_controls = f"""Operator controls:
- Run mode: {request['run_mode']}
- Industry: {request['industry']}
- Design family: {design_engine.get('family') or request.get('design_family') or 'auto'}
- Generator profile: {request['generator_profile']}
- Source expansion mode: {request['source_expansion_mode']}
- Search enrichment: {request['search_enrichment']} (budget={request['search_budget']})
- Design goal: {request['design_goal'] or 'General premium redesign'}
- Brand notes: {request['brand_notes'] or 'None'}
- Additional instructions: {request['extra_instructions'] or 'None'}
"""

    business_profile_block = f"""Business profile:
- Business name: {business_profile.get('business_name', '')}
- Category: {business_profile.get('category', '')}
- Address: {business_profile.get('address', 'Unknown')}
- Phone: {business_profile.get('phone', 'Unknown')}
- Hours: {business_profile.get('hours', 'Unknown')}
- Maps link: {business_profile.get('maps_query_url', 'Unavailable')}
- Core highlights:
{chr(10).join(f"  - {item}" for item in business_profile.get('core_highlights', [])) or '  - None extracted'}
"""

    seo_requirements_block = f"""SEO requirements:
- Canonical URL: {seo_blueprint.get('canonical_url', request['website_url'])}
- Schema type: {seo_blueprint.get('schema_type', 'LocalBusiness')}
- Title formula: {seo_blueprint.get('title_formula', '')}
- Meta description focus: {seo_blueprint.get('meta_description_focus', '')}
- Keywords to reinforce naturally: {summarize_value_list(seo_blueprint.get('content_keywords', []))}
- OG image strategy: {seo_blueprint.get('og_image_strategy', '')}
- Heading rule: {seo_blueprint.get('heading_rule', '')}
- Alt text rule: {seo_blueprint.get('alt_text_rule', '')}
- Footer/location rule: {seo_blueprint.get('footer_rule', '')}
"""

    content_integrity_block = f"""Content integrity requirements:
- Subtype: {content_blueprint.get('business_subtype', 'general')}
- Rewrite rule: {content_blueprint.get('rewrite_rule', '')}
- Proof rule: {content_blueprint.get('proof_rule', '')}
- Link rule: {content_blueprint.get('link_rule', '')}
- Menu rule: {content_blueprint.get('menu_rule', 'Not applicable')}
- Trust signals that may be emphasized:
{chr(10).join(f"  - {item}" for item in content_blueprint.get('trust_signals', [])) or '  - None extracted'}
- Required sections:
{chr(10).join(f"  - {item}" for item in content_blueprint.get('required_sections', [])) or '  - None defined'}
- Rewrite targets:
{chr(10).join(f"  - {item}" for item in content_blueprint.get('rewrite_targets', [])) or '  - None defined'}
- Section notes:
{chr(10).join(f"  - {item}" for item in content_blueprint.get('section_notes', [])) or '  - None'}
- Forbidden source URLs:
{chr(10).join(f"  - {item}" for item in content_blueprint.get('forbidden_urls', [])) or '  - None'}
"""

    classification = source_context.get("classification", {})
    source_context_block = f"""Source website context:
- URL: {request['website_url']}
- Captured source HTML is available under ./source
- Source title: {source_summary.get('title', '')}
- Detected industry: {classification.get('industry', request['industry'])} (confidence={classification.get('confidence', 0.0):.2f}, source={classification.get('source', 'unknown')})
- Detection signals: {summarize_value_list(classification.get('signals', []))}
- Completeness score: {source.get('completeness', {}).get('score', 0.0):.2f}
- Completeness notes:
{chr(10).join(f"  - {item}" for item in source.get('completeness', {}).get('reasons', [])) or '  - None'}
- Source summary:
{truncate_text(source_summary.get('markdown_excerpt', '') or 'No Firecrawl summary captured.', limits['source_chars'])}
- Important discovered links:
{chr(10).join(f"  - {link}" for link in source_summary.get('top_links', [])[:limits['links']]) or '  - None'}
- Source asset strength: {concept_blueprint.get('asset_strength', 'unknown')}
"""

    design_family_block = f"""Internal design family:
- Family: {design_engine.get('family', 'modern-approachable')}
- Selection source: {design_engine.get('source', 'inferred')}
- Rationale: {design_engine.get('rationale', 'No rationale recorded')}
- Summary: {design_engine.get('profile', {}).get('summary', '')}
- Typography direction: {design_engine.get('profile', {}).get('typography', '')}
- Palette logic: {design_engine.get('profile', {}).get('palette', '')}
- Layout direction: {design_engine.get('profile', {}).get('layout', '')}
- Component language: {design_engine.get('profile', {}).get('components', '')}
- Motion rule: {design_engine.get('profile', {}).get('motion', '')}
- Family anti-patterns: {design_engine.get('profile', {}).get('anti_patterns', '')}
"""

    component_blueprint_block = f"""MagicUI-inspired component blueprint:
- Source: {component_blueprint.get('source', 'internal component vocabulary')}
- Business subtype: {component_blueprint.get('business_subtype', 'general')}
- Hero pattern: {component_blueprint.get('hero_pattern', '')}
- Nav pattern: {component_blueprint.get('nav_pattern', '')}
- CTA pattern: {component_blueprint.get('cta_pattern', '')}
- Surface pattern: {component_blueprint.get('surface_pattern', '')}
- Gallery pattern: {component_blueprint.get('gallery_pattern', '')}
- Proof pattern: {component_blueprint.get('proof_pattern', '')}
- Menu / offering pattern: {component_blueprint.get('menu_pattern', '')}
- Footer pattern: {component_blueprint.get('footer_pattern', '')}
- Motion pattern: {component_blueprint.get('motion_pattern', '')}
- Decorative pattern: {component_blueprint.get('decor_pattern', '')}
- Family-specific adaptations:
{chr(10).join(f"  - {item}" for item in component_blueprint.get('adaptations', [])) or '  - None'}
"""

    concept_blueprint_block = f"""Concept blueprint:
- Creative thesis: {concept_blueprint.get('creative_thesis', '')}
- Typography system: {concept_blueprint.get('typography_system', '')}
- Color logic: {concept_blueprint.get('color_logic', '')}
- Layout system: {concept_blueprint.get('layout_system', '')}
- Component language: {concept_blueprint.get('component_language', '')}
- Conversion priorities: {summarize_value_list(concept_blueprint.get('conversion_priority', []))}
- Content focus: {summarize_value_list(concept_blueprint.get('content_focus', []))}
- Footer requirement: {concept_blueprint.get('footer_requirements', '')}
- Section flow:
{chr(10).join(f"  - {item}" for item in concept_blueprint.get('section_flow', [])) or '  - None defined'}
"""
    enrichment_lines = []
    for item in enrichment.get("results", [])[: request["search_budget"]]:
        enrichment_lines.append(
            "\n".join(
                [
                    f"- {item.get('title', '')}",
                    f"  URL: {item.get('url', '')}",
                    f"  Notes: {truncate_text(item.get('description') or item.get('markdown_excerpt', ''), limits['enrichment_chars'])}",
                ]
            )
        )
    enrichment_block = "External enrichment:\n" + (
        "\n".join(enrichment_lines)
        if enrichment_lines
        else f"- None used ({enrichment.get('error', 'source content considered sufficient')})"
    )
    asset_block = "Image and asset strategy:\n" + render_asset_guidance(request, source_assets)

    implementation_block = """Implementation expectations:
- Build from the internal design family, component blueprint, and concept blueprint.
- Use the source for facts, proof, usable assets, and menu/service details, not for visual direction.
- Rebuild key content inside the redesign instead of linking back to legacy pages.
- Make the first draft prospect-ready: strong hero, clear CTA, persuasive rewritten copy, and real location info.
- Include title, description, canonical, OG/Twitter tags, one clear H1, and valid LocalBusiness-style JSON-LD.
- Use a real map or directions embed/link in the footer/location area; never replace it with decorative imagery.
- If proof is weak, omit it rather than inventing it.
- If imagery is weak, preserve usable brand assets and improve the image treatment without leaving the page visually empty.
"""

    parts = {
        "stable_prefix": stable_prefix,
        "design_guardrails": design_guardrails,
        "operator_controls": operator_controls,
        "business_profile": business_profile_block,
        "seo_requirements": seo_requirements_block,
        "content_integrity": content_integrity_block,
        "source_context": source_context_block,
        "design_family": design_family_block,
        "component_blueprint": component_blueprint_block,
        "concept_blueprint": concept_blueprint_block,
        "external_enrichment": enrichment_block,
        "asset_strategy": asset_block,
        "implementation_expectations": implementation_block,
    }
    return parts, skill_names


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


def write_prompt_diagnostics(job_dir: Path, parts: dict, request: dict) -> dict:
    per_part = {}
    total_chars = 0
    total_tokens = 0
    for name, value in parts.items():
        chars = len(value)
        tokens = estimate_tokens(value)
        per_part[name] = {"chars": chars, "estimated_tokens": tokens}
        total_chars += chars
        total_tokens += tokens

    suggestions: list[str] = []
    if per_part.get("design_family", {}).get("estimated_tokens", 0) > 240 or per_part.get("concept_blueprint", {}).get("estimated_tokens", 0) > 320:
        suggestions.append("Tighten the internal family/blueprint prose so the concept stays structured without bloating the first-pass prompt.")
    if per_part.get("external_enrichment", {}).get("estimated_tokens", 0) > 220:
        suggestions.append("Lower `search_budget` or disable enrichment when source completeness is already high.")
    if per_part.get("source_context", {}).get("estimated_tokens", 0) > 320:
        suggestions.append("Trim source summary further or summarize key facts before prompt assembly.")
    if total_tokens > 1800:
        suggestions.append("Reduce standing prompt prose further; the current prompt is still heavy enough to slow first-pass generation.")
    if request.get("impeccable_autofix", True):
        suggestions.append("Keep the Impeccable refinement prompt short so the second pass stays cheap.")

    report = {
        "total_chars": total_chars,
        "estimated_tokens": total_tokens,
        "parts": per_part,
        "suggestions": suggestions,
    }
    (job_dir / "prompt.metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def build_prompt(request: dict, job_dir: Path) -> tuple[str, list[str]]:
    parts, skill_names = build_prompt_parts(request, job_dir)
    prompt = "\n\n".join(parts.values())
    (job_dir / "prompt.parts.json").write_text(json.dumps(parts, indent=2), encoding="utf-8")
    write_prompt_diagnostics(job_dir, parts, request)
    return prompt, skill_names


def create_dry_run_preview(job_dir: Path, request: dict, applied_skills: list[str]) -> None:
    dist = job_dir / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    source_context = request.get("source_context") or {}
    design_engine = source_context.get("design_engine", {})
    concept_blueprint = source_context.get("concept_blueprint", {})
    seo_blueprint = source_context.get("seo_blueprint", {})
    business_profile = source_context.get("business_profile", {})
    index_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{seo_blueprint.get("title_formula") or f'Preview for {request["client_slug"]}'}</title>
    <meta name="description" content="Dry-run preview for {business_profile.get('business_name') or request['client_slug']}." />
    <link rel="canonical" href="{request['website_url']}" />
    <meta property="og:title" content="{business_profile.get('business_name') or request['client_slug']}" />
    <meta property="og:description" content="Dry-run preview placeholder for the redesigned site." />
    <meta property="og:type" content="website" />
    <meta name="twitter:card" content="summary_large_image" />
    <script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@type": seo_blueprint.get("schema_type", "LocalBusiness"), "name": business_profile.get("business_name") or request["client_slug"], "url": request["website_url"]})}</script>
    <style>
      :root {{
        --bg: #110f12;
        --panel: rgba(255,255,255,0.08);
        --text: #f5f2ea;
        --muted: #cabfb1;
        --accent: #a5242b;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: "Georgia", serif;
        color: var(--text);
        background:
          radial-gradient(circle at top, rgba(165, 36, 43, 0.35), transparent 40%),
          linear-gradient(145deg, #0b0a0c, #19151b 55%, #0f1216);
        min-height: 100vh;
      }}
      main {{
        max-width: 1100px;
        margin: 0 auto;
        padding: 72px 24px;
      }}
      .panel {{
        border: 1px solid rgba(255,255,255,0.08);
        background: var(--panel);
        backdrop-filter: blur(10px);
        border-radius: 32px;
        padding: 40px;
        box-shadow: 0 40px 120px rgba(0,0,0,0.32);
      }}
      .eyebrow {{
        text-transform: uppercase;
        letter-spacing: 0.2em;
        color: var(--muted);
        font-size: 12px;
      }}
      h1 {{
        font-size: clamp(48px, 10vw, 94px);
        line-height: 0.92;
        margin: 12px 0 16px;
        max-width: 8ch;
      }}
      p, li {{
        color: var(--muted);
        font-size: 18px;
        line-height: 1.7;
      }}
      .accent {{
        color: var(--accent);
      }}
    </style>
  </head>
  <body>
    <main>
      <section class="panel">
        <div class="eyebrow">Dry Run Preview</div>
        <h1>{request["client_slug"]} <span class="accent">concept</span></h1>
        <p>This placeholder confirms the workflow, preview publish path, and skill loading for the redesigned runner repo.</p>
        <ul>
          <li>Source URL: {request["website_url"]}</li>
          <li>Industry: {request["industry"]}</li>
          <li>Design family: {design_engine.get("family", request.get("design_family") or "auto")}</li>
          <li>Skills: {", ".join(applied_skills) or "None"}</li>
        </ul>
        <p>Section flow: {", ".join(concept_blueprint.get("section_flow", [])[:3]) or "Not yet generated"}.</p>
      </section>
    </main>
  </body>
</html>
"""
    (dist / "index.html").write_text(index_html, encoding="utf-8")
    (dist / "redesign-summary.md").write_text(
        "Dry run mode generated a placeholder preview without calling OpenCode.\n",
        encoding="utf-8",
    )


def run_opencode_redesign(job_dir: Path, request: dict) -> dict:
    prompt, applied_skills = build_prompt(request, job_dir)
    prompt_file = job_dir / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    local_config_path = build_local_opencode_config(job_dir)
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(local_config_path)
    cmd = [
        "opencode",
        "run",
        prompt,
        "--model",
        MODEL,
        "--dir",
        str(job_dir),
    ]
    result = run_command(cmd, cwd=job_dir, env=env, timeout=7200)
    log_path = job_dir / "opencode.log"
    log_path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    return {
        "exit_code": result.returncode,
        "log": str(log_path),
        "applied_skills": applied_skills,
        "opencode_config": str(local_config_path),
    }


def extract_first(pattern: str, text: str, flags: int = 0) -> str:
    match = re.search(pattern, text, flags=flags)
    return match.group(1).strip() if match else ""


def find_meta_content(html: str, name: str, attribute: str = "name") -> str:
    pattern = rf"<meta[^>]+{attribute}=[\"']{re.escape(name)}[\"'][^>]+content=[\"']([^\"']*)[\"'][^>]*>"
    return extract_first(pattern, html, flags=re.IGNORECASE)


def extract_json_ld_blocks(html: str) -> list[str]:
    return re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def normalize_text_for_overlap(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def audit_generated_content(job_dir: Path, request: dict) -> dict:
    index_file = job_dir / "dist" / "index.html"
    if not index_file.exists():
        raise RuntimeError("dist/index.html missing for content audit")

    html = index_file.read_text(encoding="utf-8", errors="ignore")
    source_context = request.get("source_context") or {}
    business_profile = source_context.get("business_profile", {})
    content_blueprint = source_context.get("content_blueprint", {})
    source_summary = (source_context.get("source") or {}).get("summary", {})
    findings: list[dict] = []

    hrefs = re.findall(r"""href=["']([^"']+)["']""", html, flags=re.IGNORECASE)
    forbidden_urls = [url for url in content_blueprint.get("forbidden_urls", []) if url]
    hostname = request["hostname"]
    legacy_links = [href for href in hrefs if any(url in href for url in forbidden_urls) or hostname in href]
    if legacy_links:
        findings.append({
            "rule": "legacy-links",
            "severity": "high",
            "message": f"Generated preview still links back to the old site: {legacy_links[:4]}",
        })

    if request["industry"] == "restaurant":
        has_menu_section = bool(re.search(r">\s*menu(?:\s+highlights)?\s*<", html, flags=re.IGNORECASE))
        price_count = len(re.findall(r"\$\d{1,3}(?:\.\d{2})?", html))
        if not has_menu_section or price_count < 2:
            findings.append({
                "rule": "missing-rebuilt-menu",
                "severity": "high",
                "message": "Restaurant redesign should include an on-page rebuilt menu or menu highlights instead of sending users elsewhere.",
            })
        if any("menu" in href.lower() for href in hrefs if hostname in href):
            findings.append({
                "rule": "legacy-menu-link",
                "severity": "high",
                "message": "Preview still links to the old external menu URL instead of rebuilding menu content.",
            })

    if not content_blueprint.get("review_evidence_present"):
        if re.search(r"\b(yelp|google|tripadvisor)\b", html, flags=re.IGNORECASE) or re.search(r"[★☆]{3,}", html):
            findings.append({
                "rule": "invented-reviews",
                "severity": "high",
                "message": "Preview appears to include review-platform attributions or star ratings without extracted review evidence.",
            })

    if "google.com/maps" in html or "/maps/dir/" in html:
        if re.search(r"alt=[\"']Map to .*?[\"']", html, flags=re.IGNORECASE) and not re.search(r"<iframe[^>]+maps", html, flags=re.IGNORECASE):
            findings.append({
                "rule": "fake-map-visual",
                "severity": "medium",
                "message": "Location area uses a decorative image labeled like a map instead of a real embedded map surface.",
            })

    source_excerpt = normalize_text_for_overlap(source_summary.get("markdown_excerpt", ""))
    if source_excerpt:
        generated_text = normalize_text_for_overlap(html)
        copied_markers = []
        for snippet in re.split(r"[.!?]\s+", source_excerpt):
            snippet = snippet.strip()
            if len(snippet) >= 100 and snippet in generated_text:
                copied_markers.append(snippet[:120])
            if len(copied_markers) >= 3:
                break
        if copied_markers:
            findings.append({
                "rule": "verbatim-source-copy",
                "severity": "medium",
                "message": "Long source sentences appear to be copied too directly into the redesign.",
                "examples": copied_markers,
            })

    report = {
        "status": "clean" if not findings else "findings",
        "findings_count": len(findings),
        "findings": findings,
    }
    (job_dir / "content-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def format_content_finding(item: dict) -> str:
    extra = ""
    if item.get("examples"):
        extra = f" | examples: {' || '.join(item['examples'][:2])}"
    return f"- [{item.get('rule', 'issue')}] severity={item.get('severity', 'unknown')} — {item.get('message', '')}{extra}"


def run_content_refinement(job_dir: Path, request: dict, audit: dict) -> dict:
    findings = audit.get("findings", [])[:10]
    findings_block = "\n".join(format_content_finding(item) for item in findings) or "- No content findings provided"
    source_context = request.get("source_context") or {}
    content_blueprint = source_context.get("content_blueprint", {})
    business_profile = source_context.get("business_profile", {})
    prompt = f"""You are running a targeted content-integrity refinement pass on an existing static site in ./dist.

Edit only files inside ./dist and ./dist/redesign-summary.md.
Do not rebuild from scratch. Preserve the current design concept and layout unless a finding requires adjustment.

Fix these content and brand-integrity findings:
{findings_block}

Requirements:
- Rewrite copy so it feels sharper and more bespoke without changing factual business information.
- Do not use legacy source-site navigation or CTA links. Remove old menu/about/contact links and rebuild that content inside the preview.
- If this is a restaurant, ensure menu highlights exist on the page itself with at least a few representative dishes or dayparts.
- Do not invent testimonials, star ratings, Google/Yelp attributions, awards, or stats unless they are explicitly present in extracted source facts.
- If reviews are unsupported, replace them with stronger factual trust modules based on longevity, atmosphere, location, hours, team, or hospitality cues.
- The footer/location module must include a real directions or maps link and should not use a decorative photo as a fake map.
- Append a short 'Content integrity refinement' note to ./dist/redesign-summary.md describing what changed.

Blueprint reminders:
- Rewrite rule: {content_blueprint.get('rewrite_rule', '')}
- Link rule: {content_blueprint.get('link_rule', '')}
- Menu rule: {content_blueprint.get('menu_rule', '')}
- Business name: {business_profile.get('business_name', '')}
"""
    prompt_file = job_dir / "content-refinement-prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    local_config_path = build_local_opencode_config(job_dir)
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(local_config_path)
    cmd = ["opencode", "run", prompt, "--model", MODEL, "--dir", str(job_dir)]
    result = run_command(cmd, cwd=job_dir, env=env, timeout=3600)
    log_path = job_dir / "content-refinement.log"
    log_path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    return {
        "exit_code": result.returncode,
        "log": str(log_path),
        "prompt": str(prompt_file),
        "findings_used": len(findings),
    }


def run_content_pipeline(job_id: str, job_dir: Path, request: dict) -> dict:
    audit = audit_generated_content(job_dir, request)
    passes: list[dict] = []
    if audit.get("status") != "findings" or not request.get("content_autofix", True):
        audit["passes"] = passes
        return audit

    for pass_index in range(1, CONTENT_MAX_REFINEMENT_PASSES + 1):
        update_state(job_id, step="running-content-refinement", content=audit)
        refinement = run_content_refinement(job_dir, request, audit)
        next_audit = None
        if refinement.get("exit_code") == 0:
            next_audit = audit_generated_content(job_dir, request)
        pass_report = {"pass": pass_index, "refinement": refinement, "post_refinement": next_audit}
        passes.append(pass_report)
        audit["passes"] = passes
        audit["refinement"] = refinement
        audit["post_refinement"] = next_audit
        if not next_audit or next_audit.get("status") != "findings":
            break
        audit = next_audit

    audit["passes"] = passes
    return audit


def audit_generated_seo(job_dir: Path, request: dict) -> dict:
    index_file = job_dir / "dist" / "index.html"
    if not index_file.exists():
        raise RuntimeError("dist/index.html missing for SEO audit")

    html = index_file.read_text(encoding="utf-8", errors="ignore")
    source_context = request.get("source_context") or {}
    business_profile = source_context.get("business_profile", {})
    seo_blueprint = source_context.get("seo_blueprint", {})
    findings: list[dict] = []

    title = extract_first(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not title:
        findings.append({"rule": "missing-title", "severity": "high", "message": "Page title tag is missing."})
    elif not 35 <= len(title) <= 70:
        findings.append({"rule": "title-length", "severity": "medium", "message": f"Title length is {len(title)} characters; target 35-70."})

    description = find_meta_content(html, "description")
    if not description:
        findings.append({"rule": "missing-meta-description", "severity": "high", "message": "Meta description is missing."})
    elif not 110 <= len(description) <= 170:
        findings.append({"rule": "meta-description-length", "severity": "medium", "message": f"Meta description length is {len(description)} characters; target 110-170."})

    canonical = extract_first(r"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']([^\"']+)[\"'][^>]*>", html, flags=re.IGNORECASE)
    if not canonical:
        findings.append({"rule": "missing-canonical", "severity": "high", "message": "Canonical link tag is missing."})

    for key in ("og:title", "og:description", "og:image"):
        if not find_meta_content(html, key, "property"):
            findings.append({"rule": f"missing-{key.replace(':', '-')}", "severity": "medium", "message": f"{key} meta tag is missing."})
    if not find_meta_content(html, "twitter:card"):
        findings.append({"rule": "missing-twitter-card", "severity": "medium", "message": "twitter:card meta tag is missing."})

    h1_count = len(re.findall(r"<h1\b", html, flags=re.IGNORECASE))
    if h1_count != 1:
        findings.append({"rule": "h1-count", "severity": "high", "message": f"Expected exactly one H1, found {h1_count}."})

    img_tags = re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE)
    missing_alt = [tag for tag in img_tags if not re.search(r"\balt=[\"'][^\"']*[\"']", tag, flags=re.IGNORECASE)]
    if missing_alt:
        findings.append({"rule": "missing-image-alt", "severity": "medium", "message": f"{len(missing_alt)} image(s) are missing alt text."})

    json_ld_blocks = extract_json_ld_blocks(html)
    if not json_ld_blocks:
        findings.append({"rule": "missing-json-ld", "severity": "high", "message": "Structured data JSON-LD block is missing."})
    else:
        combined = "\n".join(json_ld_blocks)
        if seo_blueprint.get("schema_type") and seo_blueprint["schema_type"] not in combined:
            findings.append({"rule": "schema-type", "severity": "medium", "message": f"Expected schema type {seo_blueprint['schema_type']} not found in JSON-LD."})
        if business_profile.get("business_name") and business_profile["business_name"] not in combined:
            findings.append({"rule": "schema-name", "severity": "medium", "message": "Business name not found in JSON-LD."})
        if business_profile.get("phone") and business_profile["phone"] not in combined:
            findings.append({"rule": "schema-phone", "severity": "low", "message": "Phone number missing from JSON-LD."})
        if business_profile.get("address") and business_profile["address"] not in combined:
            findings.append({"rule": "schema-address", "severity": "low", "message": "Address missing from JSON-LD."})

    if business_profile.get("maps_query_url") and business_profile["maps_query_url"] not in html and "google.com/maps" not in html:
        findings.append({"rule": "missing-map-link", "severity": "high", "message": "Footer/location area does not contain a real Google Maps or directions link."})

    report = {
        "status": "clean" if not findings else "findings",
        "findings_count": len(findings),
        "findings": findings,
        "title": title,
        "meta_description": description,
        "canonical": canonical,
    }
    (job_dir / "seo-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def format_seo_finding(item: dict) -> str:
    return f"- [{item.get('rule', 'issue')}] severity={item.get('severity', 'unknown')} — {item.get('message', '')}"


def run_seo_refinement(job_dir: Path, request: dict, audit: dict) -> dict:
    findings = audit.get("findings", [])[:10]
    findings_block = "\n".join(format_seo_finding(item) for item in findings) or "- No SEO findings provided"
    source_context = request.get("source_context") or {}
    seo_blueprint = source_context.get("seo_blueprint", {})
    business_profile = source_context.get("business_profile", {})
    prompt = f"""You are running a targeted SEO refinement pass on an existing static site in ./dist.

Edit only files inside ./dist and ./dist/redesign-summary.md.
Do not rebuild from scratch. Preserve the current design concept and layout unless a finding requires adjustment.

Fix these SEO findings:
{findings_block}

Requirements:
- Ensure ./dist/index.html has a high-quality title tag, meta description, canonical tag, Open Graph tags, and twitter:card metadata.
- Keep metadata aligned with this title formula: {seo_blueprint.get('title_formula', '')}
- Use schema type {seo_blueprint.get('schema_type', 'LocalBusiness')} in a valid application/ld+json block.
- Include real business facts where available: name={business_profile.get('business_name', '')}, address={business_profile.get('address', '')}, phone={business_profile.get('phone', '')}, hours={business_profile.get('hours', '')}.
- Use exactly one H1 and ensure non-decorative images have meaningful alt text.
- Ensure the footer/location area includes a real map or directions link using: {business_profile.get('maps_query_url', '') or request['website_url']}
- Append a short 'SEO refinement' note to ./dist/redesign-summary.md describing what changed.
"""
    prompt_file = job_dir / "seo-refinement-prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    local_config_path = build_local_opencode_config(job_dir)
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(local_config_path)
    cmd = ["opencode", "run", prompt, "--model", MODEL, "--dir", str(job_dir)]
    result = run_command(cmd, cwd=job_dir, env=env, timeout=3600)
    log_path = job_dir / "seo-refinement.log"
    log_path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    return {
        "exit_code": result.returncode,
        "log": str(log_path),
        "prompt": str(prompt_file),
        "findings_used": len(findings),
    }


def run_seo_pipeline(job_id: str, job_dir: Path, request: dict) -> dict:
    audit = audit_generated_seo(job_dir, request)
    passes: list[dict] = []
    if audit.get("status") != "findings" or not request.get("seo_autofix", True):
        audit["passes"] = passes
        return audit

    for pass_index in range(1, SEO_MAX_REFINEMENT_PASSES + 1):
        update_state(job_id, step="running-seo-refinement", seo=audit)
        refinement = run_seo_refinement(job_dir, request, audit)
        next_audit = None
        if refinement.get("exit_code") == 0:
            next_audit = audit_generated_seo(job_dir, request)
        pass_report = {"pass": pass_index, "refinement": refinement, "post_refinement": next_audit}
        passes.append(pass_report)
        audit["passes"] = passes
        audit["refinement"] = refinement
        audit["post_refinement"] = next_audit
        if not next_audit or next_audit.get("status") != "findings":
            break
        audit = next_audit

    audit["passes"] = passes
    return audit


def run_node_json_script(script_name: str, args: list[str], cwd: Path, timeout: int) -> tuple[dict, dict]:
    script_path = BASE_DIR / "app" / script_name
    env = os.environ.copy()
    env["CHROME_PATH"] = env.get("CHROME_PATH", "/usr/bin/chromium")
    result = run_command(["node", str(script_path), *args], cwd=cwd, env=env, timeout=timeout)
    stdout_payload = {}
    if result.stdout.strip():
        try:
            stdout_payload = json.loads(result.stdout)
        except Exception:
            stdout_payload = {}
    log = {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    return stdout_payload, log


def audit_with_lighthouse(job_dir: Path, request: dict) -> dict:
    index_file = job_dir / "dist" / "index.html"
    if not index_file.exists():
        raise RuntimeError("dist/index.html missing for Lighthouse audit")

    server = None
    try:
        server, url = start_dist_server(job_dir)
        output_path = job_dir / "lighthouse-audit.json"
        payload, log = run_node_json_script(
            "run_lighthouse_audit.mjs",
            [url, str(output_path)],
            cwd=job_dir,
            timeout=LIGHTHOUSE_TIMEOUT,
        )
    finally:
        stop_dist_server(server)

    log_path = job_dir / "lighthouse-audit.log"
    log_path.write_text(
        f"exit_code={log['exit_code']}\n\nSTDOUT:\n{log['stdout']}\n\nSTDERR:\n{log['stderr']}\n",
        encoding="utf-8",
    )
    if not payload:
        payload = {
            "status": "error",
            "findingsCount": 0,
            "findings": [],
            "scores": {},
            "error": "No Lighthouse payload returned.",
        }
    payload["log"] = str(log_path)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def format_lighthouse_finding(item: dict) -> str:
    return f"- [{item.get('rule', 'issue')}] severity={item.get('severity', 'unknown')} — {item.get('message', '')}"


def run_lighthouse_refinement(job_dir: Path, request: dict, audit: dict) -> dict:
    findings = audit.get("findings", [])[:10]
    findings_block = "\n".join(format_lighthouse_finding(item) for item in findings) or "- No Lighthouse findings provided"
    prompt = f"""You are running a targeted Lighthouse-driven refinement pass on an existing static site in ./dist.

Edit only files inside ./dist and ./dist/redesign-summary.md.
Do not rebuild from scratch. Preserve the current design concept and business identity.

Fix these Lighthouse findings:
{findings_block}

Requirements:
- Improve SEO, best-practices, and performance issues without flattening the design.
- Reduce avoidable render-blocking patterns and oversized decorative overhead where practical.
- Keep metadata, structured data, and crawlable text content intact or improved.
- Do not remove the location module, menu highlights, or proof sections while optimizing.
- Append a short 'Lighthouse refinement' note to ./dist/redesign-summary.md describing what changed.
"""
    prompt_file = job_dir / "lighthouse-refinement-prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    local_config_path = build_local_opencode_config(job_dir)
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(local_config_path)
    result = run_command(["opencode", "run", prompt, "--model", MODEL, "--dir", str(job_dir)], cwd=job_dir, env=env, timeout=3600)
    log_path = job_dir / "lighthouse-refinement.log"
    log_path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    return {"exit_code": result.returncode, "log": str(log_path), "prompt": str(prompt_file), "findings_used": len(findings)}


def run_lighthouse_pipeline(job_id: str, job_dir: Path, request: dict) -> dict:
    audit = audit_with_lighthouse(job_dir, request)
    passes: list[dict] = []
    if audit.get("status") != "findings" or not request.get("lighthouse_autofix", True):
        audit["passes"] = passes
        return audit

    for pass_index in range(1, LIGHTHOUSE_MAX_REFINEMENT_PASSES + 1):
        update_state(job_id, step="running-lighthouse-refinement", lighthouse=audit)
        refinement = run_lighthouse_refinement(job_dir, request, audit)
        next_audit = None
        if refinement.get("exit_code") == 0:
            next_audit = audit_with_lighthouse(job_dir, request)
        pass_report = {"pass": pass_index, "refinement": refinement, "post_refinement": next_audit}
        passes.append(pass_report)
        audit["passes"] = passes
        audit["refinement"] = refinement
        audit["post_refinement"] = next_audit
        if not next_audit or next_audit.get("status") != "findings":
            break
        audit = next_audit

    audit["passes"] = passes
    return audit


def audit_with_axe(job_dir: Path, request: dict) -> dict:
    index_file = job_dir / "dist" / "index.html"
    if not index_file.exists():
        raise RuntimeError("dist/index.html missing for axe audit")

    server = None
    try:
        server, url = start_dist_server(job_dir)
        output_path = job_dir / "axe-audit.json"
        payload, log = run_node_json_script(
            "run_axe_audit.mjs",
            [url, str(output_path)],
            cwd=job_dir,
            timeout=AXE_TIMEOUT,
        )
    finally:
        stop_dist_server(server)

    log_path = job_dir / "axe-audit.log"
    log_path.write_text(
        f"exit_code={log['exit_code']}\n\nSTDOUT:\n{log['stdout']}\n\nSTDERR:\n{log['stderr']}\n",
        encoding="utf-8",
    )
    if not payload:
        payload = {
            "status": "error",
            "findingsCount": 0,
            "findings": [],
            "error": "No axe payload returned.",
        }
    payload["log"] = str(log_path)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def format_axe_finding(item: dict) -> str:
    nodes = item.get("nodes", [])[:2]
    targets = ", ".join(" / ".join(node.get("target", [])) for node in nodes if node.get("target"))
    suffix = f" | targets: {targets}" if targets else ""
    return f"- [{item.get('rule', 'issue')}] severity={item.get('severity', 'unknown')} — {item.get('message', '')}{suffix}"


def run_axe_refinement(job_dir: Path, request: dict, audit: dict) -> dict:
    findings = audit.get("findings", [])[:10]
    findings_block = "\n".join(format_axe_finding(item) for item in findings) or "- No accessibility findings provided"
    prompt = f"""You are running a targeted accessibility refinement pass on an existing static site in ./dist.

Edit only files inside ./dist and ./dist/redesign-summary.md.
Do not rebuild from scratch. Preserve the current design concept and business identity.

Fix these accessibility findings:
{findings_block}

Requirements:
- Resolve contrast, semantics, labeling, and structure issues while preserving the overall design quality.
- Use real text labels and descriptive alt text where needed.
- Preserve menu, location, proof, and CTA clarity.
- Append a short 'Accessibility refinement' note to ./dist/redesign-summary.md describing what changed.
"""
    prompt_file = job_dir / "axe-refinement-prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    local_config_path = build_local_opencode_config(job_dir)
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(local_config_path)
    result = run_command(["opencode", "run", prompt, "--model", MODEL, "--dir", str(job_dir)], cwd=job_dir, env=env, timeout=3600)
    log_path = job_dir / "axe-refinement.log"
    log_path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    return {"exit_code": result.returncode, "log": str(log_path), "prompt": str(prompt_file), "findings_used": len(findings)}


def run_axe_pipeline(job_id: str, job_dir: Path, request: dict) -> dict:
    audit = audit_with_axe(job_dir, request)
    passes: list[dict] = []
    if audit.get("status") != "findings" or not request.get("axe_autofix", True):
        audit["passes"] = passes
        return audit

    for pass_index in range(1, AXE_MAX_REFINEMENT_PASSES + 1):
        update_state(job_id, step="running-axe-refinement", axe=audit)
        refinement = run_axe_refinement(job_dir, request, audit)
        next_audit = None
        if refinement.get("exit_code") == 0:
            next_audit = audit_with_axe(job_dir, request)
        pass_report = {"pass": pass_index, "refinement": refinement, "post_refinement": next_audit}
        passes.append(pass_report)
        audit["passes"] = passes
        audit["refinement"] = refinement
        audit["post_refinement"] = next_audit
        if not next_audit or next_audit.get("status") != "findings":
            break
        audit = next_audit

    audit["passes"] = passes
    return audit


def parse_impeccable_json(output: str) -> list[dict]:
    output = (output or "").strip()
    if not output:
        return []
    try:
        data = json.loads(output)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def run_impeccable_detect(job_dir: Path) -> dict:
    executable = shutil.which("impeccable")
    if executable:
        cmd = [executable, "detect", "--json", "dist"]
    else:
        cmd = ["npx", "-y", "impeccable", "detect", "--json", "dist"]
    result = run_command(cmd, cwd=job_dir, timeout=IMPECCABLE_TIMEOUT)
    log_path = job_dir / "impeccable.log"
    log_path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    findings = parse_impeccable_json(result.stdout) or parse_impeccable_json(result.stderr)
    report = {
        "exit_code": result.returncode,
        "log": str(log_path),
        "findings_count": len(findings),
        "findings": findings,
        "status": "clean" if result.returncode == 0 else ("findings" if result.returncode == 2 else "error"),
    }
    (job_dir / "impeccable.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def format_impeccable_finding(item: dict) -> str:
    antipattern = item.get("antipattern") or item.get("rule") or "issue"
    file_name = item.get("file") or item.get("path") or "unknown file"
    line = item.get("line")
    message = item.get("message") or item.get("description") or item.get("reason") or ""
    suggestion = item.get("suggestion") or item.get("fix") or ""
    location = f"{file_name}:{line}" if line else file_name
    text = f"- [{antipattern}] {location}"
    if message:
        text += f" — {message}"
    if suggestion:
        text += f" | fix: {suggestion}"
    return text


def run_impeccable_refinement(job_dir: Path, request: dict, critique: dict) -> dict:
    findings = critique.get("findings", [])[:IMPECCABLE_MAX_FINDINGS]
    findings_block = "\n".join(format_impeccable_finding(item) for item in findings) or "- No findings provided"
    prompt = f"""You are running a targeted post-generation refinement pass on an existing static site in ./dist.

Edit only files inside ./dist and ./dist/redesign-summary.md.
Do not rebuild from scratch. Preserve the current concept, business identity, and overall layout unless a finding requires adjustment.

Fix these Impeccable findings:
{findings_block}

Requirements:
- Prioritize accessibility, typography quality, visual hierarchy, spacing rhythm, and anti-generic design issues.
- Keep the existing design-family-led concept intact.
- Make the smallest set of edits that materially improves the result.
- Fully resolve every listed finding, not just some of them.
- Do not replace one low-contrast issue with another. If the background is bright or multicolored, use dark text or add a dark surface behind the text.
- Remove decorative gradient text entirely; use solid text colors with clear contrast.
- Prefer distinctive but readable font stacks over generic defaults like Arial.
- When fixing contrast, aim to clearly exceed WCAG AA rather than barely meeting it.
- Append a short 'Impeccable refinement' note to ./dist/redesign-summary.md describing what changed.
"""
    prompt_file = job_dir / "impeccable-refinement-prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    local_config_path = build_local_opencode_config(job_dir)
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(local_config_path)
    cmd = [
        "opencode",
        "run",
        prompt,
        "--model",
        MODEL,
        "--dir",
        str(job_dir),
    ]
    result = run_command(cmd, cwd=job_dir, env=env, timeout=3600)
    log_path = job_dir / "impeccable-refinement.log"
    log_path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n",
        encoding="utf-8",
    )
    return {
        "exit_code": result.returncode,
        "log": str(log_path),
        "prompt": str(prompt_file),
        "findings_used": len(findings),
    }


def run_impeccable_pipeline(job_id: str, job_dir: Path, request: dict) -> dict:
    critique_result = run_impeccable_detect(job_dir)
    passes: list[dict] = []
    if critique_result.get("status") != "findings" or not request.get("impeccable_autofix", True):
        critique_result["passes"] = passes
        return critique_result

    for pass_index in range(1, IMPECCABLE_MAX_REFINEMENT_PASSES + 1):
        update_state(job_id, step="running-impeccable-refinement", impeccable=critique_result)
        refinement = run_impeccable_refinement(job_dir, request, critique_result)
        next_detect = None
        if refinement.get("exit_code") == 0:
            next_detect = run_impeccable_detect(job_dir)
        pass_report = {
            "pass": pass_index,
            "refinement": refinement,
            "post_refinement": next_detect,
        }
        passes.append(pass_report)
        critique_result["passes"] = passes
        critique_result["refinement"] = refinement
        critique_result["post_refinement"] = next_detect
        if not next_detect or next_detect.get("status") != "findings":
            break
        critique_result = next_detect

    critique_result["passes"] = passes
    return critique_result


def publish_preview(job_dir: Path, slug: str) -> str:
    dist = job_dir / "dist"
    if not dist.exists() or not (dist / "index.html").exists():
        raise RuntimeError("dist/index.html was not generated")
    target = PREVIEWS_DIR / slug
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(dist, target)
    return f"{PUBLIC_BASE_URL}/preview/{slug}/"


def send_callback(callback_url: str, state: dict) -> None:
    if not callback_url:
        return
    payload = json.dumps(state).encode("utf-8")
    request = Request(
        callback_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        response.read()


def safe_send_callback(job_id: str, callback_url: str, state: dict) -> None:
    try:
        send_callback(callback_url, state)
    except Exception as exc:
        update_state(job_id, callback_error=str(exc))


def send_job_email(request: dict, state: dict) -> dict | None:
    notify_email = request.get("notify_email", "").strip()
    if not notify_email:
        return None

    success = state.get("status") == "completed"
    subject = (
        f"Website redesign preview ready: {request['client_slug']}"
        if success
        else f"Website redesign job failed: {request['client_slug']}"
    )
    body_lines = [
        "Your redesign preview is ready." if success else "Your redesign job failed.",
        "",
        f"Source site: {request['website_url']}",
        f"Job ID: {state.get('job_id', '')}",
        f"Model: {state.get('model', MODEL)}",
        f"Industry: {request.get('industry', DEFAULT_INDUSTRY)}",
        f"Skills: {', '.join(state.get('applied_skills', [])) or ', '.join(request.get('enabled_skills', []))}",
        f"Status URL: {PUBLIC_BASE_URL}/jobs/{state.get('job_id', '')}",
    ]
    if success:
        body_lines.append(f"Preview URL: {state.get('preview_url', '')}")
    else:
        body_lines.append(f"Error: {state.get('error', 'Unknown error')}")
    body_lines.extend(["", "This job was processed automatically."])

    cmd = [
        "gws-email",
        "--to",
        notify_email,
        "--subject",
        subject,
        "--body",
        "\n".join(body_lines),
    ]
    result = run_command(cmd, timeout=120)
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def process_job(job_id: str, request: dict) -> None:
    job_dir = job_dir_path(job_id)
    try:
        update_state(job_id, status="running", step="capturing-source", model=MODEL)
        source_context = analyze_site_context(job_dir, request)
        request["source_context"] = source_context
        update_state(job_id, request=request, source_capture=source_context)

        if request["dry_run"]:
            _, applied_skills = build_prompt(request, job_dir)
            update_state(job_id, step="creating-dry-run-preview", applied_skills=applied_skills)
            create_dry_run_preview(job_dir, request, applied_skills)
            opencode_result = {"exit_code": 0, "log": None, "dry_run": True, "applied_skills": applied_skills}
        else:
            update_state(job_id, step="running-opencode")
            opencode_result = run_opencode_redesign(job_dir, request)
            if opencode_result["exit_code"] != 0:
                raise RuntimeError(f"OpenCode exited with code {opencode_result['exit_code']}")

        content_result = None
        if request.get("content_critique", True):
            update_state(job_id, step="running-content-audit")
            try:
                content_result = run_content_pipeline(job_id, job_dir, request)
                update_state(job_id, content=content_result)
            except Exception as exc:
                content_result = {"status": "error", "error": str(exc)}
                update_state(job_id, content=content_result)

        seo_result = None
        if request.get("seo_critique", True):
            update_state(job_id, step="running-seo")
            try:
                seo_result = run_seo_pipeline(job_id, job_dir, request)
                update_state(job_id, seo=seo_result)
            except Exception as exc:
                seo_result = {"status": "error", "error": str(exc)}
                update_state(job_id, seo=seo_result)

        lighthouse_result = None
        if not request["dry_run"] and request.get("lighthouse_critique", True):
            update_state(job_id, step="running-lighthouse")
            try:
                lighthouse_result = run_lighthouse_pipeline(job_id, job_dir, request)
                update_state(job_id, lighthouse=lighthouse_result)
            except Exception as exc:
                lighthouse_result = {"status": "error", "error": str(exc)}
                update_state(job_id, lighthouse=lighthouse_result)

        axe_result = None
        if not request["dry_run"] and request.get("axe_critique", True):
            update_state(job_id, step="running-axe")
            try:
                axe_result = run_axe_pipeline(job_id, job_dir, request)
                update_state(job_id, axe=axe_result)
            except Exception as exc:
                axe_result = {"status": "error", "error": str(exc)}
                update_state(job_id, axe=axe_result)

        critique_result = None
        if not request["dry_run"] and request.get("impeccable_critique", True):
            update_state(job_id, step="running-impeccable")
            try:
                critique_result = run_impeccable_pipeline(job_id, job_dir, request)
                update_state(job_id, impeccable=critique_result)
            except Exception as exc:
                critique_result = {"status": "error", "error": str(exc)}
                update_state(job_id, impeccable=critique_result)

        update_state(
            job_id,
            step="publishing-preview",
            opencode=opencode_result,
            applied_skills=opencode_result.get("applied_skills", []),
            content=content_result,
            seo=seo_result,
            lighthouse=lighthouse_result,
            axe=axe_result,
            impeccable=critique_result,
        )
        preview_url = publish_preview(job_dir, request["client_slug"])
        update_state(
            job_id,
            status="completed",
            step="completed",
            preview_url=preview_url,
            preview_slug=request["client_slug"],
        )
        completion_state = get_state(job_id) or {}
        email_result = send_job_email(request, completion_state)
        if email_result is not None:
            completion_state = update_state(job_id, email=email_result)
        safe_send_callback(job_id, request["callback_url"], completion_state)
    except Exception as exc:
        failed_state = update_state(
            job_id,
            status="failed",
            step="failed",
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        email_result = send_job_email(request, failed_state)
        if email_result is not None:
            failed_state = update_state(job_id, email=email_result)
        safe_send_callback(job_id, request["callback_url"], failed_state)


def run_qualification(request: dict) -> dict:
    qualification_id = f"qual_{uuid.uuid4().hex[:12]}"
    run_dir = QUALIFICATION_RUNS_DIR / qualification_id
    run_dir.mkdir(parents=True, exist_ok=True)

    source_context = analyze_site_context(run_dir, request)
    try:
        source_context["visual_audit"] = audit_source_visual_design(run_dir, request)
    except Exception as exc:
        source_context["visual_audit"] = {
            "status": "error",
            "visualDesignScore": None,
            "strongSignals": [],
            "weakSignals": [],
            "metrics": {},
            "error": str(exc),
        }
    try:
        source_context["source_lighthouse"] = audit_source_lighthouse(run_dir, request)
    except Exception as exc:
        source_context["source_lighthouse"] = {
            "status": "error",
            "findingsCount": 0,
            "findings": [],
            "scores": {},
            "error": str(exc),
        }
    try:
        source_context["source_axe"] = audit_source_axe(run_dir, request)
    except Exception as exc:
        source_context["source_axe"] = {
            "status": "error",
            "findingsCount": 0,
            "findings": [],
            "error": str(exc),
        }
    assessment = assess_website_quality(request, source_context)
    response = {
        "qualification_id": qualification_id,
        "created_at": now_iso(),
        "request": {
            "website_url": request["website_url"],
            "hostname": request["hostname"],
            "industry": request["industry"],
            "company_name": request.get("company_name", ""),
            "lead_id": request.get("lead_id", ""),
            "source_row_id": request.get("source_row_id", ""),
            "qualification_notes": request.get("qualification_notes", ""),
        },
        "business_profile": source_context.get("business_profile", {}),
        "source_summary": source_context.get("source", {}).get("summary", {}),
        "visual_audit": source_context.get("visual_audit", {}),
        "source_lighthouse": source_context.get("source_lighthouse", {}),
        "source_axe": source_context.get("source_axe", {}),
        "assessment": assessment,
        "artifacts": {
            "run_dir": str(run_dir),
            "source_root": source_context.get("source", {}).get("source_root"),
            "index_file": source_context.get("source", {}).get("index_file"),
            "business_profile": str(run_dir / "source" / "analysis" / "business-profile.json"),
            "design_engine": str(run_dir / "source" / "analysis" / "design-engine.json"),
            "concept_blueprint": str(run_dir / "source" / "analysis" / "concept-blueprint.json"),
            "visual_audit": str(run_dir / "source" / "analysis" / "source-visual-audit.json"),
            "source_screenshot": str(run_dir / "source" / "source-homepage.png"),
            "source_lighthouse": str(run_dir / "source" / "analysis" / "source-lighthouse-audit.json"),
            "source_axe": str(run_dir / "source" / "analysis" / "source-axe-audit.json"),
        },
    }
    write_json(run_dir / "qualification.json", response)
    return response


class Handler(BaseHTTPRequestHandler):
    server_version = "WebsiteRedesignRunner/0.2"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path, content_type: str) -> None:
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self._send_json(
                {
                    "healthy": True,
                    "model": MODEL,
                    "public_base_url": PUBLIC_BASE_URL,
                    "firecrawl_url": FIRECRAWL_URL,
                    "model_policy": "deny-openrouter",
                    "endpoints": ["/health", "/skills", "/jobs", "/qualify", "/qualification-runs/<id>"],
                    "run_modes": sorted(ALLOWED_RUN_MODES),
                    "generator_profiles": sorted(ALLOWED_GENERATOR_PROFILES),
                    "design_families": sorted(ALLOWED_DESIGN_FAMILIES),
                    "image_strategies": sorted(ALLOWED_IMAGE_STRATEGIES),
                    "skills": list_available_skills(),
                }
            )
            return

        if parsed.path == "/skills":
            self._send_json(list_available_skills())
            return

        if parsed.path.startswith("/skills/"):
            relative = unquote(parsed.path[len("/skills/"):]).lstrip("/")
            safe = Path(relative)
            if ".." in safe.parts:
                self._send_json({"error": "invalid path"}, status=400)
                return
            if safe.suffix != ".md":
                safe = safe.with_suffix(".md")
            skill_path = SKILLS_DIR / safe
            if not skill_path.exists() or not skill_path.is_file():
                self._send_json({"error": "skill not found"}, status=404)
                return
            self._send_json(
                {
                    "name": skill_path.stem,
                    "path": str(skill_path),
                    "content": skill_path.read_text(encoding="utf-8"),
                }
            )
            return

        if parsed.path.startswith("/qualification-runs/"):
            qualification_id = parsed.path.strip("/").split("/")[1]
            run_dir = QUALIFICATION_RUNS_DIR / qualification_id
            report_path = run_dir / "qualification.json"
            if not report_path.exists():
                self._send_json({"error": "qualification run not found"}, status=404)
                return
            self._send_file(report_path, "application/json; charset=utf-8")
            return

        if parsed.path.startswith("/jobs/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 3 and parts[2] == "prompt":
                job_id = parts[1]
                prompt_path = job_dir_path(job_id) / "prompt.txt"
                if not prompt_path.exists():
                    self._send_json({"error": "prompt not found"}, status=404)
                    return
                self._send_file(prompt_path, "text/plain; charset=utf-8")
                return
            if len(parts) >= 3 and parts[2] == "prompt-parts":
                job_id = parts[1]
                prompt_parts_path = job_dir_path(job_id) / "prompt.parts.json"
                if not prompt_parts_path.exists():
                    self._send_json({"error": "prompt parts not found"}, status=404)
                    return
                self._send_file(prompt_parts_path, "application/json; charset=utf-8")
                return
            if len(parts) >= 4 and parts[2] == "artifacts":
                job_id = parts[1]
                job_root = job_dir_path(job_id)
                if not job_root.exists():
                    self._send_json({"error": "job not found"}, status=404)
                    return
                relative = Path(unquote("/".join(parts[3:]))).as_posix().lstrip("/")
                artifact_path = (job_root / relative).resolve()
                if not str(artifact_path).startswith(str(job_root.resolve())):
                    self._send_json({"error": "invalid artifact path"}, status=400)
                    return
                if not artifact_path.exists() or not artifact_path.is_file():
                    self._send_json({"error": "artifact not found"}, status=404)
                    return
                content_types = {
                    ".json": "application/json; charset=utf-8",
                    ".txt": "text/plain; charset=utf-8",
                    ".md": "text/markdown; charset=utf-8",
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                }
                self._send_file(artifact_path, content_types.get(artifact_path.suffix.lower(), "application/octet-stream"))
                return

            job_id = parts[1]
            state = get_state(job_id)
            if not state:
                self._send_json({"error": "job not found"}, status=404)
                return
            self._send_json(state)
            return

        if parsed.path.startswith("/preview/"):
            relative = unquote(parsed.path[len("/preview/"):]).lstrip("/")
            safe = Path(relative)
            if ".." in safe.parts:
                self._send_json({"error": "invalid path"}, status=400)
                return
            file_path = PREVIEWS_DIR / safe
            if file_path.is_dir():
                file_path = file_path / "index.html"
            if not file_path.exists():
                self._send_json({"error": "preview not found"}, status=404)
                return
            content_types = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
                ".woff": "font/woff",
                ".woff2": "font/woff2",
                ".md": "text/markdown; charset=utf-8",
            }
            self._send_file(file_path, content_types.get(file_path.suffix.lower(), "application/octet-stream"))
            return

        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/qualify":
            try:
                payload = parse_json_body(self)
                request = normalize_qualification_request(payload)
                result = run_qualification(request)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json(result, status=HTTPStatus.OK)
            return

        if parsed.path != "/jobs":
            self._send_json({"error": "not found"}, status=404)
            return

        try:
            payload = parse_json_body(self)
            request = normalize_request(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job_dir = job_dir_path(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "job_id": job_id,
            "status": "queued",
            "step": "queued",
            "request": request,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "model": MODEL,
        }
        write_json(job_state_path(job_id), state)

        thread = threading.Thread(target=process_job, args=(job_id, request), daemon=True)
        thread.start()
        self._send_json(
            {
                "job_id": job_id,
                "status": "queued",
                "status_url": f"{PUBLIC_BASE_URL}/jobs/{job_id}",
                "prompt_url": f"{PUBLIC_BASE_URL}/jobs/{job_id}/prompt",
                "prompt_parts_url": f"{PUBLIC_BASE_URL}/jobs/{job_id}/prompt-parts",
            },
            status=HTTPStatus.ACCEPTED,
        )


def main() -> None:
    validate_model_policy()
    ensure_dirs()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"website redesign runner listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
