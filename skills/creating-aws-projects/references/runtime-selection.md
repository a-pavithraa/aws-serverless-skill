# Runtime selection

A template renders only a runtime/architecture/packaging combination that has a profile in `profiles/`. Anything else is **UNVERIFIED**: say so to the user and do not render it as if it were supported.

Check a combination before rendering:

```bash
python scripts/profiles.py resolve apigw-lambda python3.13 arm64 zip --region us-east-1
```

Exit 0 PASS, 1 FAIL (preview, deprecated, inside the runway, incomplete, or `supported` without sandbox evidence), 2 UNVERIFIED (no profile, no recorded deprecation date, or the lifecycle source is more than 180 days old).

## Gate

| Rule | Value | Why |
| --- | --- | --- |
| Runway | deprecation date at least 365 days away | A new project should not start inside its migration window. Team policy; change `RUNWAY_DAYS` deliberately. |
| Preview | never a default | AWS: preview runtimes are not covered by the Lambda SLA or Technical Support. |
| Lifecycle recheck | every 180 days and before a template release | AWS moves dates; this repo keeps no permanent copy. |
| `supported` status | needs `evidence.sandbox` | Mocks and static checks prove configuration, not deployed behaviour. |
| No runtime | `deprecation: "none"` with a non-empty `reason` | A managed service, such as Step Functions, has no runtime version to deprecate. Without a reason, the profile fails. |

## Choosing a runtime for a new profile

Start from the team's language and existing code, not from the newest runtime or a cold-start benchmark. Then record in the profile: identifier, OS, the three lifecycle dates from the [runtimes page](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html) with the check date, architecture (every native library, layer and extension must exist for it: [architectures](https://docs.aws.amazon.com/lambda/latest/dg/foundation-arch.html)), packaging, instrumentation, regions and tool versions.

- **ARM64 is not universal.** It is right for the shipped profile because the handler has no dependencies. A profile with native wheels or a vendor extension needs a target-platform build and test first.
- **SnapStart / provisioned concurrency** only with measured latency that needs them, after checking [SnapStart restrictions](https://docs.aws.amazon.com/lambda/latest/dg/snapstart.html) and testing restored state (connections, credentials, random/unique values).
- **Powertools**: pick utilities per pattern (logging, metrics, batch, idempotency) and pin the version. Its Python Tracer wraps the X-Ray SDK, which is in maintenance mode; for tracing in new templates prefer Lambda active tracing or a tested OpenTelemetry layer. Do not add both.
- **Custom runtimes, Rust/Go, LLRT** need a named patch owner and a measured benefit.
- **Existing workloads** on a deprecated runtime get a migration report, not an automatic major-version rewrite.
