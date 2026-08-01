import os
import requests
import asyncio
from pathlib import Path

# Add the root project directory to sys.path so we can import from core
import sys
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from core.models import Entity, EntityType

def inject_local_fs():
    target_dir = r"C:\Users\Sreekanth\Desktop\Projects"
    
    count = 0
    print(f"Scanning {target_dir}...")
    for root, dirs, files in os.walk(target_dir):
        # Skip heavy directories to speed up metadata injection
        if 'node_modules' in dirs:
            dirs.remove('node_modules')
        if '.git' in dirs:
            dirs.remove('.git')
        if '__pycache__' in dirs:
            dirs.remove('__pycache__')
            
        for file in files:
            file_path = os.path.join(root, file)
            try:
                p = Path(file_path)
                size = p.stat().st_size if p.exists() else 0
                ext = p.suffix
            except Exception:
                size = 0
                ext = ""
            
            # Create a Document entity with just the available metadata
            entity = Entity(
                type=EntityType.DOCUMENT,
                source="Local_FS",
                properties={
                    "title": file,
                    "filepath": file_path,
                    "extension": ext,
                    "size": size
                }
            )
            
            payload = {
                "topic": "entities_to_build",
                "event": {
                    "source": "Local_FS_Parser",
                    "event_type": "CREATED",
                    "raw_data": {"base_entity": entity.model_dump(mode='json'), "extraction": {}},
                    "metadata": {}
                }
            }
            
            try:
                resp = requests.post("http://127.0.0.1:8000/publish", json=payload)
                if resp.status_code == 200:
                    count += 1
            except requests.exceptions.RequestException as e:
                print(f"Failed to connect to main.py. Is it running? Error: {e}")
                return
                
            if count % 1000 == 0 and count > 0:
                print(f"Queued {count} files for ingestion...")
                
    print(f"Finished sending {count} files from Local_FS to main.py.")

if __name__ == "__main__":
    inject_local_fs()
