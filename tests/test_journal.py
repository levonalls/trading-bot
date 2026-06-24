import tempfile
from pathlib import Path

from trading_bot.journal.journal import Journal, JournalEntry


def test_journal_log_and_read():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "journal.db"
        journal = Journal(db_path)
        journal.log(JournalEntry("2024-01-01", "trend_following", "BTC/USDT", {"sharpe": 1.2}, "good run"))

        entries = journal.entries_for("2024-01-01")
        assert len(entries) == 1
        assert entries[0]["strategy"] == "trend_following"
        assert entries[0]["metrics"]["sharpe"] == 1.2

        markdown = journal.to_markdown("2024-01-01")
        assert "trend_following" in markdown
