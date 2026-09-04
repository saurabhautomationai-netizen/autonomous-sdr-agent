import json
import httpx
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_MODEL


class UnsafeExtractionURL(ValueError):
    pass


def validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeExtractionURL("Only public HTTP(S) URLs are allowed")
    try:
        addresses = {
            item[4][0] for item in socket.getaddrinfo(
                parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except (socket.gaierror, OSError) as error:
        raise UnsafeExtractionURL("URL destination could not be validated") from error
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise UnsafeExtractionURL("Private or reserved destinations are not allowed")


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 AutonomousSDR/0.1"
    }

    current_url = url
    try:
        for _ in range(6):
            validate_public_url(current_url)
            response = httpx.get(
                current_url, headers=headers, timeout=15.0, follow_redirects=False,
            )
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise UnsafeExtractionURL("Redirect destination is missing")
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            return response.text
        raise UnsafeExtractionURL("Too many redirects")
    except UnsafeExtractionURL:
        raise
    except httpx.HTTPError as error:
        raise UnsafeExtractionURL("Unable to fetch the requested public URL") from error


def extract_lead_from_url(url: str) -> dict:
    html = fetch_html(url)

    lead = extract_lead(html)

    return {
        **lead,
        "source_url": url,
    }


def html_to_clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "noscript"]):
        element.decompose()

    text = soup.get_text(separator="\n", strip=True)

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    return "\n".join(lines)


def extract_lead_from_html(html: str) -> dict:
    """Deterministic extraction for known HTML structures."""

    soup = BeautifulSoup(html, "html.parser")

    name_element = soup.select_one(".name")
    title_element = soup.select_one(".title")
    company_element = soup.select_one(".company")

    return {
        "name": name_element.get_text(strip=True) if name_element else None,
        "title": title_element.get_text(strip=True) if title_element else None,
        "company": company_element.get_text(strip=True) if company_element else None,
    }


def extract_lead_with_llm(html: str) -> dict:
    """Extract lead information from unstructured HTML using an LLM."""

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=OPENAI_API_KEY)

    clean_text = html_to_clean_text(html)

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "You extract B2B lead information from webpage text. "
                    "Extract only information explicitly supported by the supplied text. "
                    "Do not invent missing information."
                ),
            },
            {
                "role": "user",
                "content": f"""
Extract the primary person's information from this webpage.

Return exactly these fields:
- name
- title
- company

Webpage text:

{clean_text}
""",
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "lead_extraction",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": ["string", "null"]},
                        "title": {"type": ["string", "null"]},
                        "company": {"type": ["string", "null"]},
                    },
                    "required": ["name", "title", "company"],
                    "additionalProperties": False,
                },
            }
        },
    )

    return json.loads(response.output_text)


def extract_lead(html: str) -> dict:
    """
    Extract lead data using deterministic parsing first.
    Fall back to the LLM when required fields are missing.
    """

    lead = extract_lead_from_html(html)

    required_fields = ("name", "title", "company")

    if all(lead.get(field) for field in required_fields):
        return {
            **lead,
            "extraction_method": "deterministic",
        }

    llm_lead = extract_lead_with_llm(html)

    return {
        **llm_lead,
        "extraction_method": "llm_fallback",
    }
