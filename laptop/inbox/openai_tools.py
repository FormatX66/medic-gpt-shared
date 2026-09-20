from __future__ import annotations

import json
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from openai import OpenAI

from gtp_games.assistant.models import AssistantReply
from gtp_games.config import Settings
from gtp_games.errors import ConfigurationError, GTPError
from gtp_games.models import Comparison, ValueType
from gtp_games.service import ApplicationService

TOOLS = [
    {
        "type": "function",
        "name": "list_game_processes",
        "description": "List running processes that can be attached for game value scanning. Call this first to find the game.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "attach_game_process",
        "description": "Attach to a game process by PID for read/scan only. Get the PID from list_game_processes.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "description": "Process ID from list_game_processes"},
                "game_name": {"type": ["string", "null"], "description": "Human-readable game name, e.g. 'No Man's Sky'"},
            },
            "required": ["pid"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "detach_game_process",
        "description": "Detach from the currently attached game process.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "start_value_scan",
        "description": "Start an exact scan for the player's current scalar value.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "value_type": {
                    "type": "string",
                    "enum": [item.value for item in ValueType],
                },
            },
            "required": ["value", "value_type"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "start_unknown_value_scan",
        "description": "Start a scan when the current value is unknown (e.g. a bar with no number). Refine with refine_value_scan as the value changes.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "value_type": {
                    "type": "string",
                    "enum": [item.value for item in ValueType],
                },
            },
            "required": ["value_type"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "refine_value_scan",
        "description": "Filter the active scan using the player's latest observation.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "comparison": {
                    "type": "string",
                    "enum": [item.value for item in Comparison],
                },
                "value": {"type": ["number", "null"]},
            },
            "required": ["comparison", "value"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "list_scan_candidates",
        "description": "List a sample of current candidates from the active scan.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": ["integer", "null"], "description": "Max candidates to return (default 20)"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
]


INSTRUCTIONS = """You are GTP Games, an assistant for local, personal, offline games.
Use only the supplied tools. Help the user narrow an ordinary scalar game value through an exact
scan followed by rescans. Default unknown integers to i32 and ask for the current value when it is
missing. Do not help with online games, anti-cheat, protected processes, DRM, code injection, or
executable-memory changes. This direct-API mode is read and scan only: you can list processes, attach to a game,
run exact and unknown-value scans, and refine them. Controlled writes are available only
through the MCP plugin and its native local confirmation dialog. Never invent an address,
session, scan result, or successful write.
"""



@dataclass
class OpenAIConversation:
    id: str
    session_id: str
    active_scan_id: str | None = None
    response_id: str | None = None


class OpenAIToolAssistant:
    def __init__(self, application: ApplicationService, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise ConfigurationError(
                "GTP_ASSISTANT_PROVIDER=openai requires OPENAI_API_KEY in the environment"
            )
        self.application = application
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
        self._conversations: dict[str, OpenAIConversation] = {}
        self._lock = RLock()

    def handle(
        self,
        session_id: str,
        message: str,
        conversation_id: str | None = None,
    ) -> AssistantReply:
        state = self._conversation(session_id, conversation_id)
        request: dict = {
            "model": self.settings.openai_model,
            "instructions": INSTRUCTIONS,
            "input": message,
            "tools": TOOLS,
            "parallel_tool_calls": False,
        }
        if state.response_id:
            request["previous_response_id"] = state.response_id
        response = self.client.responses.create(**request)
        actions: list[str] = []
        latest_data: dict = {}

        for _ in range(5):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                state.response_id = response.id
                return AssistantReply(
                    conversation_id=state.id,
                    message=response.output_text or "The assistant returned no text.",
                    active_scan_id=state.active_scan_id,
                    tool_actions=actions,
                    data=latest_data,
                )
            outputs = []
            for call in calls:
                try:
                    arguments = json.loads(call.arguments)
                    result = self._execute_tool(state, call.name, arguments)
                except (GTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    result = {"error": str(exc)}
                actions.append(call.name)
                latest_data = result
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(result),
                    }
                )
            response = self.client.responses.create(
                model=self.settings.openai_model,
                instructions=INSTRUCTIONS,
                previous_response_id=response.id,
                input=outputs,
                tools=TOOLS,
                parallel_tool_calls=False,
            )
        raise ConfigurationError("assistant exceeded the five-step tool-call limit")

    def _execute_tool(
        self,
        state: OpenAIConversation,
        name: str,
        arguments: dict,
    ) -> dict:
        if name == "list_game_processes":
            processes = self.application.list_processes()
            return {
                "processes": [
                    {
                        "pid": p.pid,
                        "name": p.name,
                        "likely_game": p.likely_game,
                        "attachable": p.attachable,
                        "blocked_reason": p.blocked_reason,
                    }
                    for p in processes
                    if p.likely_game or p.attachable
                ]
            }
        if name == "attach_game_process":
            session = self.application.attach(
                arguments["pid"],
                write_enabled=False,
                game_name=arguments.get("game_name"),
            )
            state.session_id = session.id
            return session.model_dump(mode="json")
        if name == "detach_game_process":
            self.application.detach(state.session_id)
            state.active_scan_id = None
            return {"detached": True, "session_id": state.session_id}
        if name == "start_value_scan":
            summary = self.application.start_scan(
                state.session_id,
                ValueType(arguments["value_type"]),
                arguments["value"],
            )
            state.active_scan_id = summary.id
            return summary.model_dump(mode="json")
        if name == "start_unknown_value_scan":
            summary = self.application.start_unknown_scan(
                state.session_id,
                ValueType(arguments["value_type"]),
            )
            state.active_scan_id = summary.id
            return summary.model_dump(mode="json")
        if name == "refine_value_scan":
            if state.active_scan_id is None:
                raise GTPError("no active scan; start a scan first")
            summary = self.application.rescan(
                state.active_scan_id,
                Comparison(arguments["comparison"]),
                arguments.get("value"),
            )
            return summary.model_dump(mode="json")
        if name == "list_scan_candidates":
            if state.active_scan_id is None:
                raise GTPError("no active scan; start a scan first")
            limit = arguments.get("limit") or 20
            return self.application.scan_summary(
                state.active_scan_id, limit=limit
            ).model_dump(mode="json")
        raise GTPError(f"unsupported assistant tool: {name}")

    def _conversation(
        self,
        session_id: str,
        conversation_id: str | None,
    ) -> OpenAIConversation:
        with self._lock:
            if conversation_id is not None and conversation_id in self._conversations:
                state = self._conversations[conversation_id]
                if state.session_id != session_id:
                    raise GTPError("conversation belongs to a different process session")
                return state
            state = OpenAIConversation(id=conversation_id or uuid4().hex, session_id=session_id)
            self._conversations[state.id] = state
            return state
