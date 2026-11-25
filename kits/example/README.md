# Example kit

A **fictional** person (Mutale Example, a data analyst in Lusaka) used by tests and by the
onboarding wizard's "try with sample data". Every name, employer, number and address is
invented; domains are `example.com`. It covers every Kit entity and validates against
`backend/app/kit/schema.py` (`KitFile`).

- `kit.json`: the kit file (`personal_backup`).
- `vault/`: sample vault files referenced by `kit.json` (sha256 checked by tests).
