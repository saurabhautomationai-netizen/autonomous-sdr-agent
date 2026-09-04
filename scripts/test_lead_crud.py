from sqlalchemy import text

from app.database import engine


def main():
    with engine.begin() as connection:

        # Create a test lead
        insert_query = text("""
            insert into leads (
                name,
                title,
                company,
                domain,
                email,
                email_confidence,
                source_url,
                status
            )
            values (
                :name,
                :title,
                :company,
                :domain,
                :email,
                :email_confidence,
                :source_url,
                :status
            )
            returning id, name, title, company, email, status;
        """)

        lead = connection.execute(
            insert_query,
            {
                "name": "Alex Morgan",
                "title": "VP of Sales",
                "company": "Acme AI",
                "domain": "example.com",
                "email": "alex.morgan@example.com",
                "email_confidence": 95.00,
                "source_url": "https://example.com",
                "status": "new",
            },
        ).mappings().one()

        print("\nLead created successfully:")
        print(dict(lead))

        # Read the lead back from PostgreSQL
        select_query = text("""
            select
                id,
                name,
                title,
                company,
                domain,
                email,
                email_confidence,
                status,
                created_at
            from leads
            where id = :lead_id;
        """)

        saved_lead = connection.execute(
            select_query,
            {"lead_id": lead["id"]},
        ).mappings().one()

        print("\nLead read successfully:")
        print(dict(saved_lead))


if __name__ == "__main__":
    main()