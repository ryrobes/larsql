"""
DOM extraction for browser automation.

Extracts page content as markdown and clickable element coordinates
to help LLM agents understand and interact with web pages.
"""

from typing import Tuple, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# JavaScript to extract clickable elements and page structure
EXTRACTION_SCRIPT = """
() => {
    const elements = [];

    // Clickable element selectors
    const selectors = [
        'a[href]',
        'button',
        'input',
        'select',
        'textarea',
        '[onclick]',
        '[role="button"]',
        '[role="link"]',
        '[role="menuitem"]',
        '[role="tab"]',
        '[role="checkbox"]',
        '[role="radio"]',
        '[role="switch"]',
        '[role="option"]',
        '[tabindex]:not([tabindex="-1"])',
        'summary',
        'details',
        '[contenteditable="true"]',
        'label[for]',
        '[data-action]',
        '[data-click]',
    ];

    const allClickable = document.querySelectorAll(selectors.join(', '));

    allClickable.forEach((el, idx) => {
        const rect = el.getBoundingClientRect();

        // Skip invisible elements
        if (rect.width <= 0 || rect.height <= 0) return;
        if (rect.bottom < 0 || rect.top > window.innerHeight) return;
        if (rect.right < 0 || rect.left > window.innerWidth) return;

        // Get computed style to check visibility
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return;
        if (parseFloat(style.opacity) < 0.1) return;

        // Extract useful attributes
        const text = (el.innerText || el.value || el.placeholder || el.title || el.alt || '').trim().slice(0, 100);
        const tag = el.tagName.toLowerCase();

        elements.push({
            index: idx,
            text: text,
            tag: tag,
            type: el.type || el.getAttribute('role') || tag,
            x: Math.round(rect.x + rect.width / 2),
            y: Math.round(rect.y + rect.height / 2),
            left: Math.round(rect.left),
            top: Math.round(rect.top),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            href: el.href || null,
            id: el.id || null,
            name: el.name || null,
            className: (el.className && typeof el.className === 'string') ? el.className.slice(0, 100) : null,
            ariaLabel: el.getAttribute('aria-label') || null,
            placeholder: el.placeholder || null,
            disabled: el.disabled || el.getAttribute('aria-disabled') === 'true' || false,
            checked: el.checked || el.getAttribute('aria-checked') === 'true' || false,
            value: el.value ? el.value.slice(0, 50) : null,
        });
    });

    // Sort by position (top to bottom, left to right)
    elements.sort((a, b) => {
        if (Math.abs(a.top - b.top) < 20) {
            return a.left - b.left;
        }
        return a.top - b.top;
    });

    // Re-index after sorting
    elements.forEach((el, idx) => el.index = idx);

    // Generate markdown-like page summary
    let markdown = '';

    // URL and title
    markdown += `URL: ${window.location.href}\\n`;
    const title = document.title;
    if (title) {
        markdown += `# ${title}\\n\\n`;
    }

    // Meta description
    const metaDesc = document.querySelector('meta[name="description"]');
    if (metaDesc && metaDesc.content) {
        markdown += `> ${metaDesc.content}\\n\\n`;
    }

    // Main headings (limit to first 10)
    const headings = document.querySelectorAll('h1, h2, h3');
    let headingCount = 0;
    headings.forEach(h => {
        if (headingCount >= 10) return;
        const level = parseInt(h.tagName[1]);
        const text = h.innerText.trim();
        if (text && text.length > 0 && text.length < 200) {
            markdown += `${'#'.repeat(level)} ${text}\\n\\n`;
            headingCount++;
        }
    });

    // Main content (simplified)
    const main = document.querySelector('main, article, [role="main"], .content, #content, .main');
    let contentText = '';
    if (main) {
        contentText = main.innerText.trim();
    } else {
        // Fallback to body text, excluding scripts/styles
        const body = document.body.cloneNode(true);
        body.querySelectorAll('script, style, noscript, svg, canvas').forEach(el => el.remove());
        contentText = body.innerText.trim();
    }

    // Truncate and clean up content
    contentText = contentText.replace(/\\s+/g, ' ').slice(0, 3000);
    if (contentText) {
        markdown += `## Page Content\\n\\n${contentText}\\n\\n`;
    }

    // List interactive elements summary
    markdown += `## Interactive Elements (${elements.length} total)\\n\\n`;

    // Group by type
    const byType = {};
    elements.forEach(el => {
        const type = el.type || el.tag;
        if (!byType[type]) byType[type] = [];
        byType[type].push(el);
    });

    // Show summary by type
    for (const [type, els] of Object.entries(byType)) {
        if (els.length > 0) {
            markdown += `### ${type} (${els.length})\\n`;
            els.slice(0, 10).forEach(el => {
                let desc = el.text || el.placeholder || el.ariaLabel || el.name || el.id || '(no label)';
                desc = desc.slice(0, 60);
                markdown += `- [${el.index}] "${desc}" at (${el.x}, ${el.y})\\n`;
            });
            if (els.length > 10) {
                markdown += `- ... and ${els.length - 10} more\\n`;
            }
            markdown += '\\n';
        }
    }

    return { elements, markdown, url: window.location.href, title: document.title };
}
"""

