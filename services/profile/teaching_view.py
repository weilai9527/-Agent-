"""对在管学生的当前档案生成教学摘要。读取前核权，读取与成功审计同笔提交。"""

import hashlib
import re
import unicodedata
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from starlette.concurrency import run_in_threadpool

from shared.recruitment import extract_skills
from shared.service_http import request_json
from shared.service_security import require_service
from . import store

ACTION = "profile.student.read"
router = APIRouter()

# 先清理整段的联系方式，随后按句选择。禁用从正文开头盲截取摘要，
# 以免将无标签姓名、联系地址等抬头文字交给老师。
LINK = re.compile(r"(?:https?://|www\.|mailto:|tel:)[^\s,，;；。]+|"
                  r"(?<![a-z0-9@])(?:[a-z0-9-]+\.)+(?:(?:com|cn|net|org|edu|io|invalid)(?:/[^\s,，;；。]*)?|"
                  r"[a-z]{2,63}/[^\s,，;；。]*)", re.I)
EMAIL = re.compile(r"(?<![a-z0-9_.+%-])[a-z0-9_.+%-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I)
NUMBER = re.compile(r"(?:\+?\d[\s()-]*){7,}\d[xX]?|\b[a-z]+[-_]?\d{3,}[a-z0-9_-]*\b", re.I)
LABEL = re.compile(r"姓名|名字|我叫|名叫|姓氏|联系人|身份证|证件号|学号|工号|编号|"
                   r"住址|地址|住在|家住|居住|籍贯|手机|电话|微信|QQ|邮箱|邮件|网址|"
                   r"出生|生日|邮编|个人主页|证书|资格证|作品链接|联系方式|家庭住址|通信地址|导师[:：]|负责人[:：]|"
                   r"\b(?:name|address|e-?mail|mobile|phone|wechat|contact|passport|"
                   r"student\s*(?:no|id|number)|date of birth|certificate)\b", re.I)
ADDRESS = re.compile(r"[\u3400-\u9fff]{2,16}(?:路|街|巷|弄)\s*\d|[\u3400-\u9fff]{2,16}市[\u3400-\u9fff]{2,16}区|"
                     r"[\u3400-\u9fff]{2,16}(?:小区|公寓|花园)[\u3400-\u9fff\d -]{0,12}(?:栋|号|室|单元)|"
                     r"\b\d{1,5}\s+[a-z][a-z\s.]{0,40}\b(?:street|road|avenue|blvd|lane|st\.|rd\.)", re.I)
CLAUSE = re.compile(r"[\r\n\t；;。！!？?|]+")
DUTY = re.compile(r"负责|主导|独立完成|参与|实现|搭建|设计|重构|开发|优化|维护|部署|测试|"
                  r"运营|组织|调研|分析|改进|编写|协助|完成|"
                  r"\b(?:led|built|developed|implemented|improved|designed|optimized|managed|analyzed|tested|deployed)\b", re.I)
DEGREE = re.compile(r"(?:全日制|在读|应届)?(?:博士(?:研究生)?|硕士(?:研究生)?|本科|专科|大专|中专|高中|学士)|"
                    r"\b(?:bachelor(?:'s)?|master(?:'s)?|ph\.?d\.?)\b", re.I)
TENURE = re.compile(r"(?<![\d.])(?:[0-4]?\d(?:\.\d)?|[一二三四五六七八九十两]{1,3})\s*(?:年半?|个月|years?)(?:以上|左右)?", re.I)
RESULT = re.compile(r"(?:提升|提高|改善|节省|减少|降低|增长|覆盖|服务|交付|出版|上线|缩短|"
                    r"reduced|increased|improved|delivered|saved|published)", re.I)
PERSON_LABEL = re.compile(r"(?:姓名|我叫|名叫|\bname)\s*[:：=]?\s*"
                          r"([\u3400-\u9fff]{2,4}(?=[\s,，;；。|]|$)|[A-Za-z]+(?: [A-Za-z]+){0,2})", re.I)

ID_LABEL = re.compile(r"(?:学号|工号|证件号|\bstudent\s*(?:no\.?|number|id))\s*[:：=]?\s*([A-Za-z0-9_-]{2,64})", re.I)


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKC", str(value or "")) if unicodedata.category(c) != "Cf")


def clauses(text, identifiers):
    value = LINK.sub("", EMAIL.sub("", normalized(text)))
    for identifier in identifiers:
        if identifier:
            if identifier.isascii():
                pattern = r"(?<![a-z0-9])" + re.escape(identifier) + r"(?![a-z0-9])"
                value = re.sub(pattern, "", value, flags=re.I)
            else:
                value = value.replace(identifier, "")
    for sentence in CLAUSE.split(value):
        # 联系人信息可能由逗号分隔为街道、城市等片段，应整句丢弃。
        if LABEL.search(sentence) or ADDRESS.search(sentence):
            continue
        for part in re.split("[,，]", sentence):
            fragment = " ".join(NUMBER.sub("", part).split()).strip("-:：、· ")
            if fragment:
                yield fragment


def compact(parts, limit):
    return "；".join(dict.fromkeys(part for part in parts if part))[:limit]


def summarize(snapshot):
    profile = snapshot["profile"]
    form = snapshot["form"]
    text = str(profile.get("resume_text") or "")
    sources = (text, profile.get("project_experience"), form.get("professional_skills"),
               form.get("education"), profile.get("target_role"))
    identifiers = {normalized(profile.get(key)) for key in ("nickname", "user_id", "resume_filename")}
    # 从明确的姓名标签提取同一档案中的实名，用于清理项目描述里的再次出现。
    for source in sources:
        identifiers.update(PERSON_LABEL.findall(normalized(source)))
        identifiers.update(ID_LABEL.findall(normalized(source)))
    # 结构化目标和技能本就由学生填写；清理后保留真实措辞，避免用技术岗位词表误删其它专业。
    role = compact(clauses(profile.get("target_role"), identifiers), 80)
    skills = compact(clauses(profile.get("skills") or form.get("skills"), identifiers), 120)
    if not skills:
        skills = "、".join(extract_skills(text))[:120]
    body_parts = list(clauses(text, identifiers))
    body_evidence = "；".join(body_parts)
    education = compact(clauses(profile.get("education_level") or form.get("education"), identifiers), 60)
    if not education:
        education = compact(DEGREE.findall(body_evidence), 60)
    experience = "；".join(clauses("；".join(str(s or "") for s in
                          (profile.get("years_of_experience"), profile.get("experience_level"))), identifiers))
    tenure = compact(TENURE.findall(experience + "；" + body_evidence), 40)
    duties = []
    outcomes = []
    for fragments, structured in ((clauses(profile.get("project_experience"), identifiers), True),
                                  (clauses(form.get("projects"), identifiers), True), (body_parts, False)):
        for fragment in fragments:
            outcome = RESULT.search(fragment)
            if outcome and len(outcomes) < 2:
                item = fragment[outcome.start():][:72]
                if item not in outcomes:
                    outcomes.append(item)
            duty = DUTY.search(fragment)
            if duty:
                fragment = fragment[duty.start():]
            elif not structured:
                continue
            if len(fragment) >= 4 and not re.fullmatch(r"(?:开发|测试|运营|设计)经验", fragment):
                item = fragment[:88]
                if item not in duties and len(duties) < 3:
                    duties.append(item)
    project = compact([*duties, *outcomes], 220)
    summary = compact([f"目标方向：{role}" if role else "", f"学历：{education}" if education else "",
                       f"经历时长：{tenure}" if tenure else "", f"项目职责：{duties[0]}" if duties else "",
                       f"项目成果：{outcomes[0]}" if outcomes else "", f"技能：{skills}" if skills else ""], 280)
    return {"target_role":role, "skills":skills, "education_level":education,
            "project_experience":project, "resume_summary":summary}


def audit_id(value):
    # 非标准路径值、姓名或邮箱不能作为原文写日志，哈希仍可用于关联同一目标。
    if (re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value)
            or (re.fullmatch(r"[A-Za-z0-9_:-]{1,128}", value) and not NUMBER.search(value))):
        return value
    return "sha256-" + hashlib.sha256(value.encode()).hexdigest()


