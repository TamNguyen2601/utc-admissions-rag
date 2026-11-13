"""Create missing registered tables only. Run while the backend is stopped."""

from app.core.config import ConfigurationError, get_settings
from app.db.session import Database


def main() -> int:
    database = None
    try:
        database = Database(get_settings())
        database.initialize()
    except ConfigurationError:
        print("Invalid backend configuration; check environment settings.")
        return 1
    except Exception:
        print("Database initialization failed; check local database configuration.")
        return 1
    finally:
        if database is not None:
            database.dispose()
    print("Database initialized; existing data preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
