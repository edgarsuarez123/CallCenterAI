from pydantic import BaseModel, Field

class TokenizeRequest(BaseModel):
    call_id: str = Field(..., min_length=3, max_length=64)
    text: str = Field(..., min_length=1)
    mode: str = Field("strict")  # future: "lenient" to bypass 422 on residual

class TokenizeResponse(BaseModel):
    text_tokenized: str
    tokens: list[str]
    safety: dict

class HydrateRequest(BaseModel):
    text_tokenized: str

class HydrateResponse(BaseModel):
    text_hydrated: str
    missing_tokens: list[str]
