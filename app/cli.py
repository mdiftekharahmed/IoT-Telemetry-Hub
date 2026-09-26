import argparse
import os
from getpass import getpass

from sqlalchemy import delete

from app.config import Settings
from app.db import build_engine, session_factory
from app.models import Admin, AdminSession, UserProfile
from app.schemas import Login
from app.security import password_hasher


def main():
    parser = argparse.ArgumentParser(description="Create an admin or reset an existing password")
    parser.add_argument("username")
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args()
    
    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        password = getpass("Admin password (at least 12 characters): ")
        if password != getpass("Confirm password: "):
            parser.error("Passwords do not match")
            
    if len(password) < 12 or len(password) > 1024:
        parser.error("Password must contain 12 to 1024 characters")
        
    login = Login(username=args.username, password=password)
    engine = build_engine(Settings().database_url)
    try:
        with session_factory(engine).begin() as db:
            admin = db.get(Admin, login.username)
            if admin and not args.reset_password:
                parser.error("Admin already exists; use --reset-password to change it")
            if admin:
                admin.password_hash = password_hasher.hash(password)
                db.execute(delete(AdminSession).where(AdminSession.username == login.username))
            else:
                db.add(Admin(username=login.username, password_hash=password_hasher.hash(password)))
                db.flush()
                db.add(UserProfile(username=login.username))
        print(f"Admin '{login.username}' saved.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
