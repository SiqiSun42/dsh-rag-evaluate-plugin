"""dsh-rag-evaluate 的 MCP 服务入口。

当前不注册任何工具：第①步（发现链路）由 skills/rag-evaluate 承担，
不经过 MCP。工具将在需要确定性逻辑的步骤中逐步加入。
"""

from mcp.server import MCPServer

mcp = MCPServer("rag-evaluate")


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
