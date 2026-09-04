from pathlib import Path

from app.services.lead_extractor import extract_lead_from_html


FIXTURES_DIR = Path("tests/fixtures")


def main():
    files = [
        "lead_sample_1.html",
        "lead_sample_2.html",
        "lead_sample_3.html",
    ]

    for filename in files:
        path = FIXTURES_DIR / filename
        html = path.read_text(encoding="utf-8")

        lead = extract_lead_from_html(html)

        print(f"\n{filename}")
        print(lead)


if __name__ == "__main__":
    main()