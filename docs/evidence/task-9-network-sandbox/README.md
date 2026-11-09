# Task 9: sandbox deployment evidence for `network`

Date: 2026-11-09. Account `123456789012` (the `personal` AWS profile), region `us-east-1`, local Terraform state. Profile `network.none-managed-module`. Template revision `1cf9fce+uncommitted`. Terraform 1.14.4, AWS provider 6.72.0, `terraform-aws-modules/vpc/aws` 6.7.3 pinned to its commit.

Answers: project `lf-net`, environment `dev`, CIDR `10.42.0.0/16` (default), two zones, `nat_mode = none`. The run used the same local sequence as Task 6: saved plan, sanitized summary, provenance write and verify, apply of the saved plan.

## Steps

| Step | Result | Log |
| --- | --- | --- |
| Render, install, check | `harness check: PASS (pass 8, fail 0, unverified 0)` | `01`–`03` |
| Plan, provenance, apply | 19 added; apply took 30 s | `04`–`07` |
| SSM parameters against EC2 | match (below) | `09-ssm-vs-ec2.log` |
| Plan `alb-ec2` with `network_name = lf-net-dev` only | 20 to add, every network reference in `lf-net` (below); not applied | `10-consumer-plan.log`, `11-consumer-subnets.log` |
| Destroy from a saved destroy plan | 19 destroyed; no SSM parameters left | `12`–`14` |
| `verify_deployment.py residue` | FAIL on a deleted security group and flow log; after the fix below, PASS | `15-residue.log`, `15-residue-rerun.log` |
| Destroy the earlier sandbox VPC (`fixture-sandbox-vpc.tf` in `task-9-ec2-sandbox/`) | 7 destroyed; no VPC tagged `lf-sandbox-net` left | `16-fixture-plan-destroy.log`, `17-fixture-destroy.log` |

The SSM parameters under `/landform/network/lf-net-dev/` named what EC2 reported:

- `vpc-id` `vpc-0316eaacbffec1be1`: `10.42.0.0/16`, `available`, internet gateway attached (`available`).
- `public-subnet-ids`: two subnets in that VPC, in `us-east-1a` and `us-east-1b`, with public IP addresses on launch. Their route table sends `0.0.0.0/0` to the internet gateway, state `active`.
- `nat-mode` `none`. With no NAT, the template makes no private subnets and writes no `private-subnet-ids`.
- The VPC flow log was `ACTIVE`, to CloudWatch Logs.

The `alb-ec2` plan, given only `network_name`, read the parameters at plan time. The load balancer and the Auto Scaling group got the two `lf-net` subnets, and both security groups and the target group got the `lf-net` VPC.

## Finding for the verifier

The tag index still listed the VPC's default security group and the flow log after destroy. Both were gone (`InvalidGroup.NotFound`; `describe-flow-logs` returned nothing). The residue check now asks EC2 about both kinds, and reports a deleted one instead of failing. Tests: `test_deleted_security_group_and_flow_log_are_reported_not_failed`, `test_live_security_group_fails`, `test_live_flow_log_fails`.

## Not verified

- **`nat_mode` `single` and `per-az`**, private subnets, and a consumer in private subnets. They cost money for each hour, and nothing here used them. The mocked tests cover the plan.
- **A consumer applied in the network.** The `alb-ec2` and `ecs-web` deploys ran in the earlier sandbox VPC, passed as `subnet_ids`. This run proved the `network_name` wiring by plan only.
- **`ecs-web` with `network_name`.** It reads the same parameter in the same way; it was not planned against this network.
- Three zones, other regions, the GitHub Actions path.

## Cost and cleanup

The network ran for about 10 minutes, with no NAT gateway. It cost nothing beyond flow-log ingestion. After destroy, nothing tagged `Project=lf-net` is live and no `/landform/network/lf-net-dev` parameter is left.
