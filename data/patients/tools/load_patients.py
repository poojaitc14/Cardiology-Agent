import argparse, json, os
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--file",default="patients.json")
    ap.add_argument("--table",default="Patients")
    ap.add_argument("--region",default=os.getenv("AWS_REGION","eu-west-2"))
    ap.add_argument("--dry-run",action="store_true")
    ap.add_argument("--allow-nonempty",action="store_true")
    args=ap.parse_args()
    patients=json.loads(Path(args.file).read_text())
    assert len(patients)==130 and len({p["patient_id"] for p in patients})==130
    if args.dry_run:
        print(f"Validated {len(patients)} items for {args.table} in {args.region}")
        return
    import boto3
    table=boto3.resource("dynamodb",region_name=args.region).Table(args.table)
    if not args.allow_nonempty and table.scan(Select="COUNT",Limit=1).get("Count",0):
        raise SystemExit("Target table is not empty; use --allow-nonempty only if overwrite/upsert is intended")
    with table.batch_writer(overwrite_by_pkeys=["patient_id"]) as batch:
        for patient in patients: batch.put_item(Item=patient)
    print(f"Loaded {len(patients)} items into {args.table}")

if __name__=="__main__": main()
