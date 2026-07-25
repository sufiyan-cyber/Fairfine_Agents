"""Verify a Qdrant URL + API key before wiring them into the pipeline.

    python scripts/check_qdrant.py                      # reads backend/.env
    python scripts/check_qdrant.py <URL> <API_KEY>      # test a pair directly

Answers the three questions that actually matter:
  1. Do this URL and key authenticate at all?
  2. What is already in this cluster (so a shared cluster stays safe)?
  3. Which collections will FairFine create, and at what dimension?

Nothing here writes or deletes. It is a read-only probe.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    from app.config import settings

    if len(sys.argv) >= 3:
        url, api_key = sys.argv[1].strip().rstrip("/"), sys.argv[2].strip()
        source = "command line"
    else:
        url, api_key = settings.qdrant_url.strip().rstrip("/"), settings.qdrant_api_key.strip()
        source = "backend/.env"

    print("\n=== Qdrant connection check ===\n")

    if not url:
        print("  No QDRANT_URL set.")
        print("  Either add it to backend/.env, or pass it:")
        print("     python scripts/check_qdrant.py <URL> <API_KEY>\n")
        print("  FairFine runs fine without Qdrant — it falls back to a local")
        print("  in-process vector index. This check is only needed if you want")
        print("  the managed cluster in the loop.\n")
        return 1

    print(f"  Source     : {source}")
    print(f"  URL        : {url}")
    print(f"  API key    : {'set (' + str(len(api_key)) + ' chars)' if api_key else 'NOT SET'}")

    # --- shape checks that catch the usual copy-paste mistakes ------------- #
    problems = []
    if not url.startswith("https://"):
        problems.append("URL should start with https://")
    if ":6333" in url:
        problems.append("Drop the :6333 port — Qdrant Cloud serves REST on 443")
    if "/dashboard" in url or "/collections" in url:
        problems.append("Use the bare endpoint, with no path")
    if url.startswith("https://cloud.qdrant.io"):
        problems.append(
            "That is the Qdrant Cloud console URL, not your cluster endpoint. "
            "The endpoint looks like https://<uuid>.<region>.aws.cloud.qdrant.io"
        )
    if problems:
        print("\n  URL problems:")
        for problem in problems:
            print(f"    - {problem}")
        print()
        return 1

    # --- connect ----------------------------------------------------------- #
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=url, api_key=api_key or None, timeout=15)
        existing = [c.name for c in client.get_collections().collections]
    except Exception as exc:
        print(f"\n  FAILED: {type(exc).__name__}: {str(exc)[:400]}\n")
        print("  Common causes:")
        print("    - Using a Cloud Management Key instead of a Database API Key.")
        print("      Management keys administer clusters; they do not authenticate")
        print("      against cluster data. Get the database key from the cluster's")
        print("      own page: Clusters -> <your cluster> -> API Keys.")
        print("    - Key was scoped to a different cluster.")
        print("    - Cluster is suspended or still starting.\n")
        return 1

    print("\n  CONNECTED\n")

    # --- what is already there --------------------------------------------- #
    print(f"  Existing collections ({len(existing)}):")
    if existing:
        for name in sorted(existing):
            try:
                info = client.get_collection(name)
                size = info.config.params.vectors.size  # type: ignore[union-attr]
                count = info.points_count
                print(f"    - {name:<34} dim={size:<6} points={count}")
            except Exception:
                print(f"    - {name}")
    else:
        print("    (none)")

    # --- what FairFine will do --------------------------------------------- #
    from app.tools.memory import embed

    dim = len(embed("dimension probe"))
    prefix = settings.qdrant_collection
    planned = [f"{prefix}_rules_d{dim}", f"{prefix}_events_d{dim}"]

    print(f"\n  FairFine will use (embedding dim {dim}, "
          f"{'Gemini' if settings.live_llm else 'local fallback'}):")
    for name in planned:
        state = "exists, will reuse" if name in existing else "will be created"
        print(f"    - {name:<34} {state}")

    collisions = [c for c in existing if c.startswith(f"{prefix}_") and c not in planned]
    if collisions:
        print(f"\n  Note: other '{prefix}_' collections are present:")
        for name in collisions:
            print(f"    - {name}")
        print("  These are left untouched. Set QDRANT_COLLECTION to something else")
        print("  if they belong to another project and you want clean separation.")

    if not settings.live_llm:
        print("\n  Heads-up: no GEMINI_API_KEY, so embeddings are 256-d local vectors.")
        print("  Adding a Gemini key later switches to 3072-d and creates a second")
        print("  pair of collections. Set both keys together to avoid the leftovers.")

    print("\n  FairFine never deletes or drops collections — only creates and")
    print("  upserts its own. Sharing this cluster with another project is safe.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
