class ApplicationError(Exception):
    pass


class InputRejected(ApplicationError):
    pass


class AuthenticationDenied(ApplicationError):
    pass


class PermissionDenied(ApplicationError):
    pass


class InvalidState(ApplicationError):
    pass


class ConcurrentConflict(ApplicationError):
    pass


class TokenRejected(ApplicationError):
    pass


class RateLimited(ApplicationError):
    pass
