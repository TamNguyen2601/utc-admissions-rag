"""Local interactive Admin creation; run while the backend is stopped."""

import getpass
import warnings

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import get_settings
from app.db.session import Database
from app.models.identity import Role
from app.schemas.auth import Credentials
from app.services.auth import register


def main() -> int:
    database = None
    try:
        email = input("Admin email: ")
        # Fail closed if the terminal cannot disable echo.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Admin password: ")
        credentials = Credentials(email=email, password=password)
        database = Database(get_settings())
        database.initialize()
        with database.session() as db:
            register(db, credentials, role=Role.ADMIN)
    except ValidationError:
        print("Invalid email or password (8–128 characters required).")
        return 1
    except HTTPException as error:
        print("Account already exists." if error.status_code == 409 else "Admin creation failed.")
        return 1
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print("Admin creation cancelled; a secure password prompt is required.")
        return 1
    except Exception:
        print("Admin creation failed; check local configuration.")
        return 1
    finally:
        if database is not None:
            database.dispose()
    print("Admin account created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
