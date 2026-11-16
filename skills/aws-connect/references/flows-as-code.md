# Flows as code

## Getting flow content

`aws_connect_contact_flow` takes `content` (flow language JSON) or `filename` with `content_hash`. A JSON file that the console's export button produces is not flow language, so the resource cannot use it. Use the API instead:

```bash
aws connect describe-contact-flow --instance-id <id> --contact-flow-id <id> \
  | jq -r '.ContactFlow.Content' > flows/ivr.json
```

> *Source: [`aws_connect_contact_flow`](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/connect_contact_flow) · verified 2026-11-15*

`type` forces a new resource. A replaced flow gets a new ID, and phone numbers, queues and campaigns that point at the old ID break.

## Two ways to author

| Way | Use when | Cost |
| --- | --- | --- |
| Exported JSON as a `templatefile`, with ARNs substituted | A flow that the console still edits, or one that changes rarely | Diffs are a wall of JSON. Wrap it as `jsonencode(jsondecode(templatefile(...)))`, so that a bad substitution fails at plan time and the formatting is stable |
| A graph in HCL, rendered to flow language by a module | Flows that change often and are reviewed in pull requests | No round trip from the console. Pick this only when Terraform owns the content |

### The graph renderer

Write each action compactly, and let a module produce the JSON:

```hcl
{
  id         = "Invoke_Verify"
  type       = "InvokeLambdaFunction"
  params     = { LambdaFunctionARN = aws_lambda_function.verify.arn, InvocationTimeLimitSeconds = "8" }
  next       = "Set_Result"
  conditions = {}                               # operand => target, Equals only
  errors     = { NoMatchingError = "Set_Error" }
  at         = [2, 0]                           # designer grid position
}
```

The module turns each list into `Transitions.NextAction`, `Conditions` and `Errors`, and writes `Metadata.ActionMetadata` positions so the console designer opens it cleanly. Put these checks in an output `precondition`, so a broken graph fails at plan time:

- duplicate action IDs;
- a start action that does not exist;
- a transition to an action that does not exist;
- an action that nothing transitions to.

Also output a Mermaid `flowchart` of the edges. It appears in `terraform plan`, so a reviewer sees the flow change as a picture.

Make the renderer a module, not a set of locals. Call it once per flow. A flow module and the flow that invokes it can then reference each other's resources without a dependency cycle.

Test the renderer with `terraform test`. It is pure logic, so a `run` block with `command = plan` and no provider calls covers duplicate IDs, dangling targets and the rendered transitions.

## Flow modules

- Only contact attributes cross a module boundary. A module cannot read the invoking flow's stored input or `$.External` results, and the invoking flow cannot read the module's.
- A module that can end the contact takes routing decisions away from the invoking flow. Prefer modules that return on every path, including the Lambda Error branch, and let the invoking flow route.
- `aws_connect_contact_flow_module` has no `settings` argument. A module's content was rejected without a `Settings` object (`InputParameters`, `OutputParameters`, `Transitions`, empty lists are enough) inside the content JSON. The API documents `Settings` as an optional request field, so check this against your provider version.

## Logging and recording order

- `UpdateFlowLoggingBehavior` (Set logging behavior) turns flow logs on or off from that point. The setting carries into every flow that the contact is transferred to. If you disable logging and forget to enable it again, every flow after that point has no logs.
- Flow logs record the parameters sent to a Lambda function. Persisted flow attributes are hidden from the contact record but not from flow logs.
- Flow logs exist only when the instance has flow logs enabled and the flow has a Set logging behavior block set to enabled. Publish the flow again after you add the block.
- Turn recording on after the input steps, and test it: place a call and search the flow log group for the input value.

> *Sources: [Flow logs](https://docs.aws.amazon.com/connect/latest/adminguide/contact-flow-logs.html) · verified 2026-11-15; [Contact attributes](https://docs.aws.amazon.com/connect/latest/adminguide/connect-attrib-list.html) · verified 2026-11-15*

## Switching a flow to new content

A new flow resource receives no traffic until the phone number, chat widget or queue points at it. Create the flow, test it on a test number (`aws_connect_phone_number_contact_flow_association`), then move the production number in a separate change. Moving the number is the release.
