class PoisonMessage(ValueError):
    """The message can never succeed; retries only delay its move to the dead-letter queue."""


def process_order(message: dict) -> dict:
    if not isinstance(message, dict) or not message.get("id"):
        raise PoisonMessage("message has no id")
    if message.get("action") == "fail":
        raise PoisonMessage(f"order {message['id']} asked to fail")
    return {"id": message["id"], "status": "processed"}
