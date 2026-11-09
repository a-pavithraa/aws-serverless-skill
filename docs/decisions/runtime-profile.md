# Decision: first runtime profile `apigw-lambda.python3.13-arm64-zip`

Date: 2026-11-08. Plan Task 1. Status: **candidate** until Task 6 sandbox evidence.

## Evaluation (plan §2)

| Dimension | Finding | Source / evidence |
| --- | --- | --- |
| Lifecycle | `python3.13`, Amazon Linux 2023, GA. Deprecation 2029-06-30, block create 2029-07-31, block update 2029-08-31: 2.6 years of runway | [Lambda runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html), read 2026-11-08 |
| Alternatives | `python3.14`: same dates, newer; no advantage for a dependency-free handler, so not chosen as "newest". `python3.12`: deprecates 2028-10-31, shorter runway. `python3.15`: public preview, excluded | same page |
| Application fit | HTTP request/response handler, I/O-free, stdlib only. Python chosen as the draft's language; teams on another language need their own profile | draft code |
| Architecture | arm64: no native libraries, layers or extensions, so no compatibility risk; x86_64 would also work and is UNVERIFIED until a profile exists | handler has no imports beyond stdlib |
| Packaging | ZIP from `app/` via `archive_file`, tests excluded; no dependency lock needed (empty dependency set) | `infra/main.tf` |
| Instrumentation | Lambda native JSON logs (stdlib `logging` + `extra` fields), active tracing; no Powertools, no OTel layer | `infra/main.tf`, `app/handler.py` |
| Semantics | on-demand Event Function, one request per environment; handler keeps no module state | |
| Startup | no SnapStart/provisioned concurrency; not measured, not needed to justify the choice | |
| Platform | us-east-1; AWS provider 6.72.0, archive 2.8.1, Terraform 1.14.4, Copier 9.19.1 | registry/PyPI read 2026-11-08 |
| Verification | pending Tasks 2, 3, 6 | `evidence` in the profile |

## Gate implemented

`skills/creating-aws-projects/scripts/profiles.py`; tests `tests/scripts/test_profiles.py` (preview, deprecated, inside-runway, stale source, missing date, missing fields, supported-without-evidence, unknown combinations). Copier `choices` restrict `runtime` and `architecture` to this profile's values; cross-field validators in `copier.yml` are tested by `tests/scripts/test_template_render.py`.
