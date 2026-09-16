#!/bin/sh
# opencode 容器入口 · 只做一件镜像做不了的事:按 .env 现生成 provider 配置。
#
# opencode 只从配置文件读 provider,不认 LLM_* 环境变量 —— 不生成这个文件,它会回落到
# 内置的 OpenCode Zen,你在 .env 里填的网关根本不会被调用,现象是「能聊天但答得驴唇不对马嘴」。
# 改完 .env 重新 `docker compose up -d opencode` 即生效。
#
# 以前这里还补三件事,现在都在源头修好了,故删除:
#   · pip 补装 mcp<2 —— 镜像自 1.18.12-slim.1 起用 pip --target 装的就是 1.x
#   · sed 改 uzi_mcp.py 的 httpx 超时 —— 改成读 UZI_HTTP_TIMEOUT(见 scripts/opencode-mcp/uzi_mcp.py)
#   · sed 改 .opencode/opencode.jsonc 的 MCP timeout —— 镜像源头已是 180000
set -e

python3 /opt/hunter-boot/gen-config.py

# 新镜像(1.18.12-slim.1 起)是单文件二进制,旧镜像只有 bun + 源码。两种都要能起来:
# 这个脚本是 bind mount 进容器的(compose 里 ./scripts/opencode:/opt/hunter-boot:ro),
# 「脚本新 + 镜像旧」和「镜像新 + 脚本旧」都是常态。后者由镜像里的 bun 垫片兜住。
if command -v opencode >/dev/null 2>&1; then
    exec opencode serve --hostname 0.0.0.0 --port 3901
fi

echo "[boot] 镜像里没有 opencode 二进制(旧镜像),回落到源码启动" >&2
exec bun run packages/opencode/src/index.ts serve --hostname 0.0.0.0 --port 3901
