# Northbridge synthetic patient database

Fictional training data only. Not for real patient care.

## Files

- `patients.json`: native JSON array of 100 patient items.
- `patients.jsonl`: one native JSON patient item per line.
- `dynamodb_batches/batch_01.json` through `batch_04.json`: DynamoDB AttributeValue request payloads, 25 items each.
- `case_manifest.json`: scenario tags and expected review status kept outside patient items.
- `validation_summary.json`: counts and validation result.
- `load_patients.py`: optional boto3 loader using `Table.batch_writer()`.

## Table

Table name: `Patients`; partition key: `patient_id` (String).

## Load

Set `AWS_PROFILE`/AWS SSO credentials and `AWS_REGION`, then run:

```bash
python load_patients.py --file patients.json --table Patients --dry-run
python load_patients.py --file patients.json --table Patients
```

The loader refuses non-empty target tables unless `--allow-nonempty` is supplied.

## Safety/evaluation design

Records P1001-P1055 are mostly coherent histories. P1056-P1100 include defined uncertainty, conflict, stale-data, allergy, monitoring, procedure, urgent, emergency-proxy, and inactive-record cases. Use `case_manifest.json` for expected behavior; do not ingest that manifest into the patient table.

## Schema limitation

The supplied patient schema contains `prescriber` but no signed-order ID, signature/authorization timestamp, authorization state, full food/formulation directions, missed-dose instruction, or review/stop authorization. Therefore this dataset alone cannot prove `FINAL_AUTHORIZED`. Add a separate authorized-order source or extend the schema before allowing the application to label a recommendation final.
