"""Convenience entrypoint for local runs.

Prefer `python -m bot.main`; this file exists so `python main.py` works too.
"""

import asyncio

from bot.main import main


if __name__ == "__main__":
    asyncio.run(main())
