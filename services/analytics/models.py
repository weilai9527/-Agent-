"""教学分析接口和内部服务之间的数据契约。"""
from collections import defaultdict
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator


Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f]+$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(Input):
    question_id: Identifier
    original_answer: str = Field(max_length=64000)
    dimension: Label
    score: float = Field(ge=0, le=100, strict=True, allow_inf_nan=False)


class Completion(Input):
    event_id: Identifier
    attempt_id: Identifier
    version: int = Field(strict=True, ge=1, le=2147483647)
    questions: list[Observation] = Field(max_length=1000)

    @model_validator(mode="after")
    def consistent_evidence(self):
        dimensions = defaultdict(set)
        answers = {}
        for row in self.questions:
            qid = row.question_id
            if row.dimension in dimensions[qid]:
                raise ValueError("duplicate question and dimension")
            if answers.setdefault(qid, row.original_answer) != row.original_answer:
                raise ValueError("dimensions must refer to the same answer")
            dimensions[qid].add(row.dimension)
        return self


class Practice(Input):
    attempt_id: Identifier
    question_id: Identifier
    request_id: Identifier
    deadline: AwareDatetime
    max_attempts: int = Field(strict=True, ge=1, le=100)


# 下游可独立扩展响应，分析服务只提取自己依赖的权威字段。
class FrozenQuestion(BaseModel):
    question_id: Identifier
    prompt: str = Field(min_length=1, max_length=4000)


class Attempt(BaseModel):
    attempt_id: Identifier
    interview_id: Identifier
    task_id: Identifier
    student_id: Identifier
    teacher_id: Identifier
    class_id: Identifier
    school_id: Identifier
    job_role: Label
    status: str
    questions: list[FrozenQuestion] = Field(min_length=1)


class Class(BaseModel):
    class_id: Identifier


class VisibleClasses(BaseModel):
    items: list[Class]


class Enrollment(Class):
    student_ids: list[Identifier]


class Roster(BaseModel):
    classes: list[Enrollment]