# Simpler script for just text extraction
TEXT_ONLY_SCRIPT = """
() => {
    const body = document.body.cloneNode(true);
    body.querySelectorAll('script, style, noscript, svg, canvas, iframe').forEach(el => el.remove());
    return body.innerText.trim();
}
"""

# Script for extracting links only
LINKS_SCRIPT = """
() => Array.from(document.querySelectorAll('a[href]')).map(a => {
    const rect = a.getBoundingClientRect();
    return {
        text: a.innerText.trim().slice(0, 100),
        href: a.href,
        x: Math.round(rect.x + rect.width / 2),
        y: Math.round(rect.y + rect.height / 2),
        visible: rect.width > 0 && rect.height > 0
    };
}).filter(l => l.visible)
"""

# Script for form fields
FORM_FIELDS_SCRIPT = """
() => Array.from(document.querySelectorAll('input, textarea, select')).map(el => {
    const rect = el.getBoundingClientRect();
    const label = document.querySelector(`label[for="${el.id}"]`);
    return {
        tag: el.tagName.toLowerCase(),
        type: el.type || 'text',
        name: el.name,
        id: el.id,
        value: el.value ? el.value.slice(0, 100) : '',
        placeholder: el.placeholder,
        label: label ? label.innerText.trim() : null,
        required: el.required,
        disabled: el.disabled,
        x: Math.round(rect.x + rect.width / 2),
        y: Math.round(rect.y + rect.height / 2),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        visible: rect.width > 0 && rect.height > 0
    };
}).filter(f => f.visible)
"""


async def extract_dom(page) -> Tuple[str, dict]:
    """
    Extract page content as markdown and element coordinates.

    Args:
        page: Playwright Page object

    Returns:
        Tuple of (markdown_string, coords_dict)
        - markdown: Human-readable page summary
        - coords: {"elements": [...]} with clickable element positions
    """
    try:
        result = await page.evaluate(EXTRACTION_SCRIPT)
        return result["markdown"], {"elements": result["elements"], "url": result.get("url"), "title": result.get("title")}
    except Exception as e:
        logger.warning(f"Error extracting DOM: {e}")
        return f"# Error extracting DOM\n\n{str(e)}", {"elements": [], "error": str(e)}


async def extract_text_only(page) -> str:
    """Extract just the text content of the page."""
    try:
        return await page.evaluate(TEXT_ONLY_SCRIPT)
    except Exception as e:
        logger.warning(f"Error extracting text: {e}")
        return f"Error: {str(e)}"


async def extract_links(page) -> List[Dict[str, Any]]:
    """Extract all visible links from the page."""
    try:
        return await page.evaluate(LINKS_SCRIPT)
    except Exception as e:
        logger.warning(f"Error extracting links: {e}")
        return []


async def extract_form_fields(page) -> List[Dict[str, Any]]:
    """Extract all form fields from the page."""
    try:
        return await page.evaluate(FORM_FIELDS_SCRIPT)
    except Exception as e:
        logger.warning(f"Error extracting form fields: {e}")
        return []


def find_element_at(coords: dict, x: int, y: int, tolerance: int = 20) -> dict | None:
    """
    Find the element closest to given coordinates.

    Args:
        coords: Coordinates dict from extract_dom
        x, y: Target coordinates
        tolerance: Maximum distance to consider a match

    Returns:
        Element dict or None if no match within tolerance
    """
    elements = coords.get("elements", [])
    if not elements:
        return None

    best_match = None
    best_distance = float("inf")

    for el in elements:
        # Calculate distance from center
        dx = el["x"] - x
        dy = el["y"] - y
        distance = (dx * dx + dy * dy) ** 0.5

        if distance < best_distance:
            best_distance = distance
            best_match = el

    if best_distance <= tolerance:
        return best_match

    return None


def find_element_by_text(
    coords: dict, text: str, partial: bool = True, case_sensitive: bool = False
) -> dict | None:
    """
    Find element by its text content.

    Args:
        coords: Coordinates dict from extract_dom
        text: Text to search for
        partial: If True, match partial text
        case_sensitive: If True, match case exactly

    Returns:
        First matching element or None
    """
    elements = coords.get("elements", [])
    if not elements:
        return None

    search_text = text if case_sensitive else text.lower()

    for el in elements:
        el_text = el.get("text", "")
        if not case_sensitive:
            el_text = el_text.lower()

        if partial:
            if search_text in el_text:
                return el
        else:
            if search_text == el_text:
                return el

    return None


def find_elements_by_type(coords: dict, element_type: str) -> List[dict]:
    """
    Find all elements of a given type.

    Args:
        coords: Coordinates dict from extract_dom
        element_type: Element type (button, input, link, etc.)

    Returns:
        List of matching elements
    """
    elements = coords.get("elements", [])
    type_lower = element_type.lower()

    return [
        el
        for el in elements
        if el.get("type", "").lower() == type_lower
        or el.get("tag", "").lower() == type_lower
    ]
