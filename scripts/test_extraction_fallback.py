from pathlib import Path

from app.services.lead_extractor import extract_lead


FIXTURES_DIR = Path("tests/fixtures")


def test_file(filename: str):
    path = FIXTURES_DIR / filename
    html = path.read_text(encoding="utf-8")

    result = extract_lead(html)

    print(f"\n{filename}")
    print("----------------------")
    print(result)


def main():
    # Should NOT use OpenAI
    test_file("lead_sample_1.html")

    # Should automatically use OpenAI
    test_file("lead_messy.html")


if __name__ == "__main__":
    main()