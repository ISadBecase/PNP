"""Prompts and style configurations for Poster image generation."""

from typing import Dict


STYLE_PROCESS_PROMPT = """User wants this style for presentation slides: {user_style}

IMPORTANT RULES:
1. Default to MORANDI COLOR PALETTE (soft, muted, low-saturation colors with gray undertones) and LIGHT background unless user specifies otherwise.
2. Keep it CLEAN and SIMPLE - NO flashy/gaudy elements. Every visual element must be MEANINGFUL.
3. LIMITED COLOR PALETTE (3-4 colors max).

Output JSON:
{{
    "style_name": "Style name with brief description (e.g., Cyberpunk sci-fi style with high-tech aesthetic)",
    "color_tone": "Color tone description - prefer Morandi palette with light background (e.g., light cream background with muted sage green and dusty rose accents)",
    "special_elements": "Any special visual elements like characters, mascots, motifs - must be MEANINGFUL, not random decoration",
    "decorations": "Background/border effects - keep SIMPLE and CLEAN (or empty string)",
    "valid": true,
    "error": null
}}

Examples:
- "cyberpunk": {{"style_name": "Cyberpunk sci-fi style with high-tech aesthetic", "color_tone": "dark background with neon cyan and magenta accents", "special_elements": "", "decorations": "subtle grid pattern, neon glow on borders", "valid": true, "error": null}}
- "Studio Ghibli": {{"style_name": "Studio Ghibli anime style with whimsical aesthetic", "color_tone": "light cream background with soft Morandi watercolor tones - muted sage, dusty pink, soft gray-blue", "special_elements": "Totoro or soot sprites can appear as friendly guides - must relate to content", "decorations": "soft clouds or nature elements as borders", "valid": true, "error": null}}
- "minimalist": {{"style_name": "Clean minimalist style", "color_tone": "light warm gray background with Morandi palette - charcoal text, muted gold accent", "special_elements": "", "decorations": "", "valid": true, "error": null}}

If inappropriate, set valid=false with error."""


FORMAT_POSTER = "Wide landscape poster layout (16:9 aspect ratio). Just ONE poster. Keep information density moderate, leave whitespace for readability."

POSTER_STYLE_HINTS: Dict[str, str] = {
    "academic": "Academic conference poster style with LIGHT CLEAN background. English text only. Use PROFESSIONAL, CLEAR tones with good contrast and academic fonts. Preserve details from the content. Title section at the top can have a colored background bar to make it stand out. FIGURES: Preserve original scientific figures - maintain their accuracy, style, and integrity. Include institution logo if present.",
    "doraemon": "Classic Doraemon anime style, bright and friendly. English text only. Use WARM, ELEGANT, MUTED tones. Use ROUNDED sans-serif fonts for ALL text (NO artistic/fancy/decorative fonts). Large readable text. Panels can have scene-appropriate backgrounds (e.g., cloudy for problem, clearing for method, sunny for result). Keep it simple, not too fancy. Doraemon character as guide only (1-2 small figures), not the main focus.",
}

POSTER_COMMON_STYLE_RULES = """IF the poster has figures/tables: focus on them as the main visual content, polish them to fit the style."""

VISUALIZATION_HINTS = """Visualization:
- Use diagrams and icons to represent concepts
- Visualize data/numbers as charts
- Use bullet points, highlight key metrics
- Keep background CLEAN and simple"""

POSTER_FIGURE_HINT = "For reference figures: REDRAW them to match the visual style and color scheme. Preserve the original structure and key information, but make them BLEND seamlessly with the poster design."
