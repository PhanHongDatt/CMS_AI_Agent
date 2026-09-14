"""POST /llm/chat — hỏi-đáp qua LLMGateway (openai chính, gemini fallback,
retry + circuit breaker sẵn có trong core/llm/gateway.py). Dùng cho bot NL
Q&A — trước đây bot tự gọi thẳng GeminiProvider, không có fallback khi
Gemini quá tải (503 UNAVAILABLE) dù OpenAI vẫn khỏe.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_llm_gateway
from core.llm.base import LLMRequest
from core.llm.errors import LLMError
from core.llm.gateway import LLMGateway

router = APIRouter(prefix="/llm", tags=["llm"])


class ChatRequest(BaseModel):
    system_prompt: str
    user_message: str
    max_tokens: int = 800
    temperature: float = 0.3


class ChatResponse(BaseModel):
    content: str
    provider: str
    model: str


@router.post("/chat", response_model=ChatResponse)
async def llm_chat(body: ChatRequest, gateway: LLMGateway = Depends(get_llm_gateway)):
    try:
        resp = await gateway.complete(
            LLMRequest(
                task="default",
                system_prompt=body.system_prompt,
                user_message=body.user_message,
                max_tokens=body.max_tokens,
                temperature=body.temperature,
            )
        )
    except LLMError as e:
        return ChatResponse(content=f"(LLM lỗi: {e})", provider="none", model="none")
    return ChatResponse(content=resp.content, provider=resp.provider, model=resp.model)
