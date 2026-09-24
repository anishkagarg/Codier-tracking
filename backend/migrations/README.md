# OptiGo migration decision

No migration is supplied or applied. The live PostgreSQL database `seneca_phase3` was inspected directly and is the source of truth. The backend maps the existing text OBU identifiers and existing non-null constraints. Any future change to make task scheduling or OTP issuance nullable would require a separately approved database migration; it is intentionally not included here.
