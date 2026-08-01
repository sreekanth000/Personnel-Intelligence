import os
import duckdb
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
import json

app = FastAPI(title="Cognitive Brain API")

# Allow the React frontend to make requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Since it's local
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "world_model.duckdb")

def query_db(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    # Open connection in read_only mode to avoid locking issues with main.py
    try:
        with duckdb.connect(DB_PATH, read_only=True) as conn:
            # Return results as list of dicts
            result = conn.execute(query, params).df().to_dict(orient="records")
            return result
    except Exception as e:
        print(f"Error querying DuckDB: {e}")
        return []

@app.get("/api/graph")
async def get_graph():
    """Returns nodes and edges formatted for react-force-graph-2d"""
    entities = query_db("SELECT id, type, properties, source, confidence FROM entities")
    relationships = query_db("SELECT source_id, target_id, type, properties, confidence FROM relationships")
    
    nodes = []
    for e in entities:
        props = json.loads(e['properties']) if isinstance(e['properties'], str) else e['properties']
        nodes.append({
            "id": e['id'],
            "name": props.get('name') or props.get('subject') or props.get('title') or e['id'],
            "group": e['type'],
            "val": 1.5 if e['type'] == 'Email' else 1,
            "properties": props
        })
        
    links = []
    for r in relationships:
        links.append({
            "source": r['source_id'],
            "target": r['target_id'],
            "label": r['type']
        })
        
    return {"nodes": nodes, "links": links}

@app.get("/api/stats")
async def get_stats():
    entities = query_db("SELECT type, COUNT(*) as count FROM entities GROUP BY type")
    rels = query_db("SELECT COUNT(*) as count FROM relationships")
    
    stats = {}
    for e in entities:
        stats[e['type']] = e['count']
        
    total_rels = rels[0]['count'] if rels else 0
    stats['Relationships'] = total_rels
    
    return stats
