"""Safe terminal errors for the official ChatGPT subscription provider."""


class ChatGPTSubscriptionLimitError(RuntimeError):
    code = "subscription_usage_limit"

    def __init__(self):
        super().__init__("ChatGPT 订阅共享额度已达上限；请在额度重置后从断点继续。")


def is_subscription_usage_limit(error):
    # Match the observed OpenAI response, never persist or echo arbitrary bodies.
    message = getattr(error, "message", "")
    return isinstance(error, ChatGPTSubscriptionLimitError) or (
        isinstance(message, str)
        and "the chatgpt user has reached their subscription sharing usage limit" in message.lower()
    )
