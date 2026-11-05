"""核对自有源码中的说明性注释和 Python 文档字符串，输出供人工复核的文件位置。"""
import argparse
import ast
from collections import Counter
import io
import json
from pathlib import Path
import re
import subprocess
import tokenize

ROOT = Path(__file__).resolve().parents[1]
TREES = ("admin", "admin-next", "admin_backend", "backend", "deploy", "frontend", "scripts", "services", "shared", "src", "tests")
IGNORED = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "coverage", ".pytest_cache", "data", "logs", "preview"}
JS = {".js", ".jsx", ".ts", ".tsx", ".cjs", ".mjs"}
HAN = re.compile(r"[\u3400-\u9fff]")
# 保留解释器声明、类型/静态检查指令、许可证和构建器魔术注释，翻译会改变工具行为。
DIRECTIVE = re.compile(r"^(?:!|[-* ]*coding[:=]|noqa\b|type:\s*ignore\b|fmt:\s|ruff:|eslint-|@ts-|@license\b|SPDX-|copyright\b|#__PURE__|@vite-ignore|pragma:\s*no cover)", re.I)


def python_items(src):
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            yield tok.start[0], tok.string[1:], "注释"
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                yield node.body[0].lineno, doc, "说明"


def english(text):
    for line in text.splitlines():
        value = line.strip().strip("*").strip()
        if not value or DIRECTIVE.match(value) or HAN.search(value):
            continue
        # 多行文档按行复核，避免只在开头加一句中文便掩盖整段英文说明。
        if re.search(r"[A-Za-z]{2}", value):
            return True
    return False


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--summary", action="store_true", help="按文件夹显示待复核数量")
    args = cli.parse_args()
    # 使用 Git 的源码清单，避免扫描部署凭据、安装包和构建产物。
    files = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *TREES],
                                    cwd=ROOT).decode().split("\0")
    paths = [Path(name) for name in files if name and not IGNORED.intersection(Path(name).parts) and (ROOT / name).is_file()]
    issues = []
    js_files = []
    for path in paths:
        suffix = path.suffix
        if suffix in JS:
            js_files.append(str(path))
            continue
        if suffix not in {".py", ".css", ".ps1", ".conf"} and not path.name.endswith(".env.example"):
            continue
        source = (ROOT / path).read_text(encoding="utf-8-sig")
        if suffix == ".py":
            comments = python_items(source)
        elif suffix == ".css":
            comments = ((source.count("\n", 0, m.start()) + 1, m[1], "注释") for m in re.finditer(r"/\*(.*?)\*/", source, re.S))
        else:
            comments = ((i, l.strip()[1:], "注释") for i, l in enumerate(source.splitlines(), 1) if l.strip().startswith("#"))
        for line, comment, kind in comments:
            if english(comment):
                issues.append((str(path), line, kind, " ".join(comment.split())[:200]))
    # 由真正的 JS/JSX 解析器识别注释，不能把 URL、正则和提示词错当注释。
    js = """
const fs = require('node:fs'), parser = require('@babel/parser');
for (const file of JSON.parse(fs.readFileSync(0, 'utf8'))) {
  const source = fs.readFileSync(file, 'utf8');
  const result = parser.parse(source,{sourceType:'unambiguous',plugins:['jsx','typescript']});
  for (const c of result.comments) process.stdout.write(JSON.stringify([file,c.loc.start.line,c.value])+'\\n');
}
"""
    result = subprocess.run(["node", "-e", js], input=json.dumps(js_files), text=True, cwd=ROOT, capture_output=True, check=True)
    for line in result.stdout.splitlines():
        path, n, comment = json.loads(line)
        if english(comment):
            issues.append((path, n, "注释", " ".join(comment.split())[:200]))
    if args.summary:
        for group, n in Counter("/".join(Path(p).parts[:2]) for p, *_ in issues).most_common():
            print(f"{n:4} {group}")
    else:
        for path, n, kind, comment in issues:
            print(f"{path}:{n} {kind} {comment}")
    print(f"待人工复核的英文说明共 {len(issues)} 处")
    return bool(issues)


if __name__ == "__main__":
    raise SystemExit(main())
