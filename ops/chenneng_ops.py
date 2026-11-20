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
  python chenneng_ops.py put-daily <file> [morning|review]
                                             推送 daily.json（带类型可保证提交说明可被识别）
  python chenneng_ops.py fresh morning|review 检查今天是否已有对应提交（区分新旧内容）
  python chenneng_ops.py verify morning|review 综合校验（含新鲜度）
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
        # 公开 API 兜底（不走 raw.githubusercontent，部分网络环境不可达）
        d = _req("https://api.github.com/repos/%s/contents/holdings.json" % REPO)
        return json.loads(base64.b64decode(d["content"]).decode("utf-8"))


COMMIT_KEY = {"morning": "晨报更新", "review": "收盘复盘更新"}


def is_fresh(kind):
    """判断今天是否已有对应类型的提交记录。
    返回 True=今天已发布 / False=今天未发布 / None=无法判定（接口失败）"""
    key = COMMIT_KEY.get(kind, "更新")
    td = today_bj()
    try:
        cs = _req("https://api.github.com/repos/%s/commits?per_page=10" % REPO, token())
    except Exception:
        try:
            cs = _req("https://api.github.com/repos/%s/commits?per_page=10" % REPO)
        except Exception:
            return None
    for c in cs:
        msg = c["commit"]["message"].split("\n")[0]
        if key in msg and td in msg:
            return True
    return False


def cmd_fresh(kind):
    td = today_bj()
    r = is_fresh(kind)
    key = COMMIT_KEY.get(kind, "更新")
    line("== 新鲜度检查(%s) @ %s ==" % (kind, now_bj()))
    if r is True:
        line("[FRESH] 今日已有提交：%s %s" % (key, td))
        return 0
    if r is False:
        line("[STALE] 最近提交中没有「%s %s」——今天的内容尚未发布" % (key, td))
        try:
            cs = _req("https://api.github.com/repos/%s/commits?per_page=3" % REPO, token())
            for c in cs:
                line("  - %s" % c["commit"]["message"].split("\n")[0])
        except Exception:
            pass
        return 1
    line("[UNKNOWN] 提交查询失败，无法判定新鲜度（可能限流或网络问题）")
    return 2


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
    # 今日提交状态（区分"今天新写的"与"昨天留下的"）
    fm, fr = is_fresh("morning"), is_fresh("review")
    fmt = lambda x: "已发布" if x is True else ("未发布" if x is False else "未知")
    line("今日提交: 晨报=%s | 复盘=%s" % (fmt(fm), fmt(fr)))
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


def cmd_put_daily(path, kind=None):
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
        # 提交说明：优先用显式类型（保证"晨报更新/收盘复盘更新"前缀可被新鲜度检查识别）
        if kind in COMMIT_KEY:
            msg = "%s %s" % (COMMIT_KEY[kind], new.get("date", ""))
        else:
            msg = "daily 更新 %s" % new.get("date", "")
            try:
                old, _ = get_file("daily.json")
                if old.get("morning") != new.get("morning") and old.get("review") == new.get("review"):
                    msg = "%s %s" % (COMMIT_KEY["morning"], new.get("date", ""))
                elif old.get("review") != new.get("review") and old.get("morning") == new.get("morning"):
                    msg = "%s %s" % (COMMIT_KEY["review"], new.get("date", ""))
            except Exception:
                pass
        payload = {
            "message": msg,
            "content": base64.b64encode(
                json.dumps(new, ensure_ascii=False, indent=1).encode("utf-8")).decode(),
            "sha": sha,
        }
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
    # 新鲜度校验：必须有今天对应类型的提交，否则可能是在校验昨日遗留内容
    fresh = is_fresh(kind)
    if fresh is False:
        problems.append("仓库无「%s %s」提交记录，当前内容可能是昨日遗留"
                        % (COMMIT_KEY.get(kind, "更新"), td))
    elif fresh is None:
        line("[WARN] 提交记录查询失败，本次跳过新鲜度校验")
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
        return cmd_put_daily(a[0], a[1] if len(a) > 1 else None) if a else 1
    if c == "fresh":
        return cmd_fresh(a[0] if a else "morning")
    if c == "verify":
        return cmd_verify(a[0] if a else "morning")
    if c == "alert":
        return cmd_alert(a[0] if a else "未说明")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
