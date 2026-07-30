from typing import Generic, TypeVar

from pydantic import BaseModel

DataT = TypeVar("DataT")


class APIError(BaseModel):
    code: str
    message: str


class APIResponse(BaseModel, Generic[DataT]):
    data: DataT | None = None
    error: APIError | None = None
