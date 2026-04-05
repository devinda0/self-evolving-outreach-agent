"""UI frame models — typed WebSocket payloads for in-thread ephemeral components."""

from typing import Literal, Optional

from pydantic import BaseModel


class UIAction(BaseModel):
    id: str
    label: str
    action_type: str
    payload: dict


class UIFrame(BaseModel):
    type: Literal["ui_component", "text", "progress", "error"]
    component: Optional[str] = None
    instance_id: str
    props: dict
    actions: list[UIAction]
