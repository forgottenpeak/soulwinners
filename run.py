#!/usr/bin/env python3
"""
Hedgehog - Personal AI Agent
Entry point for running the agent
"""
import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def setup_test_db():
    """Create a test database with sample data"""
    import sqlite3
    from config import LOCAL_TEST_DB

    LOCAL_TEST_DB.parent.mkdir(exist_ok=True)

    conn = sqlite3.connect(LOCAL_TEST_DB)
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            id INTEGER PRIMARY KEY,
            address TEXT NOT NULL,
            balance REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            wallet_id INTEGER,
            amount REAL,
            type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (wallet_id) REFERENCES wallets(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Insert sample data
    cursor.execute("SELECT COUNT(*) FROM wallets")
    if cursor.fetchone()[0] == 0:
        sample_wallets = [
            ("0x1234...abcd", 1.5),
            ("0x5678...efgh", 2.3),
            ("0x9abc...ijkl", 0.8),
            ("0xdef0...mnop", 5.2),
            ("0x1111...qrst", 0.1),
        ]
        cursor.executemany(
            "INSERT INTO wallets (address, balance) VALUES (?, ?)",
            sample_wallets
        )

        sample_users = [
            ("alice", "alice@example.com"),
            ("bob", "bob@example.com"),
            ("charlie", "charlie@example.com"),
        ]
        cursor.executemany(
            "INSERT INTO users (username, email) VALUES (?, ?)",
            sample_users
        )

    conn.commit()
    conn.close()
    print(f"Test database created at: {LOCAL_TEST_DB}")


def run_cli():
    """Run in CLI mode"""
    from core.gateway import CLIGateway
    gateway = CLIGateway()
    gateway.run()


def run_telegram():
    """Run Telegram bot"""
    from core.gateway import TelegramGateway
    gateway = TelegramGateway()
    gateway.run()


def main():
    parser = argparse.ArgumentParser(
        description="Hedgehog - Personal AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --cli          Run in CLI mode (for testing)
  python run.py --cli --gpt-only   Run CLI without Claude routing
  python run.py --telegram     Run Telegram bot
  python run.py --setup-db     Create test database

Environment variables:
  TELEGRAM_BOT_TOKEN    Telegram bot token
  OPENAI_API_KEY        OpenAI API key (for GPT-4o-mini)
  ANTHROPIC_API_KEY     Anthropic API key (for Claude)
  HEDGEHOG_DB_PATH      Override database path
        """
    )

    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in CLI mode for testing"
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Run Telegram bot"
    )
    parser.add_argument(
        "--setup-db",
        action="store_true",
        help="Create test database with sample data"
    )
    parser.add_argument(
        "--gpt-only",
        action="store_true",
        help="Use only GPT-4o-mini, disable Claude routing"
    )

    args = parser.parse_args()

    # Set GPT-only mode before importing router
    if args.gpt_only:
        import os
        os.environ["HEDGEHOG_GPT_ONLY"] = "1"
        print("GPT-only mode enabled (Claude routing disabled)")

    if args.setup_db:
        setup_test_db()
        return

    if args.telegram:
        run_telegram()
    elif args.cli:
        run_cli()
    else:
        # Default to CLI mode
        print("No mode specified, running CLI mode.")
        print("Use --telegram for Telegram bot mode.")
        print("-" * 40)
        run_cli()


if __name__ == "__main__":
    main()
