"""
智能体对话：文本入、文本出（Coze stream_run）。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.coze_agent_service import run_coze_agent_chat

router = APIRouter(prefix="/agent", tags=["智能体对话"])


class AgentChatRequest(BaseModel):
    text: str = Field(..., min_length=1, description="用户输入文本")


class AgentChatResponse(BaseModel):
    text: str = Field(..., description="智能体回复文本")


@router.post(
    "/chat",
    summary="智能体对话",
    response_model=AgentChatResponse,
)
async def agent_chat(body: AgentChatRequest) -> AgentChatResponse:
    result = run_coze_agent_chat(body.text)
    if result.get("success"):
        return AgentChatResponse(text=result["text"])
    raise HTTPException(
        status_code=502,
        detail=result.get("error", "智能体调用失败"),
    )
