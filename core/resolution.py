import asyncio
from core.db import DuckDBWorldModelStore, ChromaVectorStore


class EntityResolutionEngine:
    def __init__(
        self, db_store: DuckDBWorldModelStore, vector_store: ChromaVectorStore
    ):
        self.db = db_store
        self.vector_store = vector_store
        self._running = False

    async def run_resolution_loop(self, interval_seconds: int = 3600):
        self._running = True
        print("[ResolutionEngine] Started background entity resolution loop (DuckDB).")
        while self._running:
            try:
                await self._deduplicate_people()
            except Exception as e:
                print(f"[ResolutionEngine] Error during resolution: {e}")

            await asyncio.sleep(interval_seconds)

    async def _deduplicate_people(self):
        """Finds People with exact matching names but different IDs."""
        loop = asyncio.get_running_loop()

        def _find_duplicates():
            with self.db._get_connection() as conn:
                query = """
                SELECT p1.properties->>'$.name' as name, p1.id as keep_id, p2.id as merge_id
                FROM entities p1
                JOIN entities p2 ON (p1.properties->>'$.name') = (p2.properties->>'$.name')
                WHERE p1.type = 'Person' AND p2.type = 'Person'
                  AND p1.status != 'Merged' AND p2.status != 'Merged'
                  AND p1.id < p2.id
                """
                return conn.execute(query).fetchall()

        try:
            records = await loop.run_in_executor(None, _find_duplicates)

            if records:
                print(
                    f"[ResolutionEngine] Found {len(records)} duplicate Person entities. Executing Merge..."
                )
                for record in records:
                    name, keep_id, merge_id = record[0], record[1], record[2]
                    print(f"  - Merging: '{name}' ({merge_id} -> {keep_id})")
                    await self.db.merge_entities(keep_id, merge_id)

        except Exception as e:
            print(f"[ResolutionEngine] Query error: {e}")

    def stop(self):
        self._running = False
