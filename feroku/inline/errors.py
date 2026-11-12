class TelegramAPIError(Exception):
    label = "Telegram server says"

    def __init__(self, method=None, message=""):
        super().__init__(message)
        self.method = method
        self.message = message

    def __str__(self):
        return f"{self.label} - {self.message}"

    def __repr__(self):
        return f"{type(self).__name__}('{self}')"


class TelegramNetworkError(TelegramAPIError):
    label = "HTTP client says"


class TelegramRetryAfter(TelegramAPIError):
    def __init__(self, method=None, message="", retry_after=0):
        description = f"Flood control exceeded on method {method!r}."
        description += f" Retry in {retry_after} seconds."
        description += f"\nOriginal description: {message}"
        super().__init__(method=method, message=description)
        self.retry_after = retry_after


class TelegramBadRequest(TelegramAPIError):
    pass


class TelegramNotFound(TelegramAPIError):
    pass


class TelegramUnauthorizedError(TelegramAPIError):
    pass


class TelegramForbiddenError(TelegramAPIError):
    pass


class TelegramServerError(TelegramAPIError):
    pass
