import json
import os

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.idempotency import (
    DynamoDBPersistenceLayer,
    IdempotencyConfig,
    idempotent_function,
)

from orders import process_order

logger = Logger()
processor = BatchProcessor(event_type=EventType.SQS)
persistence = DynamoDBPersistenceLayer(table_name=os.environ["IDEMPOTENCY_TABLE"])
idempotency = IdempotencyConfig(event_key_jmespath="id", expires_after_seconds=3600)


@idempotent_function(data_keyword_argument="message", config=idempotency, persistence_store=persistence)
def handle_order(message: dict) -> dict:
    result = process_order(message)
    logger.info("order processed", order_id=message["id"])
    return result


def record_handler(record):
    message = json.loads(record.body)
    logger.info(
        "message received",
        order_id=message.get("id") if isinstance(message, dict) else None,
        message_id=record.message_id,
        receive_count=record.attributes.approximate_receive_count,
    )
    return handle_order(message=message)


@logger.inject_lambda_context
def handler(event, context):
    idempotency.register_lambda_context(context)
    return process_partial_response(event=event, record_handler=record_handler, processor=processor, context=context)
