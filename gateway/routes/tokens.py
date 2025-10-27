from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from services.database import get_db, Base, engine
from models.schemas import TokenizeRequest, TokenizeResponse, HydrateRequest, HydrateResponse
from services.tokens import tokenize_text, hydrate_text

router = APIRouter(prefix="/tokens", tags=["phi-proxy"])

@router.post("/tokenize", response_model=TokenizeResponse)
def post_tokenize(req: TokenizeRequest, db: Session = Depends(get_db)):
    text_tok, tokens, residual = tokenize_text(db, req.call_id, req.text)
    if req.mode == "strict" and residual:
        # Azure Mode: fail-closed on residual PHI
        raise HTTPException(status_code=422, detail="Residual PHI detected after tokenization")
    return TokenizeResponse(
        text_tokenized=text_tok,
        tokens=tokens,
        safety={"residual_phi": residual}
    )

@router.post("/hydrate", response_model=HydrateResponse)
def post_hydrate(req: HydrateRequest, db: Session = Depends(get_db)):
    hydrated, missing = hydrate_text(db, req.text_tokenized)
    return HydrateResponse(text_hydrated=hydrated, missing_tokens=missing)
