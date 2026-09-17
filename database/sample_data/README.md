# Synthetic data

`database.synthetic_data.generate_patients()` deterministically creates 100 synthetic patient partitions by default (`P1001` through `P1100`). Each partition contains one profile, condition, medication, allergy, lab result, vital-sign, and cardiology-test item. The generator is the source of sample data used by the operator-only seed command and tests; it contains no real patient information.
