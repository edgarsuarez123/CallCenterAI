"""
PHI Tokenization API Routes

Provides endpoints for HIPAA-compliant PHI tokenization and hydration:
- Tokenize text by replacing PHI (phone numbers, emails, names) with encrypted tokens
- Hydrate tokenized text by replacing tokens with original PHI values

Critical for HIPAA compliance and PHI protection in call transcripts and logs.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from services.database import get_async_db
from models.schemas import TokenizeRequest, TokenizeResponse, HydrateRequest, HydrateResponse
from services.crypto import tokenize_text, hydrate_text
from services.structured_logging import get_logger, LogCategory
from services.exceptions import ValidationError

router = APIRouter(prefix="/tokens", tags=["phi-proxy"])
logger = get_logger("token_routes")

# Allowed tokenization modes
ALLOWED_MODES = {"strict", "lenient"}


@router.post("/tokenize", response_model=TokenizeResponse)
async def post_tokenize(
    req: TokenizeRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Tokenize text by replacing PHI (Protected Health Information) with encrypted tokens.
    
    This endpoint:
    - Detects and replaces phone numbers, emails, and names with tokens
    - Stores encrypted mappings in the database
    - Validates that all PHI was successfully tokenized (in strict mode)
    - Returns tokenized text, list of tokens, and safety information
    
    Args:
        req: TokenizeRequest containing call_id, text, and mode
        db: Database session
        
    Returns:
        TokenizeResponse with tokenized text, tokens list, and safety info
    """
    # Validate mode parameter
    if req.mode not in ALLOWED_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mode '{req.mode}'. Allowed modes: {', '.join(ALLOWED_MODES)}"
        )
    
    # Validate call_id format (basic check)
    if not req.call_id or len(req.call_id.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="call_id must be at least 3 characters"
        )
    
    # Validate text is not empty
    if not req.text or not req.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="text cannot be empty"
        )
    
    logger.info(
        f"Tokenizing text for call {req.call_id}",
        LogCategory.API,
        extra_data={
            "call_id": req.call_id,
            "mode": req.mode,
            "text_length": len(req.text)
        }
    )
    
    # Tokenize the text
    text_tok, tokens, residual = await tokenize_text(db, req.call_id, req.text)
    
    # Check for residual PHI in strict mode
    if req.mode == "strict" and residual:
        logger.warning(
            f"Residual PHI detected after tokenization for call {req.call_id}",
            LogCategory.SECURITY,
            extra_data={
                "call_id": req.call_id,
                "tokens_count": len(tokens),
                "residual_phi": True
            }
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Residual PHI detected after tokenization. Use 'lenient' mode to allow residual PHI."
        )
    
    logger.info(
        f"Text tokenized successfully for call {req.call_id}",
        LogCategory.API,
        extra_data={
            "call_id": req.call_id,
            "tokens_count": len(tokens),
            "residual_phi": residual,
            "mode": req.mode
        }
    )
    
    return TokenizeResponse(
        text_tokenized=text_tok,
        tokens=tokens,
        safety={"residual_phi": residual}
    )


@router.post("/hydrate", response_model=HydrateResponse)
async def post_hydrate(
    req: HydrateRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Hydrate tokenized text by replacing tokens with original PHI values.
    
    This endpoint:
    - Finds all tokens in the tokenized text
    - Retrieves encrypted mappings from the database
    - Replaces tokens with decrypted original values
    - Returns hydrated text and list of any missing tokens
    
    **Security Note**: This operation accesses PHI and is logged for audit purposes.
    
    Args:
        req: HydrateRequest containing tokenized text
        db: Database session
        
    Returns:
        HydrateResponse with hydrated text and missing tokens list
    """
    # Validate input
    if not req.text_tokenized or not req.text_tokenized.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="text_tokenized cannot be empty"
        )
    
    logger.info(
        "Hydrating tokenized text",
        LogCategory.AUDIT,
        extra_data={
            "text_length": len(req.text_tokenized),
            "operation": "phi_hydration"
        }
    )
    
    # Hydrate the text
    hydrated, missing = await hydrate_text(db, req.text_tokenized)
    
    # Log PHI access for audit trail
    logger.info(
        "Text hydrated successfully",
        LogCategory.AUDIT,
        extra_data={
            "missing_tokens_count": len(missing),
            "operation": "phi_hydration",
            "has_missing_tokens": len(missing) > 0
        }
    )
    
    # Log warning if tokens are missing
    if missing:
        logger.warning(
            f"Missing tokens during hydration: {len(missing)} tokens not found",
            LogCategory.SECURITY,
            extra_data={
                "missing_tokens_count": len(missing),
                "missing_tokens": missing[:10]  # Log first 10 to avoid log bloat
            }
        )
    
    return HydrateResponse(
        text_hydrated=hydrated,
        missing_tokens=missing
    )
