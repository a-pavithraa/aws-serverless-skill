# Access control, adoption and events

## Security profiles and access-control tags

| Rule | Effect |
| --- | --- |
| Several tags on one profile | AND: the user sees only resources that carry all the tags |
| Several profiles on one user | OR: the user sees resources allowed by any of them |
| A tagged and an untagged profile grant the same permission | Connect enforces the untagged profile, so the tag restriction is lost for that permission |
| Tags per profile | At most 4 |
| Tagged profiles per user | At most 7 |

> *Source: [Tag-based access control](https://docs.aws.amazon.com/connect/latest/adminguide/tag-based-access-control.html) · verified 2026-11-15*

A pattern for department supervisors:

- One security profile per department, carrying one tag (`dept = billing`). A supervisor of two departments gets two profiles.
- The same tag on the department's queues, routing profiles and users.
- Only the supervisor permissions in the tagged profiles. Keep the base agent profile free of permissions that overlap them, because the untagged profile wins.

When a resource type is in `tag_restricted_resources` and no resource of that type carries the tag, the user sees none of them. Tag the existing queues before you restrict `Queue`. That is a reason to adopt queues that were built in the console.

A profile name that is derived from a variable forces replacement when the variable changes. Connect will not delete a profile that is still assigned to a user, so set `create_before_destroy = true`.

### Setting the tags without `awscc`

`aws_connect_security_profile` has no tag-restriction arguments, verified 2026-11-15. The fallback:

```hcl
resource "terraform_data" "access_control" {
  for_each = var.departments

  triggers_replace = {
    profile = aws_connect_security_profile.supervisor[each.key].security_profile_id
    tag     = "${var.dept_tag_key}=${each.key}"
  }

  provisioner "local-exec" {
    command = "aws connect update-security-profile --instance-id ${var.instance_id} --security-profile-id ${self.triggers_replace.profile} --allowed-access-control-tags ${self.triggers_replace.tag} --tag-restricted-resources User Queue RoutingProfile"
  }
}
```

This is not drift-detected. Prefer `awscc_connect_security_profile`. If you use the fallback, run a scheduled check that compares `aws connect describe-security-profile` with the code.

## Users

- On a SAML instance, the username is the federation identifier. Connect rejects `identity_info.email` with "Email is not required for this directory type".
- Generate the users map from the identity provider's groups (for example, a script that writes `users.auto.tfvars.json`). Do not keep a hand list.

## Adopting console-built resources

```hcl
import {
  for_each = var.hours_of_operation
  to       = aws_connect_hours_of_operation.this[each.key]
  id       = "${var.instance_id}:${each.value.hours_of_operation_id}"
}
```

- Import IDs are `<instance_id>:<resource_id>`.
- Add `prevent_destroy` to adopted queues and hours. Flows and campaigns point at their IDs, and removing a map entry must fail, not delete.
- Copy the existing values (description, tags, outbound caller config) into the configuration before the first apply. Otherwise the first apply changes them.

## Approved origins

An embedded CCP (Streams) loads only from an approved origin of the instance. Use `awscc_connect_approved_origin`. Without Cloud Control access, a `terraform_data` with `associate-approved-origin` on create and `disassociate-approved-origin` on destroy works. Put the region, instance and origin in `input`, and reference them as `self.input` in the destroy provisioner. A destroy provisioner cannot read variables.

## Contact events to SQS

```hcl
event_pattern = jsonencode({
  source        = ["aws.connect"]
  "detail-type" = ["Amazon Connect Contact Event"]
  resources     = [local.instance_arn]
})
```

- Events are emitted on a best-effort basis and are not ordered. Use the event timestamp, and make the consumer idempotent.
- A queue policy lets `events.amazonaws.com` send, with `aws:SourceArn` equal to the rule ARN.
- EventBridge does not retry a permission error or a missing target, and drops the event when the target has no DLQ. The queue's own redrive DLQ does not see those events. Set `dead_letter_config` on `aws_cloudwatch_event_target`, and alarm on the rule's `FailedInvocations`.
- An SQS target encrypted with a customer managed key needs a key policy statement that allows `events.amazonaws.com` to use `kms:Decrypt` and `kms:GenerateDataKey`. Without it, delivery fails. SSE-SQS avoids this.
- Alarm on the DLQ depth (`ApproximateNumberOfMessagesVisible > 0`). Messages left in a DLQ expire at the end of its retention period.

> *Sources: [Contact events](https://docs.aws.amazon.com/connect/latest/adminguide/contact-events.html) · verified 2026-11-15; [EventBridge DLQs](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-rule-dlq.html) · verified 2026-11-15; [EventBridge troubleshooting](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-troubleshooting.html) · verified 2026-11-15*

### Contact Lens analysis files

Contact Lens writes post-call analysis files to the instance's S3 bucket under `Analysis/Voice/`, with redacted copies under `Analysis/Voice/Redacted/`. To consume them, turn on EventBridge notifications for the bucket, then match `Object Created` with a key wildcard that selects the files you want:

```hcl
detail = {
  bucket = { name = [var.recordings_bucket] }
  object = { key = [{ wildcard = "Analysis/Voice/2*_analysis_*.json" }] }
}
```

Until the bucket's EventBridge notifications are on, the rule exists and matches nothing. Check a pattern with `aws events test-event-pattern` before you rely on it.
