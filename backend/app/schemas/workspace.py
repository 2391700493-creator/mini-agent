from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectSave(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("请输入项目名称。")
        return value.strip()


class ProjectView(BaseModel):
    id: str
    name: str


class FolderView(BaseModel):
    path: str
    name: str


class FolderListing(BaseModel):
    parent: str
    root_name: str
    items: list[FolderView]


class FolderSelection(BaseModel):
    folder: str | None
