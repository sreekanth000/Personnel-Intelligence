import asyncio
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileDeletedEvent, FileMovedEvent
from core.models import PipelineEvent, EventType
from core.pipeline import EventBus

class LocalFSEventHandler(FileSystemEventHandler):
    def __init__(self, bus: EventBus, loop: asyncio.AbstractEventLoop):
        self.bus = bus
        self.loop = loop
        super().__init__()

    def _publish_event(self, path: str, event_type: EventType, metadata: dict = None):
        if metadata is None:
            metadata = {}
        
        # Determine basic properties
        try:
            p = Path(path)
            if p.exists() and p.is_file():
                metadata["size"] = p.stat().st_size
                metadata["extension"] = p.suffix
        except Exception:
            pass

        event = PipelineEvent(
            source="Local_FS",
            event_type=event_type,
            raw_data={"path": path},
            metadata=metadata
        )
        # Use run_coroutine_threadsafe to publish from the watchdog thread to the asyncio loop
        asyncio.run_coroutine_threadsafe(self.bus.publish("local_fs_events", event), self.loop)

    def on_created(self, event):
        if not event.is_directory:
            self._publish_event(event.src_path, EventType.CREATED)

    def on_modified(self, event):
        if not event.is_directory:
            self._publish_event(event.src_path, EventType.MODIFIED)

    def on_deleted(self, event):
        if not event.is_directory:
            self._publish_event(event.src_path, EventType.DELETED)

    def on_moved(self, event):
        if not event.is_directory:
            self._publish_event(event.src_path, EventType.DELETED)
            self._publish_event(event.dest_path, EventType.CREATED, metadata={"moved_from": event.src_path})

class LocalFSWatcher:
    def __init__(self, bus: EventBus, directories: list[str]):
        self.bus = bus
        self.directories = directories
        self.observer = Observer()
        # We need the running event loop to dispatch events from watchdog's threads
        self.loop = asyncio.get_running_loop()

    def start(self):
        handler = LocalFSEventHandler(self.bus, self.loop)
        for directory in self.directories:
            path = Path(directory)
            if path.exists() and path.is_dir():
                self.observer.schedule(handler, str(path), recursive=True)
                print(f"[LocalFS] Started watching: {path}")
            else:
                print(f"[LocalFS] Warning: Directory {directory} does not exist. Skipping.")
        
        self.observer.start()

    def stop(self):
        self.observer.stop()
        self.observer.join()
        print("[LocalFS] Stopped watching directories.")
