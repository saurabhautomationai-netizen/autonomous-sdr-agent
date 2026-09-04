from pathlib import Path

from app.services.lead_extractor import extract_lead_with_llm


def main():
    path = Path("tests/fixtures/lead_messy.html")

    html = path.read_text(encoding="utf-8")

    lead = extract_lead_with_llm(html)

    print("\nLLM extraction result:")
    print("----------------------")
    print(lead)


if __name__ == "__main__":
    main()