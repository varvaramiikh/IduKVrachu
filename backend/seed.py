import asyncio

from backend.app.seed import seed_if_empty


if __name__ == "__main__":
    asyncio.run(seed_if_empty())
