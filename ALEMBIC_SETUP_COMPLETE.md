# Alembic Migrations Setup - Complete

## What Was Implemented

### 1. Alembic Initialization ✅
- Created `alembic.ini` configuration file
- Created `alembic/env.py` with async SQLAlchemy support
- Created `alembic/script.py.mako` template
- Created `alembic/versions/` directory

### 2. Alembic Configuration ✅
**File: `Clinic_app/alembic/env.py`**
- Configured to import all models from `Clinic_app.data.models`
- Set up sync database URL (postgresql+psycopg2) for migrations
- Handles missing environment variables gracefully
- Falls back to offline mode if database connection fails
- Imports Base and all 10 models for autogenerate support

**File: `Clinic_app/alembic.ini`**
- Configured script location
- Database URL configured in env.py (from environment variables)

### 3. Database Module Updates ✅
**File: `Clinic_app/common/database.py`**
- Made engine creation conditional (only if env vars are set)
- Handles missing asyncpg gracefully (allows imports for migrations)
- AsyncSessionLocal created only if engine exists
- get_db() raises helpful error if engine not initialized

### 4. Initial Migration Created ✅
**File: `Clinic_app/alembic/versions/3f270d38367a_initial_models.py`**

**Includes:**
- ✅ All 10 tables: Clinic, License, ClinicIntegration, Provider, Patient, Booking, AvailabilitySlot, BookingAudit, PhoneRoute, CallLog
- ✅ 4 PostgreSQL ENUM types: BookingStatus, SlotStatus, SlotSource, BookingAction
- ✅ All primary key indexes
- ✅ All foreign key indexes
- ✅ All composite indexes (7 total)
- ✅ All unique constraints
- ✅ All CHECK constraints (3 total)
- ✅ Partial unique index on Booking (with WHERE clause)
- ✅ Proper CASCADE/RESTRICT delete actions
- ✅ UUID defaults using gen_random_uuid()
- ✅ Timestamp defaults using now()
- ✅ JSONB default for License.features

## Migration Details

### Tables Created (in dependency order):
1. **clinic** - Root tenant table
2. **license** - One-to-one with clinic
3. **clinic_integration** - One-to-one with clinic
4. **provider** - Depends on clinic
5. **patient** - Depends on clinic
6. **phone_route** - Depends on clinic
7. **availability_slot** - Depends on clinic, provider
8. **booking** - Depends on clinic, provider, patient
9. **booking_audit** - Depends on clinic, booking (RESTRICT delete)
10. **call_log** - No foreign keys (PHI-free)

### ENUM Types Created:
- `bookingstatus`: 'tentative', 'confirmed', 'canceled'
- `slotstatus`: 'free', 'booked', 'blocked'
- `slotsource`: 'csv', 'gcal'
- `bookingaction`: 'hold', 'confirm', 'cancel', 'expire'

### Key Constraints:
- **Partial Unique Index**: `idx_booking_unique_slot` on Booking (prevents double-booking)
- **CHECK Constraints**: 
  - Booking: `slot_end > slot_start`
  - AvailabilitySlot: `slot_end > slot_start`
  - CallLog: `call_type IN ('inbound', 'outbound_reminder', 'outbound_campaign')`
- **Unique Constraints**: 
  - Clinic.license_token
  - License.token
  - ClinicIntegration.clinic_id
  - AvailabilitySlot (provider_id, slot_start, slot_end)

## How to Use

### Generate New Migrations (when models change):
```bash
cd Clinic_app
alembic revision --autogenerate -m "Description of changes"
```

### Apply Migrations:
```bash
cd Clinic_app
alembic upgrade head
```

### Rollback Migration:
```bash
cd Clinic_app
alembic downgrade -1
```

### Check Current Migration:
```bash
cd Clinic_app
alembic current
```

### View Migration History:
```bash
cd Clinic_app
alembic history
```

## Environment Variables Required

For migrations to run, set these in `.env` or environment:
```bash
DB_HOST=your-postgres-host
DB_PORT=5432
DB_NAME=your-database-name
DB_USER=your-username
DB_PASSWORD=your-password
```

## Notes

1. **UUID Generation**: Uses `gen_random_uuid()` which is available in PostgreSQL 13+. For older versions, you may need to enable `pgcrypto` extension.

2. **Connection**: Migrations use sync connection (psycopg2), while application uses async (asyncpg).

3. **Autogenerate**: Requires database connection to compare current state. For initial migration, we created it manually.

4. **Model Imports**: All models are imported in `env.py` to enable autogenerate detection.

## Next Steps

1. **Test Migration**: Run `alembic upgrade head` on a dev database to verify all tables are created correctly
2. **Verify Constraints**: Test that all constraints work (double-booking prevention, CHECK constraints, etc.)
3. **Test Rollback**: Run `alembic downgrade -1` to verify rollback works
4. **Create Seed Data**: After migration is applied, create seed script for test data

## Verification Checklist

- [x] Alembic initialized
- [x] env.py configured with model imports
- [x] Initial migration created with all 10 tables
- [x] All ENUM types included
- [x] All indexes included
- [x] All constraints included
- [x] Partial unique index with WHERE clause included
- [ ] Migration tested on dev database (pending database connection)
- [ ] Rollback tested (pending database connection)

