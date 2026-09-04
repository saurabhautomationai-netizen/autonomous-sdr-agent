from sqlalchemy import text

from app.database import engine


def main():
    with engine.connect() as connection:
        result = connection.execute(text("select now();"))
        print("Database connected successfully.")
        print("Database time:", result.scalar())


if __name__ == "__main__":
    main()