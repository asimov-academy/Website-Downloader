"""
Extract semantic structure from HTML without full content.
"""
from bs4 import BeautifulSoup


def extract_structure(html_content: str) -> dict:
    """
    Extract semantic structure from HTML.

    Returns:
        {
            "sections": [
                {
                    "tag": "section",
                    "classes": ["hero", "main"],
                    "id": "hero-section",
                    "role": "banner",
                    "children_count": 3,
                    "depth": 1
                },
                ...
            ],
            "components": {
                "nav": 1,
                "header": 1,
                "footer": 1,
                "section": 5,
                "article": 2
            }
        }
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # Semantic elements we care about
    semantic_tags = {
        'header', 'nav', 'main', 'section', 'article', 'aside', 'footer',
        'form', 'figure', 'dialog', 'details'
    }

    # Class-based components (common patterns)
    component_classes = {
        'hero', 'card', 'button', 'btn', 'modal', 'dialog', 'nav', 'navbar',
        'sidebar', 'header', 'footer', 'container', 'wrapper', 'grid', 'flex'
    }

    sections = []
    component_counts = {}

    def traverse(element, depth=0):
        if not hasattr(element, 'name') or element.name is None:
            return

        tag = element.name
        classes = element.get('class', [])
        element_id = element.get('id', '')
        role = element.get('role', '')

        # Track semantic elements
        if tag in semantic_tags:
            component_counts[tag] = component_counts.get(tag, 0) + 1

            children_count = len([child for child in element.children if hasattr(child, 'name')])

            sections.append({
                'tag': tag,
                'classes': classes if isinstance(classes, list) else [classes],
                'id': element_id,
                'role': role,
                'children_count': children_count,
                'depth': depth,
            })

        # Track class-based components
        if isinstance(classes, list):
            for cls in classes:
                for component in component_classes:
                    if component in cls.lower():
                        key = f'.{component}'
                        component_counts[key] = component_counts.get(key, 0) + 1

        # Recurse
        for child in element.children:
            traverse(child, depth + 1)

    body = soup.find('body')
    if body:
        traverse(body)

    return {
        'sections': sections,
        'components': component_counts,
    }
