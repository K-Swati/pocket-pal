"""python -m pocketpal                     run the server
python -m pocketpal create-superadmin   create a super admin account (prompts for details)"""

import getpass
import os
import sys

import uvicorn


def create_superadmin() -> None:
    os.environ["POCKETPAL_NO_APP"] = "1"
    from pocketpal.auth import create_staff, password_problem
    from pocketpal.db import DB

    db = DB()
    email = input("Email: ").strip()
    name = input("Name: ").strip() or "Super admin"
    while True:
        password = getpass.getpass("Password (10+ chars, upper/lower case and a number): ")
        problem = password_problem(password)
        if problem:
            print(problem)
            continue
        if getpass.getpass("Repeat password: ") != password:
            print("Passwords don't match.")
            continue
        break
    if db.one("SELECT 1 AS x FROM staff WHERE email = ?", (email,)):
        sys.exit("Someone with that email already exists.")
    create_staff(db, email, name, "super_admin", password)
    db.audit(None, "staff.bootstrap", email, {"role": "super_admin", "via": "cli"})
    print(f"Created super admin {email}. Sign in at /admin")


if __name__ == "__main__":
    if sys.argv[1:] == ["create-superadmin"]:
        create_superadmin()
    else:
        uvicorn.run("pocketpal.api:app", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
