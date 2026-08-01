import asyncio
import os
import json
from typing import Optional
from pydantic import BaseModel, Field
from openai import AsyncAzureOpenAI
from core.db import DuckDBWorldModelStore
from core.models import Provenance, OriginType, Relationship


class ReasoningEngine:
    def __init__(self, db_store: DuckDBWorldModelStore):
        self.db = db_store
        self._running = False

        self.api_key = os.environ.get("AZURE_AI_API_KEY")
        self.endpoint = os.environ.get("AZURE_AI_ENDPOINT")
        self.deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        self.api_version = os.environ.get("AZURE_AI_API_VERSION", "2024-12-01-preview")

        if not all([self.api_key, self.endpoint, self.deployment]):
            print(
                "[Warning] Azure OpenAI environment variables missing. Reasoning engine will be limited."
            )
            self.client = None
        else:
            self.client = AsyncAzureOpenAI(
                azure_endpoint=self.endpoint,
                api_key=self.api_key,
                api_version=self.api_version,
            )

    async def run_reasoning_loop(self, interval_seconds: int = 300):
        self._running = True
        print("[ReasoningEngine] Started cognitive background loop (Azure).")
        await asyncio.sleep(5)

        while self._running:
            try:
                print("[ReasoningEngine] Waking up to analyze the World Model...")
                await self._align_tasks_to_goals()
                await self._detect_temporal_conflicts()
                print("[ReasoningEngine] Analysis complete. Going back to sleep.")
            except Exception as e:
                print(f"[ReasoningEngine] Error during reasoning cycle: {e}")

            await asyncio.sleep(interval_seconds)

    async def _align_tasks_to_goals(self):
        if not self.client:
            return

        loop = asyncio.get_running_loop()

        def _fetch_data():
            with self.db._get_connection() as conn:
                # 1. Fetch active goals
                goals = conn.execute(
                    "SELECT id, properties->>'$.name' as name, properties->>'$.description' as desc FROM entities WHERE type='Goal'"
                ).fetchall()

                # 2. Fetch orphan tasks
                tasks = conn.execute("""
                    SELECT e.id, e.properties->>'$.name' as name, e.properties->>'$.description' as desc 
                    FROM entities e
                    LEFT JOIN relationships r ON e.id = r.source_id AND r.type = 'SERVES_GOAL'
                    WHERE e.type = 'Task' AND r.source_id IS NULL
                    LIMIT 10
                """).fetchall()

                return goals, tasks

        goals_raw, tasks_raw = await loop.run_in_executor(None, _fetch_data)

        if not goals_raw or not tasks_raw:
            return

        goals_context = [{"id": g[0], "name": g[1], "desc": g[2]} for g in goals_raw]
        tasks = [{"id": t[0], "name": t[1], "desc": t[2]} for t in tasks_raw]

        print(
            f"[ReasoningEngine] Found {len(tasks)} orphan tasks. Attempting goal alignment..."
        )

        for task in tasks:
            prompt = f"""
            You are a cognitive reasoning engine.
            The user has the following Active Goals:
            {json.dumps(goals_context, indent=2)}
            
            The user just acquired this new Task:
            ID: {task['id']}
            Name: {task['name']}
            Description: {task.get('desc', 'N/A')}
            
            Does this task strongly serve any of the active goals? 
            Format your response as a JSON object with:
            - serves_goal_id: string (The ID of the Goal this task serves. Empty string if none.)
            - reasoning: string (One sentence explaining why this task serves the chosen goal.)
            """

            try:
                response = await self.client.chat.completions.create(
                    model=self.deployment,
                    messages=[
                        {"role": "system", "content": "You output JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )

                alignment_json = response.choices[0].message.content
                alignment = json.loads(alignment_json)

                serves_goal_id = alignment.get("serves_goal_id", "")
                reasoning = alignment.get("reasoning", "")

                if serves_goal_id:
                    prov = Provenance(
                        source_connector="ReasoningEngine",
                        source_item_id=task["id"],
                        origin_type=OriginType.INFERRED,
                    )
                    rel = Relationship(
                        target_entity_id=serves_goal_id,
                        relationship_type="SERVES_GOAL",
                        properties={"reasoning": reasoning},
                        provenance=prov,
                    )
                    await self.db.upsert_relationship(task["id"], rel)
                    print(
                        f"[ReasoningEngine] Aligned Task '{task['name']}' -> Goal '{serves_goal_id}'"
                    )

            except Exception as e:
                print(f"[ReasoningEngine] Error aligning task {task['id']}: {e}")

    async def _detect_temporal_conflicts(self):
        loop = asyncio.get_running_loop()

        def _detect():
            with self.db._get_connection() as conn:
                return conn.execute("""
                    SELECT t.id, t.properties->>'$.name' as task_name, 
                           e.id, e.properties->>'$.name' as event_name
                    FROM entities t
                    JOIN entities e ON (
                        COALESCE(t.valid_from, t.occurred_at) < COALESCE(e.valid_to, e.occurred_at, e.valid_from)
                        AND
                        COALESCE(t.valid_to, t.occurred_at, t.valid_from) > COALESCE(e.valid_from, e.occurred_at)
                        AND t.id < e.id
                    )
                    LEFT JOIN relationships r ON t.id = r.source_id AND e.id = r.target_id AND r.type = 'CONFLICTS_WITH'
                    WHERE t.type IN ('Task', 'Event', 'Meeting') 
                      AND e.type IN ('Task', 'Event', 'Meeting')
                      AND COALESCE(t.valid_from, t.occurred_at) IS NOT NULL
                      AND COALESCE(e.valid_from, e.occurred_at) IS NOT NULL
                      AND r.source_id IS NULL
                """).fetchall()

        try:
            conflicts = await loop.run_in_executor(None, _detect)
            for c in conflicts:
                t_id, t_name, e_id, e_name = c
                prov = Provenance(
                    source_connector="ReasoningEngine",
                    source_item_id=t_id,
                    origin_type=OriginType.INFERRED,
                )
                rel = Relationship(
                    target_entity_id=e_id,
                    relationship_type="CONFLICTS_WITH",
                    properties={"reason": "Scheduling overlap detected"},
                    provenance=prov,
                )
                await self.db.upsert_relationship(t_id, rel)
                print(
                    f"[ReasoningEngine] Detected Conflict: Task '{t_name}' overlaps with Event '{e_name}'"
                )
        except Exception as e:
            print(f"[ReasoningEngine] Error detecting conflicts: {e}")

    def stop(self):
        self._running = False