def record(tx, actor, student_id, result, version=None):
    tx.execute("""INSERT INTO profile_access_audit
        (id,school_id,actor_id,actor_type,student_id,version,result) VALUES (?,?,?,?,?,?,?)""",
        (str(uuid4()),audit_id(actor["school_id"]),audit_id(actor["actor_id"]),actor["actor_type"],
         audit_id(student_id),version,result))


def record_denial(db, actor, student_id, outcome):
    with db.transaction(write=True) as tx:
        record(tx, actor, student_id, outcome)


def read_for_teaching(db, actor, student_id):
    with db.transaction(write=True) as tx:
        current = store.snapshot(tx, (actor["school_id"], student_id))
        if not current:
            record(tx, actor, student_id, "not_found")
            return None
        result = {"school_id":actor["school_id"],"student_id":student_id,"version":current["version"],
                  "profile":summarize(current)}
        record(tx, actor, student_id, "allowed", current["version"])
        return result


@router.get("/v1/admin/students/{student_id}/profile")
async def student_profile(request: Request, student_id: str = Path(min_length=1, max_length=128),
                          actor=Depends(require_service("profile", ACTION))):
    db = request.app.state.db
    if actor["actor_type"] not in {"teacher", "admin"}:
        await run_in_threadpool(record_denial,db,actor,student_id,"denied")
        raise HTTPException(403, "此接口仅供有权教职工使用。")
    expected = {key: actor[key] for key in ("school_id", "actor_id", "actor_type")}
    expected.update(student_id=student_id,action=ACTION)
    try:
        reply = await request_json("identity","POST","/internal/staff/authorize-student",actor=actor,
                                   scope="identity.student.authorize",body={"student_id":student_id,"action":ACTION})
        if reply != expected:
            raise HTTPException(403)
    except HTTPException as exc:
        denied = exc.status_code in {403,404}
        await run_in_threadpool(record_denial,db,actor,student_id,"denied" if denied else "unavailable")
        raise HTTPException(403 if denied else 503, "当前无法确认查阅此学生档案的权限。") from None
    # 只有核验成功后才查询版本行；对越权请求不能通过结果推断学生是否有简历。
    try:
        result = await run_in_threadpool(read_for_teaching, db, actor, student_id)
    except Exception:
        # 读取、脱敏或审计提交失败都不释放正文，也不向浏览器回显驱动异常。
        raise HTTPException(503, "教学档案暂时无法安全读取。") from None
    if result is None:
        raise HTTPException(404, "该学生尚无简历档案。")
    return result
