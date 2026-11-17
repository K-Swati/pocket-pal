import os

os.environ.setdefault("POCKETPAL_NO_APP", "1")   # tests build their own app with an in-memory database
os.environ.setdefault("PBKDF2_ITERATIONS", "1000")  # fast hashing in tests; production uses 600k
