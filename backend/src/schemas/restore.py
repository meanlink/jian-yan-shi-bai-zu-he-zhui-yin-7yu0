from pydantic import BaseModel, Field
class RestorePointInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
