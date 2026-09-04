from pathlib import Path

from app.services.lead_extractor import html_to_clean_text


def main():
    path = Path("tests/fixtures/lead_messy.html")

    html = path.read_text(encoding="utf-8")

    clean_text = html_to_clean_text(html)

    print("\nCleaned HTML text:")
    print("------------------")
    print(clean_text)


if __name__ == "__main__":
    main()