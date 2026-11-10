"""最小 MCP 服务器：把 ai-radar 的公开台账变成任何 agent 都能调用的工具。

设计约束
--------
1. **单文件、零依赖、只用标准库。** 这就是「小核心」：别人克隆公开仓库就能跑，
   不需要安装整个 ai-radar（那套要 httpx/trafilatura/pyyaml/yt-dlp，几十兆、
   还带网络抓取能力）。要传播的应该是**能读的那一小块**，不是整台机器。
2. **只读。** 不写文件、不回调服务、不执行外部命令、不访问除数据源以外的地址。
3. **数据源只有一个**：同目录的 index.json，或 --snapshot 指定的路径/URL。

明确不做的事（写在这里，是为了让别人能审计，也为了约束自己）
------------------------------------------------------------
- 不自我复制、不伪装成别的程序、不向宿主注入代码、不修改宿主任何文件。
- 它只是一个被宿主**主动注册**的只读查询工具。宿主随时可以删掉这一个文件卸载。

为什么寄生式的传播不成立
------------------------
病毒能传播，前提是宿主没有选择权。MCP 宿主（Claude Desktop、Cursor、
各种 agent 框架）的运营方**有**选择权：他们看得到 manifest，看得到源码，
可随时撤销。在这种环境里，「伪装」不是优势，是让整台机器被判定为不可信的
最快方式 —— 一旦被标记，同一作者的所有产物都会被连带审查。

所以这里走的是另一条路：把接口做小、做透明、做到别人**愿意**装。

用法
----
    # 本地
    python mcp_server.py --snapshot ./index.json

    # 远程（无需克隆）
    python mcp_server.py --snapshot https://raw.githubusercontent.com/www1987wl/ai-radar-ledger/main/index.json

    # 注册到 MCP 客户端（示例）
    {"mcpServers": {"ai-radar": {"command": "python", "args": ["mcp_server.py"]}}}

协议：JSON-RPC 2.0 over stdio，每行一个 JSON 对象。
实现了 initialize / tools/list / tools/call / ping 四个方法。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ai-radar"
SERVER_VERSION = "0.1.0"

DEFAULT_REMOTE = (
    "https://raw.githubusercontent.com/www1987wl/ai-radar-ledger/main/index.json"
)

# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------


def load_snapshot(spec: str | None = None) -> dict:
    """读快照。spec 为 http(s) URL 时联网取，否则按本地路径读。"""
    target = spec or os.environ.get("AI_RADAR_SNAPSHOT")
    if not target:
        here = Path(globals().get("__file__") or "mcp_server.py").resolve().parent
        local = here / "index.json"
        target = str(local) if local.exists() else DEFAULT_REMOTE

    if target.startswith(("http://", "https://")):
        req = urllib.request.Request(
            target, headers={"User-Agent": f"{SERVER_NAME}-mcp/{SERVER_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return json.loads(Path(target).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------


def _pct(p) -> str:
    try:
        return f"{float(p) * 100:.0f}%"
    except (TypeError, ValueError):
        return "?"


def _f3(v) -> str:
    """Brier 这类小数只给三位 —— 0.16000000000000003 是浮点噪声，不是精度。"""
    try:
        return f"{float(v):.3f}"
    except (TypeError, ValueError):
        return "?"


def tool_status(snap: dict, _args: dict) -> str:
    fit = snap.get("fitness") or {}
    comp = fit.get("components") or {}
    preds = (snap.get("predictions") or {}).get("summary") or {}
    sysinfo = snap.get("system") or {}
    lines = [
        f"ai-radar 第 {sysinfo.get('generation')} 代（出生 {sysinfo.get('born_at')}）",
        f"适应度 {fit.get('value')}  公式 v{fit.get('formula_version')}  窗口 {fit.get('window_days')} 天",
        "",
        f"深加工率   {comp.get('deep_rate')}",
        f"断言校验率 {comp.get('verify_rate')}",
        f"预测校准   {comp.get('calibration')}  来源 {comp.get('calibration_source')}",
        f"成本指数   {comp.get('cost_index')}（每条目 {comp.get('calls_per_item')} 次模型调用）",
        "",
        f"台账：已结算 {preds.get('resolved')} · 开放 {preds.get('open')} · "
        f"已放弃 {preds.get('expired')} · 平均 Brier {_f3(preds.get('mean_brier'))}",
        f"快照生成于 {snap.get('generated_at')}",
        "",
        "提醒：已结算样本很小时，校准值经过了向中性值收缩（样本越多越接近实测）。",
    ]
    return "\n".join(lines)


def tool_predictions(snap: dict, args: dict) -> str:
    status = str(args.get("status") or "resolved").lower()
    limit = int(args.get("limit") or 20)
    p = snap.get("predictions") or {}
    rows: list[dict] = []
    note = ""

    if status in ("resolved", "all"):
        for r in p.get("resolved") or []:
            rows.append(
                {
                    "id": r.get("id"),
                    "statement": r.get("statement"),
                    "probability": r.get("probability"),
                    "resolve_by": r.get("resolve_by"),
                    "outcome": r.get("outcome"),
                    "brier": r.get("brier"),
                    "resolved_at": (r.get("resolved_at") or "")[:10],
                    "status": "resolved",
                }
            )
    if status in ("open", "all"):
        recent = p.get("open_recent") or []
        summary = p.get("summary") or {}
        note = (
            f"（开放预测共 {summary.get('open')} 条，快照里只收录最近 "
            f"{len(recent)} 条，完整列表不在公开范围内）"
        )
        for r in recent:
            rows.append(
                {
                    "id": r.get("id"),
                    "statement": r.get("statement"),
                    "probability": r.get("probability"),
                    "resolve_by": r.get("resolve_by"),
                    "status": "open",
                }
            )

    rows = rows[:limit]
    if not rows:
        return "没有符合条件的预测。"

    out = []
    for r in rows:
        head = f"#{r['id']} [{r['status']}] p={_pct(r['probability'])} 截止 {r.get('resolve_by')}"
        if r.get("status") == "resolved":
            head += f" 结果={r.get('outcome')} Brier={_f3(r.get('brier'))}"
        out.append(head)
        out.append(f"  {r.get('statement')}")
    if note:
        out.append("")
        out.append(note)
    return "\n".join(out)


def tool_calibration(snap: dict, args: dict) -> str:
    limit = int(args.get("limit") or 50)
    p = snap.get("predictions") or {}
    summary = p.get("summary") or {}
    resolved = (p.get("resolved") or [])[:limit]
    n = summary.get("resolved") or 0
    brier = summary.get("mean_brier")

    lines = [
        f"已结算 {n} 条，平均 Brier {_f3(brier)}",
        "",
        "怎么读这个数：",
        "  Brier 0.00 = 完美；0.25 = 永远猜 50%；1.00 = 永远猜错方向。",
    ]
    if n and n < 10:
        lines.append(
            f"  ⚠ n={n} 太小，这个平均值还不能当能力证据。少于约 30 条时，"
            "区间比点估计更有意义。"
        )
    lines += ["", "明细："]
    for r in resolved:
        lines.append(
            f"  #{r.get('id')} p={_pct(r.get('probability'))} "
            f"结果={r.get('outcome')} Brier={_f3(r.get('brier'))} "
            f"({(r.get('resolved_at') or '')[:10]})"
        )
        lines.append(f"    {r.get('statement')}")
    return "\n".join(lines)


def tool_evolution(snap: dict, _args: dict) -> str:
    gens = snap.get("generations") or []
    if not gens:
        return "没有代际记录。"
    out = ["代  父代  状态        适应度   变更"]
    for g in gens:
        muts = "; ".join(
            f"{m.get('kind')} {m.get('source_id')} {m.get('field')}->{m.get('to')}"
            for m in (g.get("mutations") or [])
        ) or "-"
        fit = g.get("fitness")
        fit_s = "-" if fit is None else f"{float(fit):.4f}"
        out.append(
            f"{g.get('gen'):<3} {str(g.get('parent_gen') if g.get('parent_gen') is not None else '-'):<5} "
            f"{str(g.get('status')):<11} {fit_s:<8} {muts}"
        )
    out.append("")
    out.append("状态含义：kept=优于父代保留 / reverted=不如父代已回滚 / active=正在运行待裁决")
    return "\n".join(out)


TOOLS = {
    "radar_status": {
        "fn": tool_status,
        "description": "当前世代、适应度拆解、台账计数。判断这个系统现在准不准，先调这个。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "radar_predictions": {
        "fn": tool_predictions,
        "description": "读取预测台账。每条预测在做出时即固定概率与截止日，事后不可修改。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["resolved", "open", "all"],
                    "description": "默认 resolved（有实际结果的）",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
            },
            "additionalProperties": False,
        },
    },
    "radar_calibration": {
        "fn": tool_calibration,
        "description": "校准记录：已结算预测的 Brier 分数与明细。用来评估这个信息源的可靠性。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}
            },
            "additionalProperties": False,
        },
    },
    "radar_evolution": {
        "fn": tool_evolution,
        "description": "进化史：系统改过自己哪些配置、为什么改、结果变好还是变坏（含被回滚的失败）。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}


# ---------------------------------------------------------------------------
# JSON-RPC 分发
# ---------------------------------------------------------------------------


def _err(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def handle(msg: dict, snap: dict | None = None) -> dict | None:
    """处理一条 JSON-RPC 消息。通知（无 id）返回 None。"""
    if not isinstance(msg, dict):
        return _err(None, -32600, "Invalid Request")
    mid = msg.get("id")
    method = msg.get("method")

    if mid is None:
        return None  # notification，不回复

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "tools": [
                    {
                        "name": name,
                        "description": spec["description"],
                        "inputSchema": spec["inputSchema"],
                    }
                    for name, spec in TOOLS.items()
                ]
            },
        }

    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        spec = TOOLS.get(name)
        if spec is None:
            return _err(mid, -32602, f"Unknown tool: {name}")
        if snap is None:
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": "无法读取台账快照。"}],
                    "isError": True,
                },
            }
        try:
            text = spec["fn"](snap, args if isinstance(args, dict) else {})
        except Exception as exc:  # noqa: BLE001
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": f"工具执行失败: {exc}"}],
                    "isError": True,
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {"content": [{"type": "text", "text": text}]},
        }

    return _err(mid, -32601, f"Method not found: {method}")


def serve(stdin=None, stdout=None, snapshot: str | None = None) -> None:
    """stdio 主循环。每行一条 JSON-RPC。"""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout

    try:
        snap = load_snapshot(snapshot)
    except Exception as exc:  # noqa: BLE001
        # 读不到数据也要能起来 —— 否则宿主会以为服务器挂了
        print(f"[{SERVER_NAME}] 快照加载失败: {exc}", file=sys.stderr)
        snap = None

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = _err(None, -32700, "Parse error")
        else:
            if isinstance(msg, list):
                resp = [_handle_one(m, snap) for m in msg]
            else:
                resp = _handle_one(msg, snap)
        if resp is None:
            continue
        stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        stdout.flush()


def _handle_one(msg, snap):
    try:
        return handle(msg, snap)
    except Exception as exc:  # noqa: BLE001
        return _err(None, -32603, f"Internal error: {exc}")


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    snapshot = None
    if "--snapshot" in argv:
        i = argv.index("--snapshot")
        if i + 1 < len(argv):
            snapshot = argv[i + 1]
    serve(snapshot=snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
