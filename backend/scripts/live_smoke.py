import json
import os
from sqlalchemy import create_engine, text


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DATABASE_URL before running live_smoke.py")
    engine = create_engine(url, pool_pre_ping=True)
    expected = {"users", "customers", "staff", "addresses", "shipments", "shipment_status_history", "shipment_assignments", "hubs", "routes", "vehicles", "warehouse_scans", "delivery_otps", "proof_of_delivery", "invoices", "payments", "refunds", "cod_collections"}
    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("select table_name from information_schema.tables where table_schema='public'"))}
        missing = expected - tables
        counts = {name: conn.execute(text(f"select count(*) from {name}")).scalar_one() for name in sorted(expected)}
        obus = conn.execute(text("select tracking_id from shipments order by tracking_id limit 5")).scalars().all()
    result = {"database": "seneca_phase3", "tables_checked": len(expected), "missing_tables": sorted(missing), "counts": counts, "sample_tracking_ids": obus, "read_only": True}
    print(json.dumps(result, indent=2, default=str))
    if missing or not obus:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

