"""Supabase client wrapper.

Service-role key, SERVER-SIDE ONLY (it bypasses RLS). Reads creds from env.
Never import this into anything that ships the anon key to a client.
"""
from __future__ import annotations

import os
from functools import lru_cache

from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set (see .env.example)"
        )
    return create_client(url, key)
