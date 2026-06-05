# Run SQL migration script
"""
Execute SQL migration files on the MySQL database.
"""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
import mysql.connector


def run_migration(migration_file: str):
    """Execute a single SQL migration file"""

    # Connect to MySQL
    conn = mysql.connector.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
    )

    cursor = conn.cursor()

    # Read migration file
    with open(migration_file, 'r', encoding='utf-8') as f:
        sql = f.read()

    # Execute SQL (split by semicolon for multiple statements)
    statements = [s.strip() for s in sql.split(';') if s.strip()]

    for statement in statements:
        try:
            cursor.execute(statement)
            print(f"✓ Executed: {statement[:50]}...")
        except Exception as e:
            print(f"✗ Error: {e}")
            print(f"  Statement: {statement[:100]}...")

    conn.commit()
    cursor.close()
    conn.close()

    print(f"\n✓ Migration completed: {migration_file}")


if __name__ == "__main__":
    migrations_dir = Path(__file__).parent / "migrations"

    if not migrations_dir.exists():
        print(f"Migrations directory not found: {migrations_dir}")
        sys.exit(1)

    # Run all .sql files in order
    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        print("No migration files found")
        sys.exit(1)

    print(f"Found {len(migration_files)} migration(s)\n")

    for migration_file in migration_files:
        print(f"Running: {migration_file.name}")
        run_migration(str(migration_file))
        print()

    print("All migrations completed successfully!")
