### Terraform plan: 1 to create, 1 to update

| Address | Action | Known after apply |
| --- | --- | --- |
| `aws_kms_key.alarms` | create | arn, id, key_id, multi_region, rotation_period_in_days |
| `aws_sns_topic.alarms` | update | kms_master_key_id |
