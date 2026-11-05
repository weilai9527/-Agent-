"""以只读方式检查显式配置的服务数据库，核对标识符列的排序规则。"""
import argparse

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.service_db import ServiceDatabase


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("service", choices=("identity", "training", "analytics", "credentials", "media", "provenance",
                                         "usage", "profile", "career", "assessment"))
    args = cli.parse_args()
    if args.service == "career":
        from services.career.store import school_databases
        stores = school_databases().values()
    else:
        stores = [ServiceDatabase.from_env(args.service)]
    for store in stores:
        if store.engine != "mysql":
            cli.error("This checker requires an explicitly configured MySQL service schema")
        for key_group in ("media-context", "media-rtc") if args.service == "media" else (args.service,):
            store.require_exact_keys(key_group)
    print(f"{args.service}: exact identifier columns verified")


if __name__ == "__main__":
    main()
