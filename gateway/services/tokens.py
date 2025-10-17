import re
import logging
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func

from .crypto import (
    make_hmac_token, make_ulid_token,
    normalize_phone, normalize_email, normalize_generic,
    encrypt_str, decrypt_str
)
from models.models import Mapping

PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Super simple "name" heuristic for demo (capitalized words). Replace later with better NER.
NAME_RE  = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")

def tokenize_text(db: Session, call_id: str, text: str) -> Tuple[str, List[str], bool]:
    tokens: List[str] = []
    residual_phi = False
    token_map: Dict[str, str] = {}

    # Phones (deterministic)
    for m in set(PHONE_RE.findall(text)):
        norm = normalize_phone(m)
        token = make_hmac_token("PHONE", norm)
        text = text.replace(m, token)
        token_map[token] = norm

    # Emails (deterministic)
    for m in set(EMAIL_RE.findall(text)):
        norm = normalize_email(m)
        token = make_hmac_token("EMAIL", norm)
        text = text.replace(m, token)
        token_map[token] = norm

    # Names (one-off): use ULID token
    for m in set(NAME_RE.findall(text)):
        norm = normalize_generic(m)
        token = make_ulid_token("PATIENT")
        text = text.replace(m, token)
        token_map[token] = norm

    # Store encrypted mappings using upsert pattern
    if token_map:
        # Prepare batch insert data
        insert_data = []
        for token, value in token_map.items():
            nonce, ct = encrypt_str(value)
            insert_data.append({
                'token': token,
                'value_nonce': nonce,
                'value_ciphertext': ct,
                'value_type': token.split("_", 1)[0],
                'call_id': call_id
            })
            tokens.append(token)
        
        # Batch upsert: insert new tokens or update last_used_at for existing ones
        stmt = insert(Mapping).values(insert_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=['token'],
            set_={
                'last_used_at': func.now()
                # Note: We DO NOT update call_id to preserve original for audit trail
                # Note: We DO NOT update encrypted values (they should be identical anyway)
            }
        )
        db.execute(stmt)
        db.commit()

    # Basic residual check: if we still find phones/emails/names ? residual true
    if PHONE_RE.search(text) or EMAIL_RE.search(text) or NAME_RE.search(text):
        residual_phi = True

    return text, tokens, residual_phi

def hydrate_text(db: Session, text_tokenized: str) -> Tuple[str, List[str]]:
    """Replace tokens with original values from DB; returns hydrated text and missing list."""
    missing: List[str] = []
    # Find tokens by pattern KIND_HEX… (we use 6+ uppercase hex chars)
    token_candidates = set(re.findall(r"\b([A-Z]+_[A-F0-9]{6,})\b", text_tokenized))
    if not token_candidates:
        return text_tokenized, missing

    mappings = {m.token: m for m in db.query(Mapping).filter(Mapping.token.in_(list(token_candidates))).all()}

    result = text_tokenized
    for tok in token_candidates:
        m = mappings.get(tok)
        if not m:
            missing.append(tok)
            continue
        try:
            original = decrypt_str(m.value_nonce, m.value_ciphertext)
            result = result.replace(tok, original)
        except Exception as e:
            logging.warning(f"Failed to decrypt token {tok}: {e}")  # ADD LOGGING
            missing.append(tok)

    return result, missing
