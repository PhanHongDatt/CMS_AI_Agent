"""Quick-start: run Telegram bot in polling mode (development)."""

from dotenv import load_dotenv

load_dotenv()

from bot.app import main  # noqa: E402

if __name__ == "__main__":
    main()
