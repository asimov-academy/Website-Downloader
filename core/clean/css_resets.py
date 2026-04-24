"""
Separate CSS resets/normalize from visual rules.
"""
import re

# Patterns for reset/normalize rules
RESET_PATTERNS = [
    r'\*\s*\{[^}]*?(margin|padding|box-sizing)[^}]*?\}',
    r'html\s*,\s*body\s*\{[^}]*?(margin|padding|box-sizing)[^}]*?\}',
    r'body\s*\{[^}]*?(margin:\s*0|padding:\s*0)[^}]*?\}',
    r'html\s*\{[^}]*?(box-sizing:\s*border-box)[^}]*?\}',
    r'\*\s*,\s*\*::before\s*,\s*\*::after\s*\{[^}]*?(box-sizing)[^}]*?\}',
]

# Properties that are typically resets
RESET_PROPERTIES = {
    'margin': '0',
    'padding': '0',
    'box-sizing': 'border-box',
    'border': '0',
    'font-size': '100%',
    'font': 'inherit',
    'vertical-align': 'baseline',
}


def extract_resets(css_content: str) -> tuple[str, str]:
    """
    Extract reset/normalize rules from CSS.

    Returns:
        (resets_css, visual_css) - Split content
    """
    resets = []
    visual_lines = []

    # Split into rules
    rules = re.findall(r'([^{}]+\{[^{}]*\})', css_content, re.DOTALL)

    for rule in rules:
        if _is_reset_rule(rule):
            resets.append(rule)
        else:
            visual_lines.append(rule)

    # If no resets found, return all as visual
    if not resets:
        return '', css_content

    resets_css = '\n'.join(resets)
    visual_css = '\n'.join(visual_lines)

    return resets_css, visual_css


def _is_reset_rule(rule: str) -> bool:
    """Check if a CSS rule is a reset/normalize rule."""
    # Check for universal selectors
    if re.match(r'^\s*\*\s*[,{]', rule):
        return True

    # Check for html/body resets
    if re.match(r'^\s*(html|body)\s*[,{]', rule):
        # Check if it only contains reset properties
        properties = re.findall(r'([a-z-]+)\s*:\s*([^;]+)', rule)
        for prop, value in properties:
            prop = prop.strip()
            value = value.strip()
            if prop in RESET_PROPERTIES:
                if RESET_PROPERTIES[prop] == '*' or value == RESET_PROPERTIES[prop]:
                    return True

    return False
