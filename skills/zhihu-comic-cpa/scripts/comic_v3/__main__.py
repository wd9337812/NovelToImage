from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .core import ProductionError, read_json, write_json, validate_plan, migrate_legacy
from .provider import validate_profile
from .pipeline import Production, export
from .scheduler import Scheduler


def main(argv=None, legacy=None):
    if legacy is None:
        import comic as legacy
    parser = argparse.ArgumentParser(description="v3漫画生产：已核验模型资料＋逐页脚本＋可编辑排字")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema", help="查看技能内置的原创version3分镜示例")
    run = sub.add_parser("run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--story", type=Path, required=True)
    run.add_argument("--profile", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--pages", help="按稳定页面ID选择，以逗号分隔")
    run.add_argument("--stage", choices=["all", "assets"], default="all")
    run.add_argument("--max-attempts", type=int, default=12)
    run.add_argument("--mock", action="store_true")
    check = sub.add_parser("profile-check", help="校验agent查阅资料后写出的模型档案，不调用API")
    check.add_argument("path", type=Path)
    pack = sub.add_parser("export")
    pack.add_argument("path", type=Path)
    pack.add_argument("--review-copy", action="store_true", help="明确带REVIEW前缀的待审样本，不能伪称成品")
    migrate = sub.add_parser("migrate-plan")
    migrate.add_argument("--plan", type=Path, required=True)
    migrate.add_argument("--story", type=Path, required=True)
    migrate.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            print((Path(__file__).resolve().parents[2]/"references/plan-v3.example.json").read_text(encoding="utf-8"))
            return 0
        legacy.load_env(Path.cwd()/".env")
        if args.command == "profile-check":
            p = validate_profile(read_json(args.path))
            print(json.dumps({"model": p["model"], "limits": p["limits"], "evidence": p["research"]["decision"]}, ensure_ascii=False, indent=2))
        elif args.command == "migrate-plan":
            write_json(args.out, migrate_legacy(read_json(args.plan), args.story.read_text(encoding="utf-8-sig").strip()))
        elif args.command == "export":
            for path in export(args.path, args.review_copy):
                print(path)
        else:
            if not 1 <= args.max_attempts <= 1000:
                raise ProductionError("图片总提交预算需为1–1000。")
            production = Production(read_json(args.plan), read_json(args.profile), args.story.read_text(encoding="utf-8-sig").strip(), args.out, legacy, args.max_attempts, args.mock)
            result = production.run(args.pages.split(",") if args.pages else None, args.stage)
            print(result)
        return 0
    except (ProductionError, legacy.ComicError) as exc:
        print("错误："+str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("输入／本地文件错误："+type(exc).__name__+"；未输出凭据或服务端正文。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
