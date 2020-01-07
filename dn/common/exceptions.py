from werkzeug.exceptions import HTTPException


class AppBaseException(HTTPException):
    def __init__(self, code, description, data=None, extra_info=None):
        self.code = int(code)
        self.description = description
        self.response = data
        self.extra_info = extra_info


class ParameterError(AppBaseException):
    pass


class OperationConflictedError(AppBaseException):
    pass


class SessionError(AppBaseException):
    pass


class ConnectionError(Exception):
    """Failed to connect to the broker."""
    pass


class RequestDataException(HTTPException):
    code = 400
    description = 'Request Data Not Integrity'
