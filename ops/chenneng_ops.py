#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
定增业务工具（AI 投研驾驶舱）运维脚本
仓库: lord-masi/chenneng   页面: https://lord-masi.github.io/chenneng/

用法:
  python chenneng_ops.py status              线上状态摘要（是否今天、各段条数、持仓数）
  python chenneng_ops.py holdings            输出持仓 JSON
  python chenneng_ops.py check-token         令牌健康检查
  python chenneng_ops.py commits [n]         最近 n 次提交
  python chenneng_ops.py quote               抓实时行情（GBK）
  python chenneng_ops.py fetch-daily <out>   下载线上 daily.json 到文件
  python chenneng_ops.py put-daily <file>    推送 daily.json（自动 sha + 409 重试）
  python chenneng_ops.py verify morning      校验晨报（date=今天 + 三个字段非空）
  python chenneng_ops.py verify review       校验复盘（额外校验条数=持仓数）
  python chenneng_ops.py alert "<msg>"       写告警到 ALERT.log 并生成醒目文件

退出码: 0 = 通过 / 1 = 不通过或出错
"""
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = "lord-masi/chenneng"
API = "https://api.github.com/repos/%s/contents/" % REPO
PAGES = "https://lord-masi.github.io/chenneng/"
TOKEN_FILE = r"D:\WB-appdata\secrets\chenneng_gh_token.txt"
OPS_DIR = os.path.dirname(os.path.abspath(__file__))
ALERT_LOG = os.path.join(OPS_DIR, "ALERT.log")
ALERT_FLAG = os.path.join(OPS_DIR, "!!!有待处理告警.txt")
BJ = timezone(timedelta(hours=8))


def today_bj():
    return datetime.now(BJ).strftime("%Y-%m-%d")


def now_bj():
    return datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")


def token():
    # 1) 环境变量（云端沙箱用）
    env = os.environ.get("CHENNENG_TOKEN", "").strip()
    if env:
        return env
    # 2) 本地文件
    for p in (TOKEN_FILE, os.path.join(OPS_DIR, "gh_token.txt")):
        if os.path.exists(p):
            t = io.open(p, encoding="utf-8").read().strip()
            if t:
                return t
    raise SystemExit("[ERR] 找不到 GitHub 令牌：请设置环境变量 CHENNENG_TOKEN，或放置 %s" % TOKEN_FILE)


def _req(url, tok=None, payload=None, method=None, raw=False):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "chenneng-ops"}
    if tok:
        headers["Authorization"] = "Bearer " + tok
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=45) as r:
        body = r.read()
        return body.decode("utf-8", "replace") if raw else json.loads(body.decode("utf-8"))


def get_file(path):
    """返回 (json内容, sha)"""
    d = _req(API + path, token())
    content = base64.b64decode(d["content"]).decode("utf-8")
    return json.loads(content), d["sha"]


def get_holdings():
    try:
        h, _ = get_file("holdings.json")
        return h
    except Exception:
        # 公开地址兜底
        raw = _req("https://raw.githubusercontent.com/%s/main/holdings.json" % REPO, raw=True)
        return json.loads(raw)


def line(t=""):
    print(t)


# ---------------- 命令实现 ----------------

def cmd_status():
    ok = True
    line("== 线上状态 @ %s (北京时间) ==" % now_bj())
    # 线上 daily.json
    try:
        raw = _req(PAGES + "daily.json?t=%d" % int(time.time()), raw=True)
        d = json.loads(raw)
        m, r, s = d.get("morning") or [], d.get("review") or [], d.get("shortTerm") or []
        td = today_bj()
        is_today = d.get("date") == td
        line("页面 daily.json : date=%s %s" % (d.get("date"), "（今天）" if is_today else "（不是今天！）"))
        line("  晨报 %d 条 | 复盘 %d 条 | 短线 %d 条 | source=%s" % (len(m), len(r), len(s), d.get("source")))
        if not is_today:
            ok = False
    except Exception as e:
        line("页面 daily.json : 取数失败 %s" % e)
        ok = False
    # 持仓
    try:
        h = get_holdings()
        hs = h.get("holdings") or []
        line("持仓 %d 只 : %s" % (len(hs), "、".join(x.get("name", "?") for x in hs)))
        line("  条数校验基准 N=%d" % len(hs))
    except Exception as e:
        line("持仓读取失败: %s" % e)
        ok = False
        hs = []
    # 最近提交
    try:
        cs = _req("https://api.github.com/repos/%s/commits?per_page=3" % REPO)
        line("最近提交:")
        for c in cs:
            t = c["commit"]["author"]["date"]
            dt = datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(BJ)
            line("  %s | %s" % (dt.strftime("%m-%d %H:%M"), c["commit"]["message"].split("\n")[0]))
    except Exception as e:
        line("提交查询失败: %s" % e)
    line("")
    line("判定: %s" % ("✅ 今天数据已就位" if ok else "⚠️ 需要处理"))
    return 0 if ok else 1


def cmd_holdings():
    print(json.dumps(get_holdings(), ensure_ascii=False, indent=1))
    return 0


def cmd_check_token():
    try:
        d = _req("https://api.github.com/repos/%s" % REPO, token())
        u = _req("https://api.github.com/user", token())
        line("[OK] 令牌有效 | 账号=%s | 仓库=%s | private=%s"
             % (u.get("login"), d.get("full_name"), d.get("private")))
        return 0
    except urllib.error.HTTPError as e:
        line("[ERR] 令牌无效或权限不足 HTTP %s" % e.code)
        return 1
    except Exception as e:
        line("[ERR] %s" % e)
        return 1


def cmd_commits(n=5):
    cs = _req("https://api.github.com/repos/%s/commits?per_page=%d" % (REPO, int(n)))
    for c in cs:
        t = c["commit"]["author"]["date"]
        dt = datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(BJ)
        line("%s | %s" % (dt.strftime("%Y-%m-%d %H:%M"), c["commit"]["message"].split("\n")[0]))
    return 0


def cmd_quote():
    h = get_holdings()
    codes = ",".join(x["code"] for x in h.get("holdings") or [])
    raw = urllib.request.urlopen("https://qt.gtimg.cn/q=" + codes, timeout=30).read()
    txt = raw.decode("gbk", "replace")
    line("%-10s %8s %8s %8s" % ("名称", "现价", "昨收", "涨跌幅"))
    for seg in txt.split(";"):
        if "=" not in seg:
            continue
        f = seg.split('="')[-1].strip('"\n ').split("~")
        if len(f) < 33:
            continue
        line("%-10s %8s %8s %8s" % (f[1], f[3], f[4], f[32] + "%"))
    return 0


def cmd_fetch_daily(out):
    raw = _req(PAGES + "daily.json?t=%d" % int(time.time()), raw=True)
    d = json.loads(raw)
    io.open(out, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    line("[OK] 已保存 %s | date=%s" % (out, d.get("date")))
    return 0


def cmd_put_daily(path):
    if not os.path.exists(path):
        line("[ERR] 文件不存在: %s" % path)
        return 1
    new = json.loads(io.open(path, encoding="utf-8").read())
    for attempt in range(2):
        try:
            _, sha = get_file("daily.json")
        except Exception as e:
            line("[ERR] 读取当前 sha 失败: %s" % e)
            return 1
        payload = {
            "message": "daily 更新 %s" % new.get("date", ""),
            "content": base64.b64encode(
                json.dumps(new, ensure_ascii=False, indent=1).encode("utf-8")).decode(),
            "sha": sha,
        }
        # 依据内容判断提交说明
        try:
            old, _ = get_file("daily.json")
            if old.get("morning") != new.get("morning") and old.get("review") == new.get("review"):
                payload["message"] = "晨报更新 %s" % new.get("date", "")
            elif old.get("review") != new.get("review") and old.get("morning") == new.get("morning"):
                payload["message"] = "收盘复盘更新 %s" % new.get("date", "")
        except Exception:
            pass
        try:
            r = _req(API + "daily.json", token(), payload, method="PUT")
            line("[OK] 已推送 | %s | commit=%s" % (payload["message"], r["commit"]["sha"][:8]))
            return 0
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (409, 422) and attempt == 0:
                line("[WARN] sha 冲突，重新读取后重试")
                time.sleep(2)
                continue
            line("[ERR] PUT 失败 HTTP %s: %s" % (e.code, body[:300]))
            return 1
    return 1


def _verify(kind):
    problems = []
    try:
        raw = _req(PAGES + "daily.json?t=%d" % int(time.time()), raw=True)
        d = json.loads(raw)
    except Exception as e:
        line("[FAIL] 线上取数失败: %s" % e)
        return 1
    td = today_bj()
    m, r, s = d.get("morning") or [], d.get("review") or [], d.get("shortTerm") or []
    if d.get("date") != td:
        problems.append("date=%s，不是今天 %s" % (d.get("date"), td))
    if not m:
        problems.append("morning 为空")
    if not r:
        problems.append("review 为空")
    if not s:
        problems.append("shortTerm 为空")
    if kind == "review":
        try:
            n = len(get_holdings().get("holdings") or [])
            if len(r) != n:
                problems.append("review 条数 %d ≠ 持仓数 %d" % (len(r), n))
            if len(s) != n:
                problems.append("shortTerm 条数 %d ≠ 持仓数 %d" % (len(s), n))
        except Exception as e:
            problems.append("持仓读取失败: %s" % e)
    # 禁用 URL 检查
    txt = json.dumps(d, ensure_ascii=False)
    if "http://" in txt or "https://" in txt:
        problems.append("内容中出现 http/https 链接（违反铁律）")
    line("== 校验(%s) @ %s ==" % (kind, now_bj()))
    line("date=%s | morning=%d | review=%d | shortTerm=%d" % (d.get("date"), len(m), len(r), len(s)))
    if problems:
        line("[FAIL] " + "；".join(problems))
        return 1
    line("[PASS] 校验通过")
    return 0


def cmd_verify(kind):
    return _verify(kind)


def cmd_alert(msg):
    ts = now_bj()
    with io.open(ALERT_LOG, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (ts, msg))
    with io.open(ALERT_FLAG, "w", encoding="utf-8") as f:
        f.write("定增驾驶舱流水线告警\n时间：%s\n问题：%s\n\n处置：打开 WorkBuddy 对话说明情况，可要求补发。\n"
                % (ts, msg))
    line("[ALERT 已记录] %s" % msg)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    c = sys.argv[1]
    a = sys.argv[2:]
    if c == "status":
        return cmd_status()
    if c == "holdings":
        return cmd_holdings()
    if c == "check-token":
        return cmd_check_token()
    if c == "commits":
        return cmd_commits(a[0] if a else 5)
    if c == "quote":
        return cmd_quote()
    if c == "fetch-daily":
        return cmd_fetch_daily(a[0] if a else "daily_current.json")
    if c == "put-daily":
        return cmd_put_daily(a[0]) if a else 1
    if c == "verify":
        return cmd_verify(a[0] if a else "morning")
    if c == "alert":
        return cmd_alert(a[0] if a else "未说明")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
