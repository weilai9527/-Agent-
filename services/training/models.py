from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from typing import Annotated


Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f]+$")]
Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Question(Input):
    question_id: Identifier
    prompt: Prompt


class Schedule(Input):
    deadline: datetime
    max_attempts: int = Field(strict=True, ge=1, le=100)

    @field_validator("deadline")
    @classmethod
    def explicit_offset(cls, value):
        if value.utcoffset() is None:
            raise ValueError("deadline requires a UTC offset")
        return value


class Assignment(Schedule):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    job_role: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    job_id: Identifier | None = None
    class_ids: list[Identifier] = Field(min_length=1, max_length=100)
    questions: list[Question] = Field(min_length=1, max_length=100)
    request_id: Identifier | None = None

    @field_validator("class_ids", "questions")
    @classmethod
    def unique_ids(cls, value):
        ids = [q.question_id if isinstance(q, Question) else q for q in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate identifier")
        return value


class Repractice(Schedule):
    source_attempt_id: Identifier
    question_id: Identifier
    prompt: Prompt
    request_id: Identifier


class Start(Input):
    request_id: Identifier


class Completion(Input):
    event_id: Identifier
    interview_id: Identifier
