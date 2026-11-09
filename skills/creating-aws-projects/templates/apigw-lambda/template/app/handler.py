import json
import logging
import os

logger = logging.getLogger()


def handler(event, context):
    headers = event.get("headers") or {}
    correlation_id = headers.get("x-correlation-id") or context.aws_request_id
    trace_id = os.environ.get("_X_AMZN_TRACE_ID", "")

    logger.info(
        "request handled",
        extra={"correlation_id": correlation_id, "route": event.get("routeKey")},
    )

    return {
        "statusCode": 200,
        "headers": {
            "content-type": "application/json",
            "x-correlation-id": correlation_id,
            "x-lambda-request-id": context.aws_request_id,
            "x-trace-id": trace_id,
        },
        "body": json.dumps({"message": "hello", "requestId": context.aws_request_id}),
    }
