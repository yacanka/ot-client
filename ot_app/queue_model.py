"""In-memory presentation state for document queue rows."""
from dataclasses import dataclass, field
from uuid import uuid4

from otClient import Document


@dataclass
class QueueRow:
    number: str
    key: str = field(default_factory=lambda: uuid4().hex)
    status: str = "pending"
    document: Document | None = None
    candidates: tuple = ()
    message: str = "İndirilmeye hazır."
    path: str = ""
    size: int | None = None
    chosen: bool = False
    parent_key: str | None = None
