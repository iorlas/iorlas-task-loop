"""A missing shelf capability for the owner or supervisor to address in shelf."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ShelfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    package: str = Field(strict=True, min_length=1, max_length=200,
                         pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\z")
    capability: str = Field(strict=True, min_length=1, max_length=1000)

    @field_validator("capability")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("capability must not be blank")
        return value

    def describe(self) -> str:
        return (
            f"Shelf package {self.package} lacks the capability: {self.capability.strip()}. "
            "The owner or supervisor must address this in the shelf repository before this task can continue."
        )
