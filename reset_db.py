import argparse
from sqlalchemy.engine import Engine

from db.models import Base, init_db


def reset_db(engine: Engine):
    print(f"Using database: {engine.url}")
    print("Dropping all tables...")
    Base.metadata.drop_all(engine)
    print("Creating all tables...")
    Base.metadata.create_all(engine)
    print("Done. Database schema has been reset.")


def main():
    parser = argparse.ArgumentParser(description="Reset database schema: drop all tables and recreate")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if not args.yes:
        confirm = input("This will DROP ALL TABLES and recreate them. Type 'yes' to continue: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return

    engine = init_db()
    reset_db(engine)


if __name__ == "__main__":
    main()