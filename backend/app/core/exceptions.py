"""Domain exceptions and the FastAPI handlers that turn them into clean JSON responses."""
import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError

logger = logging.getLogger(__name__)


def format_safe_traceback(exc: Exception) -> str:
    """Log exception types and frames without messages that may contain user data."""
    traces = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        traces.append(f"{type(current).__name__} traceback:\n")
        if current.__traceback__ is not None:
            traces.extend(traceback.format_tb(current.__traceback__))
        current = current.__cause__ or current.__context__
        if current is not None:
            traces.append("Caused by:\n")
    return "".join(traces)


class AppError(Exception):
    status_code = 400
    detail = "Request could not be processed."

    def __init__(self, detail: str | None = None):
        super().__init__(detail or self.detail)
        self.detail = detail or self.detail


class UnsupportedFileError(AppError):
    status_code = 415
    detail = "Unsupported file format. Please upload PDF or DOCX."


class FileTooLargeError(AppError):
    status_code = 413
    detail = "File is too large."


class EmptyDocumentError(AppError):
    status_code = 422
    detail = "The document contains no extractable text."


class CorruptedDocumentError(AppError):
    status_code = 422
    detail = "The document appears to be corrupted or is not a valid file."


class ModelUnavailableError(AppError):
    status_code = 503
    detail = "The language model is not available right now. Please try again later."


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(OperationalError)
    async def _db_unavailable(_: Request, exc: OperationalError):
        logger.error("Database unavailable:\n%s", format_safe_traceback(exc))
        return JSONResponse(status_code=503, content={"detail": "Database is unavailable. Please try again later."})

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(_: Request, exc: SQLAlchemyError):
        logger.error("Database error:\n%s", format_safe_traceback(exc))
        return JSONResponse(status_code=500, content={"detail": "A database error occurred."})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.error("Unhandled error:\n%s", format_safe_traceback(exc))
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})
