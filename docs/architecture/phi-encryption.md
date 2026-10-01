# PHI Encryption Architecture

All Protected Health Information (PHI) is encrypted at rest using AES-256-GCM
as required under HIPAA §164.312(a)(2)(iv).

## Encryption Flow

```mermaid
flowchart LR
    subgraph Input["Plaintext PHI (in-memory only)"]
        N[Patient Name\ne.g. 'Maria Garcia']
        P[Phone Number\ne.g. '+17875550101']
    end

    subgraph Process["encryption.py — AES-256-GCM"]
        K[PHI_ENCRYPTION_KEY\n32-byte base64 env var]
        IV[Random IV\n12 bytes per operation]
        ENC[encrypt_phi\nIV + ciphertext + auth_tag]
        HASH[SHA-256 hash\nof normalized phone]
    end

    subgraph Storage["PostgreSQL — BYTEA columns"]
        NE[patient_name_encrypted\nBYTEA]
        PE[phone_encrypted\nBYTEA]
        PH[phone_hash\nSHA-256 hex string]
    end

    subgraph Display["API Response"]
        ND[Decrypted name\nreport only]
        PM[Masked phone\n***-***-1234]
    end

    N --> ENC
    P --> ENC
    P --> HASH
    K --> ENC
    IV --> ENC
    ENC --> NE
    ENC --> PE
    HASH --> PH
    NE -->|decrypt_phi on read| ND
    PH -->|last 4 chars| PM
```

## Storage Format

```
Encrypted bytes layout:
┌──────────────────────────────────────────────────┐
│  IV (12 bytes)  │  Ciphertext (N bytes)  │  Tag (16 bytes)  │
└──────────────────────────────────────────────────┘

Key: AESGCM(PHI_ENCRYPTION_KEY, nonce=IV)
Tag: GCM authentication tag — tamper-evident
```

## What Is Never Stored in Plaintext

| PHI Field | Storage | Notes |
|-----------|---------|-------|
| Patient name | AES-256-GCM BYTEA | Decrypted only for report display |
| Phone number | AES-256-GCM BYTEA | Masked in all API responses |
| Phone hash | SHA-256 hex | Used for dedup only, not reversible |
| Call transcripts | Never stored | Discarded after call ends |
| Patient DOB | Never stored | Passed to Retell as call metadata only |

## Implementation

- `Clinic_app/common/encryption.py` — `encrypt_phi()` / `decrypt_phi()`
- `cryptography` library — FIPS 140-2 compliant
- Key loading: base64-encoded 32-byte key from `PHI_ENCRYPTION_KEY` env var
- Auth tag verification on every decrypt — raises `AuthenticationError` on tamper
- Logs: phone numbers masked as `***-***-XXXX`, never logged in plaintext
