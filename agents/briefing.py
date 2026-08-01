import asyncio
import json
from agents.base import BaseAgent

class BriefingAgent(BaseAgent):
    def __init__(self, db_store, vector_store):
        super().__init__(db_store, vector_store)
        self._running = False
        # In base.py we called it self.neo4j, but for this class let's access it directly or rename in base
        self.db = db_store 

    async def run(self, interval_seconds: int = 3600):
        self._running = True
        print("[BriefingAgent] Initialized. Waiting to generate daily briefing...")
        await asyncio.sleep(15)
        
        while self._running:
            try:
                await self._generate_briefing()
            except Exception as e:
                print(f"[BriefingAgent] Error generating briefing: {e}")
            
            await asyncio.sleep(interval_seconds)

    async def _generate_briefing(self):
        if not self.llm:
            return
            
        print("[BriefingAgent] Fetching recent context from World Model (DuckDB)...")
        
        loop = asyncio.get_running_loop()
        
        def _fetch_context():
            with self.db._get_connection() as conn:
                tasks = conn.execute("SELECT properties->>'$.name' as name, properties->>'$.status' as status FROM entities WHERE type='Task' LIMIT 5").fetchall()
                events = conn.execute("SELECT properties->>'$.title' as title, properties->>'$.date' as date FROM entities WHERE type='Event' LIMIT 5").fetchall()
                conflicts = conn.execute("""
                    SELECT a.type as type_a, a.properties->>'$.name' as name_a,
                           b.type as type_b, b.properties->>'$.name' as name_b,
                           c.properties->>'$.reason' as reason
                    FROM relationships c
                    JOIN entities a ON c.source_id = a.id
                    JOIN entities b ON c.target_id = b.id
                    WHERE c.type = 'CONFLICTS_WITH'
                    LIMIT 5
                """).fetchall()
                return tasks, events, conflicts
                
        try:
            tasks_raw, events_raw, conflicts_raw = await loop.run_in_executor(None, _fetch_context)
            
            if not tasks_raw and not events_raw:
                print("[BriefingAgent] World Model is empty. Skipping briefing.")
                return

            context = {
                "upcoming_events": [{"title": e[0], "date": e[1]} for e in events_raw],
                "open_tasks": [{"name": t[0], "status": t[1]} for t in tasks_raw],
                "detected_conflicts": [{"type_a": c[0], "name_a": c[1], "type_b": c[2], "name_b": c[3], "reason": c[4]} for c in conflicts_raw]
            }

            prompt = f"""
            You are the User's proactive Briefing Agent. 
            You have read-only access to their Personal World Model.
            
            Here is a snapshot of their current context:
            {json.dumps(context, indent=2)}
            
            Write a short, punchy "Morning Briefing" addressed to the user.
            - Highlight any temporal conflicts they need to resolve immediately.
            - Summarize the top tasks for the day.
            - Be concise, professional, but slightly conversational.
            - DO NOT use markdown formatting, just plain text.
            """
            
            async def call_azure():
                response = await self.llm.chat.completions.create(
                    model=self.deployment,
                    messages=[
                        {"role": "system", "content": "You are a highly efficient personal assistant. Output only the briefing without formatting."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7
                )
                return response.choices[0].message.content

            briefing_text = await call_azure()
            
            print("\n==================================================")
            print("  🌤️  MORNING BRIEFING FROM COGNITIVE BRAIN (Azure)")
            print("==================================================")
            print(briefing_text.strip())
            print("==================================================\n")
            
        except Exception as e:
            print(f"[BriefingAgent] Error: {e}")

    def stop(self):
        self._running = False
